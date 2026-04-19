import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
import plotly.graph_objects as go
import base64

# ==========================================
# 1. FUNCIÓN NÚCLEO DE SIMULACIÓN
# ==========================================
#@st.cache_data(show_spinner=False)
def ejecutar_simulacion(flujo_mosto, temp_mosto, presion_bomba):
    # CRÍTICO: Limpiar el entorno para evitar "Duplicate ID" en cada recarga
    bst.main_flowsheet.clear()
    
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)
    
    # Corrientes dinámicas
    mosto = bst.Stream("1-MOSTO", Water=flujo_mosto*0.9, Ethanol=flujo_mosto*0.1, 
                       units="kg/hr", T=temp_mosto + 273.15, P=101325)
    vinazas_retorno = bst.Stream("Vinazas-Retorno", Water=200, Ethanol=0, 
                                 units="kg/hr", T=95 + 273.15, P=300000)
    
    # Equipos
    P100 = bst.Pump("P-100", ins=mosto, P=presion_bomba * 101325)
    W210 = bst.HXprocess("W-210", ins=(P100-0, vinazas_retorno), outs=("3-Mosto-Pre", "Drenaje"), phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15
    W220 = bst.HXutility("W-220", ins=W210-0, outs="Mezcla", T=92 + 273.15)
    V100 = bst.IsenthalpicValve("V-100", ins=W220-0, outs="Mezcla-Bifásica", P=101325)
    V1 = bst.Flash("V-1", ins=V100-0, outs=("Vapor caliente", "Vinazas"), P=101325, Q=0)
    W310 = bst.HXutility("W-310", ins=V1-0, outs="Producto Final", T=25 + 273.15)
    P200 = bst.Pump("P-200", ins=V1-1, outs=vinazas_retorno, P=3 * 101325)
    
    eth_sys = bst.System("planta_etanol", path=(P100, W210, W220, V100, V1, W310, P200))
    eth_sys.simulate()
    
    return eth_sys

# ==========================================
# 2. EXTRACCIÓN DE DATOS Y CORRECCIÓN DE ERRORES
# ==========================================
def obtener_datos_equipos(sistema):
    datos_equipos = {}
    for u in sistema.units:
        calor_kw = 0.0
        # Solución al error de tanques Flash adiabáticos
        if hasattr(u, 'heat_utilities') and u.heat_utilities:
            calor_kw = sum(hu.duty for hu in u.heat_utilities) / 3600
        elif hasattr(u, "duty") and u.duty is not None:
            calor_kw = u.duty / 3600
            
        potencia = u.power_utility.rate if hasattr(u, "power_utility") and u.power_utility else 0.0
        temp_out = u.outs[0].T - 273.15 if u.outs else 0
        
        datos_equipos[u.ID] = {
            "Energía Térmica (kW)": round(calor_kw, 2),
            "Energía Eléctrica (kW)": round(potencia, 2),
            "Temp. Salida (°C)": round(temp_out, 1)
        }
    return datos_equipos

# ==========================================
# 3. RENDERIZADO DEL DIAGRAMA INTERACTIVO (VÍA PLOTLY)
# ==========================================
def inyectar_svg_interactivo(ruta_svg, datos_equipos):
    # 1. Leer el SVG y codificarlo para que Plotly lo acepte como imagen de fondo
    with open(ruta_svg, "rb") as f:
        encoded_svg = base64.b64encode(f.read()).decode()
    svg_uri = f"data:image/svg+xml;base64,{encoded_svg}"

    # 2. Coordenadas de los equipos mapeadas desde tu archivo original (1200x800)
    # Nota: Plotly invierte el eje Y respecto al formato SVG
    coords = {
        "P-100": {"x": 150, "y": 700},
        "W-210": {"x": 400, "y": 650},
        "W-220": {"x": 550, "y": 550},
        "V-100": {"x": 700, "y": 450},
        "V-1":   {"x": 810, "y": 340},
        "W-310": {"x": 910, "y": 500},
        "P-200": {"x": 910, "y": 200}
    }

    fig = go.Figure()

    # 3. Añadimos tu diagrama SVG como fondo
    fig.add_layout_image(
        dict(
            source=svg_uri,
            xref="x", yref="y",
            x=0, y=800,  # Origen en la esquina superior izquierda
            sizex=1200, sizey=800,
            sizing="stretch", layer="below"
        )
    )

    # 4. Colocamos marcadores "invisibles" con los datos de BioSTEAM
    for unit_id, metricas in datos_equipos.items():
        if unit_id in coords:
            # Construimos el texto que aparecerá al pasar el cursor
            hover_text = f"<b>Equipo: {unit_id}</b><br>"
            for key, value in metricas.items():
                if value != 0: 
                    hover_text += f"{key}: {value}<br>"

            fig.add_trace(go.Scatter(
                x=[coords[unit_id]["x"]],
                y=[coords[unit_id]["y"]],
                mode="markers",
                marker=dict(size=60, color="rgba(0,0,0,0)"), # Círculo grande pero transparente
                hoverinfo="text",
                hovertext=hover_text,
                showlegend=False
            ))

    # 5. Ocultamos los ejes para que parezca una aplicación pura
    fig.update_layout(
        xaxis=dict(visible=False, range=[0, 1200]),
        yaxis=dict(visible=False, range=[0, 800]),
        margin=dict(l=0, r=0, t=0, b=0),
        plot_bgcolor="white",
        hovermode="closest",
        dragmode=False # Evita que el usuario mueva el dibujo por error
    )

    # 6. Enviamos el gráfico interactivo a Streamlit
    # st.plotly_chart es 100% compatible y nativo
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
# ==========================================
# 4. INTERFAZ Y TUTOR IA
# ==========================================
st.set_page_config(layout="wide", page_title="Simulador BioSTEAM")
st.title("Proceso de Concentración de Mosto")

with st.sidebar:
    st.header("Parámetros de Operación")
    flujo = st.slider("Flujo Mosto (kg/h)", 500, 1500, 1000)
    temp = st.slider("Temp. Entrada (°C)", 20, 40, 25)
    presion = st.slider("Presión P-100 (bar)", 2, 6, 4)

sys_simulado = ejecutar_simulacion(flujo, temp, presion)
datos = obtener_datos_equipos(sys_simulado)

st.subheader("Diagrama de Flujo de Proceso (Pase el cursor sobre los equipos)")
# Asegúrese de que su archivo SVG tenga los id="P-100", id="W-210" en los grupos (<g>) correspondientes
inyectar_svg_interactivo("Diagrama en blanco.svg", datos)

# Integración del Tutor IA
st.divider()
st.subheader("Tutor de Ingeniería Química (IA)")
if st.button("Analizar eficiencia térmica con Gemini"):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    Actúa como un profesor universitario de ingeniería química. Analiza brevemente 
    estos consumos energéticos de una simulación de concentración de mosto: {datos}. 
    ¿Qué recomendaciones darías a un estudiante para mejorar la eficiencia del intercambiador W-210?
    """
    with st.spinner("El tutor está analizando los datos..."):
        respuesta = model.generate_content(prompt)
        st.info(respuesta.text)
st.write("IDs buscados en el SVG:", list(datos.keys()))
