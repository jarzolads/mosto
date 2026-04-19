import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import base64
import google.generativeai as genai

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="IALabs - Simulador BioSTEAM", layout="wide")

def get_svg_base64(file_path):
    """Codifica el SVG para que el navegador lo renderice sin restricciones."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# --- NÚCLEO DE SIMULACIÓN (BioSTEAM) ---
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
    
    sys = bst.System("planta", path=(P100, W210, W220, V100, V1, W310, P200))
    sys.simulate()
    return sys

def extraer_datos_interactivos(sistema):
    res = {}
    for u in sistema.units:
        # Manejo de energía para evitar error de .duty
        calor = sum(hu.duty for hu in u.heat_utilities)/3600 if hasattr(u, 'heat_utilities') and u.heat_utilities else (u.duty/3600 if hasattr(u, 'duty') and u.duty else 0)
        potencia = u.power_utility.rate if hasattr(u, "power_utility") and u.power_utility else 0
        tout = u.outs[0].T - 273.15 if u.outs else 0
        res[u.ID] = {"Q": round(calor, 2), "W": round(potencia, 2), "T": round(tout, 1)}
    return res

# --- INTERFAZ ---
st.title("Concentración de Mosto: Simulación BioSTEAM")
st.markdown("Pasa el cursor sobre los equipos para visualizar el balance en tiempo real.")

with st.sidebar:
    st.header("Parámetros de Entrada")
    flujo = st.slider("Flujo Mosto (kg/h)", 500, 1500, 1000)
    temp = st.slider("Temp. Entrada (°C)", 20, 40, 25)
    presion = st.slider("Presión P-100 (bar)", 2.0, 6.0, 4.0)

# Ejecución de la simulación
sistema_res = ejecutar_simulacion(flujo, temp, presion)
datos_dinamicos = extraer_datos_interactivos(sistema_res)

# --- RENDERIZADO INTERACTIVO (LÓGICA CSS TOOLTIP) ---
try:
    svg_b64 = get_svg_base64("Diagrama en blanco.svg")
    
    # Coordenadas relativas (%) para los hotspots del SVG de 1200x800
    zonas_mapeo = {
        "P-100": {"t": "7.5%", "l": "9.1%", "w": "7%", "h": "13%"},
        "W-210": {"t": "15%", "l": "26.6%", "w": "14%", "h": "8%"},
        "W-220": {"t": "27.5%", "l": "43.3%", "w": "7%", "h": "13%"},
        "V-100": {"t": "40%", "l": "56.6%", "w": "5%", "h": "9%"},
        "V-1":   {"t": "50%", "l": "65%", "w": "5%", "h": "15%"},
        "W-310": {"t": "33.7%", "l": "73.3%", "w": "7%", "h": "13%"},
        "P-200": {"t": "71.2%", "l": "73.3%", "w": "7%", "h": "13%"},
    }

    hotspots_html = ""
    for uid, coord in zonas_mapeo.items():
        if uid in datos_dinamicos:
            d = datos_dinamicos[uid]
            hotspots_html += f"""
            <div class="hotspot" style="top:{coord['t']}; left:{coord['l']}; width:{coord['w']}; height:{coord['h']};">
                <div class="tooltip-text">
                    <strong>📊 Datos {uid}:</strong><br><br>
                    • Temp. Salida: <span class="data-val">{d['T']} °C</span><br>
                    • E. Térmica: <span class="data-val">{d['Q']} kW</span><br>
                    • E. Eléctrica: <span class="data-val">{d['W']} kW</span>
                </div>
            </div>
            """

    # Ensamblado final de HTML/CSS inyectado
    html_interactivo = f"""
    <style>
        .container {{ position: relative; width: 100%; max-width: 1200px; margin: auto; }}
        .overlay-image {{ width: 100%; height: auto; display: block; }}
        .hotspot {{ position: absolute; cursor: crosshair; z-index: 5; }}
        /* Para depurar coordenadas, puedes activar: border: 1px solid red; background: rgba(255,0,0,0.1); */
        .tooltip-text {{
            visibility: hidden; width: 220px; background-color: #262730; color: #fff;
            border-radius: 8px; padding: 15px; position: absolute; z-index: 100;
            bottom: 115%; left: 50%; transform: translateX(-50%);
            opacity: 0; transition: opacity 0.3s; border: 1px solid #ff4b4b;
            font-family: sans-serif; box-shadow: 0px 4px 10px rgba(0,0,0,0.5);
            pointer-events: none;
        }}
        .hotspot:hover .tooltip-text {{ visibility: visible; opacity: 1; }}
        .data-val {{ color: #ff4b4b; font-weight: bold; }}
    </style>
    <div class="container">
        <img src="data:image/svg+xml;base64,{svg_b64}" class="overlay-image">
        {hotspots_html}
    </div>
    """
    st.components.v1.html(html_interactivo, height=700)

except FileNotFoundError:
    st.error("Asegúrate de que 'Diagrama en blanco.svg' esté en la raíz del proyecto.")

# --- TUTOR IA ---
st.divider()
if st.button("Consultar Tutor IA (Gemini)"):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Analiza estos resultados de simulación de ingeniería química: {datos_dinamicos}."
    with st.spinner("El tutor está analizando el proceso..."):
        st.info(model.generate_content(prompt).text)
