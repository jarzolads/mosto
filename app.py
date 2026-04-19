import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import base64
import google.generativeai as genai

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(layout="wide", page_title="Simulador BioSTEAM")

def get_svg_base64(file_path):
    """Convierte el SVG a base64 para incrustarlo como imagen de fondo."""
    with open(file_path, "rb") as f:
        data = f.read()
        return base64.b64encode(data).decode()

# ==========================================
# 2. FUNCIÓN NÚCLEO DE SIMULACIÓN
# ==========================================
def ejecutar_simulacion(flujo_mosto, temp_mosto, presion_bomba):
    bst.main_flowsheet.clear()
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)
    
    mosto = bst.Stream("1-MOSTO", Water=flujo_mosto*0.9, Ethanol=flujo_mosto*0.1, 
                       units="kg/hr", T=temp_mosto + 273.15, P=101325)
    vinazas_retorno = bst.Stream("Vinazas-Retorno", Water=200, Ethanol=0, 
                                 units="kg/hr", T=95 + 273.15, P=300000)
    
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

def obtener_datos_equipos(sistema):
    datos_equipos = {}
    for u in sistema.units:
        calor_kw = 0.0
        if hasattr(u, 'heat_utilities') and u.heat_utilities:
            calor_kw = sum(hu.duty for hu in u.heat_utilities) / 3600
        elif hasattr(u, "duty") and u.duty is not None:
            calor_kw = u.duty / 3600
            
        potencia = u.power_utility.rate if hasattr(u, "power_utility") and u.power_utility else 0.0
        temp_out = u.outs[0].T - 273.15 if u.outs else 0
        
        datos_equipos[u.ID] = {
            "Térmica (kW)": round(calor_kw, 2),
            "Eléctrica (kW)": round(potencia, 2),
            "T. Salida (°C)": round(temp_out, 1)
        }
    return datos_equipos

# ==========================================
# 3. INTERFAZ PRINCIPAL
# ==========================================
st.title("Proceso de Concentración de Mosto")
st.markdown("Pasa el mouse sobre los equipos para ver los datos del balance en tiempo real.")

with st.sidebar:
    st.header("Parámetros de Operación")
    flujo = st.slider("Flujo Mosto (kg/h)", 500, 1500, 1000)
    temp = st.slider("Temp. Entrada (°C)", 20, 40, 25)
    presion = st.slider("Presión P-100 (bar)", 2, 6, 4)

sys_simulado = ejecutar_simulacion(flujo, temp, presion)
datos = obtener_datos_equipos(sys_simulado)

# ==========================================
# 4. RENDERIZADO INTERACTIVO (HTML + CSS)
# ==========================================
try:
    svg_base64 = get_svg_base64("Diagrama en blanco.svg")
    
    # Coordenadas calculadas matemáticamente para superponerse a tu SVG (1200x800)
    zonas = {
        "P-100": {"top": "8%", "left": "10%", "w": "6%", "h": "10%"},
        "W-210": {"top": "14%", "left": "26%", "w": "14%", "h": "8%"},
        "W-220": {"top": "28%", "left": "43%", "w": "6%", "h": "9%"},
        "V-100": {"top": "41%", "left": "55%", "w": "5%", "h": "6%"},
        "V-1":   {"top": "49%", "left": "64%", "w": "6%", "h": "16%"},
        "W-310": {"top": "34%", "left": "73%", "w": "6%", "h": "9%"},
        "P-200": {"top": "72%", "left": "73%", "w": "6%", "h": "9%"},
    }

    # Generamos los "divs" invisibles para cada equipo
    hotspots_html = ""
    for unit_id, metricas in datos.items():
        if unit_id in zonas:
            z = zonas[unit_id]
            detalle = ""
            for k, v in metricas.items():
                if v != 0: 
                    detalle += f"• {k}: <span class='data-val'>{v}</span><br>"

            hotspots_html += f"""
            <div class="hotspot" style="top: {z['top']}; left: {z['left']}; width: {z['w']}; height: {z['h']};">
                <div class="tooltip-text">
                    <strong>📊 Equipo: {unit_id}</strong><br><br>
                    {detalle}
                </div>
            </div>
            """

    # Ensamblamos el CSS y el HTML siguiendo tu lógica
    html_completo = f"""
    <style>
        .container {{
            position: relative;
            display: inline-block;
            width: 100%;
            max-width: 1200px;
        }}
        .overlay-image {{
            display: block;
            width: 100%;
            height: auto;
        }}
        .hotspot {{
            position: absolute;
            cursor: crosshair;
            /* Descomenta la siguiente línea si quieres ver dónde están los cuadros invisibles */
            /* border: 1px solid rgba(255, 0, 0, 0.5); background: rgba(255, 0, 0, 0.1); */
        }}
        .tooltip-text {{
            visibility: hidden;
            width: max-content;
            min-width: 180px;
            background-color: #262730;
            color: #fff;
            text-align: left;
            border-radius: 8px;
            padding: 15px;
            position: absolute;
            z-index: 10;
            bottom: 110%; /* Aparece justo encima del equipo */
            left: 50%;
            transform: translateX(-50%);
            opacity: 0;
            transition: opacity 0.3s;
            border: 1px solid #ff4b4b;
            font-family: sans-serif;
            box-shadow: 0px 4px 10px rgba(0,0,0,0.5);
            pointer-events: none; /* Evita parpadeos al mover el mouse */
        }}
        .hotspot:hover .tooltip-text {{
            visibility: visible;
            opacity: 1;
        }}
        .data-val {{ color: #ff4b4b; font-weight: bold; }}
    </style>

    <div class="container">
        <img src="data:image/svg+xml;base64,{svg_base64}" class="overlay-image">
        {hotspots_html}
    </div>
    """
    
    # st.components.v1.html aísla el CSS, garantizando que el hover funcione
    st.components.v1.html(html_completo, height=750)

except FileNotFoundError:
    st.error("Archivo 'Diagrama en blanco.svg' no encontrado en el directorio raíz.")

# ==========================================
# 5. TUTOR IA
# ==========================================
st.divider()
st.subheader("Tutor de Ingeniería Química (IA)")
if st.button("Analizar eficiencia térmica con Gemini"):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"Actúa como un ingeniero. Analiza estos consumos de la simulación: {datos}."
    with st.spinner("El tutor está analizando los datos..."):
        respuesta = model.generate_content(prompt)
        st.info(respuesta.text)
