import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
import re

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
# 3. RENDERIZADO DEL DIAGRAMA INTERACTIVO (SIN IFRAMES)
# ==========================================
def inyectar_svg_interactivo(ruta_svg, datos_equipos):
    with open(ruta_svg, "r", encoding="utf-8") as f:
        svg_content = f.read()

    # Inyectamos los datos matemáticamente en el XML
    for unit_id, metricas in datos_equipos.items():
        info_texto = f"EQUIPO: {unit_id}&#10;"
        for key, value in metricas.items():
            if value != 0: 
                info_texto += f"{key}: {value}&#10;"
            
        id_alternativo = unit_id.replace("-", "")
        patron = rf'(<g[^>]*id=["\']?({unit_id}|{id_alternativo})["\']?[^>]*>)'
        reemplazo = rf'\1\n    <title>{info_texto}</title>'
        
        svg_content = re.sub(patron, reemplazo, svg_content, flags=re.IGNORECASE)

    # LA SOLUCIÓN MÁGICA: Usar st.markdown con unsafe_allow_html=True
    # Esto incrusta el SVG de forma nativa en la página, permitiendo que 
    # el navegador muestre los tooltips sin restricciones de seguridad.
    
    html_code = f"""
    <div style="display: flex; justify-content: center; margin: 20px 0;">
        <style>
            /* Cambia el cursor para indicar interactividad */
            svg g[id] {{ cursor: pointer; transition: opacity 0.2s; }}
            svg g[id]:hover {{ opacity: 0.7; }}
        </style>
        {svg_content}
    </div>
    """
    
    st.markdown(html_code, unsafe_allow_html=True)
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
