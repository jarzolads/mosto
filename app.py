import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import base64
import google.generativeai as genai

# =================================================================
# 1. CONFIGURACIÓN DE LA PÁGINA Y FUNCIONES DE APOYO
# =================================================================
st.set_page_config(page_title="IALabs - Simulador de Mosto", layout="wide")

def get_svg_base64(file_path):
    """Convierte el SVG a base64 para incrustarlo en el HTML."""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
            return base64.b64encode(data).decode()
    except FileNotFoundError:
        return None

# =================================================================
# 2. LÓGICA DE SIMULACIÓN (BioSTEAM)
# =================================================================
def ejecutar_simulacion(f_mosto, t_mosto, p_descarga):
    # Limpiar flowsheet para evitar errores de ID duplicado
    bst.main_flowsheet.clear()
    
    # Definición de componentes y termodinámica
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)
    
    # Corrientes (IDs numéricos según Diagrama en blanco2.svg)
    mosto = bst.Stream("1", Water=f_mosto*0.9, Ethanol=f_mosto*0.1, 
                       units="kg/hr", T=t_mosto + 273.15, P=101325)
    
    # Vapor de reciclo (Corriente 6)
    vapor_reciclo = bst.Stream("6", Water=0, Ethanol=0, units="kg/hr", phase='g')
    
    # Equipos con nomenclatura actualizada
    P110 = bst.Pump("P-110", ins=mosto, P=p_descarga * 101325)
    
    # V-210: Intercambiador de proceso (Usa el vapor 6 para precalentar)
    V210 = bst.HXprocess("V-210", 
                         ins=(P110-0, vapor_reciclo), 
                         outs=("3", "7"), 
                         phase0="l", phase1="g")
    V210.outs[0].T = 85 + 273.15
    
    # V-310: Calentador auxiliar (Pink circle)
    V310 = bst.HXutility("V-310", ins=V210-0, outs="4", T=92 + 273.15)
    
    # Válvula de expansión
    V100 = bst.IsenthalpicValve("V-100", ins=V310-0, outs="5", P=101325)
    
    # K-410: Tanque Flash (Green tank)
    K410 = bst.Flash("K-410", ins=V100-0, outs=(vapor_reciclo, "9"), P=101325, Q=0)
    
    # P-510: Bomba de producto/reciclo
    P510 = bst.Pump("P-510", ins=K410-1, outs="10", P=101325)
    
    # Crear sistema con reciclo de vapor
    sys = bst.System("planta_mosto", path=(P110, V210, V310, V100, K410, P510), recycle=vapor_reciclo)
    sys.simulate()
    return sys

def extraer_resultados(sistema):
    resultados = {}
    for u in sistema.units:
        # Manejo de energía
        calor = sum(hu.duty for hu in u.heat_utilities)/3600 if hasattr(u, 'heat_utilities') and u.heat_utilities else 0
        potencia = u.power_utility.rate if hasattr(u, "power_utility") and u.power_utility else 0
        t_salida = u.outs[0].T - 273.15 if u.outs else 0
        
        resultados[u.ID] = {
            "temp": round(t_salida, 1),
            "calor": round(calor, 2),
            "potencia": round(potencia, 2)
        }
    return resultados

# =================================================================
# 3. INTERFAZ DE USUARIO
# =================================================================
st.title("👨‍🏫 Simulador Interactivo: Planta de Mosto (v2)")
st.markdown("Ajuste los parámetros y desplace el ratón sobre los equipos para ver los datos.")

with st.sidebar:
    st.header("Control de Proceso")
    f_in = st.slider("Flujo Alimentación (kg/h)", 500, 2000, 1000)
    t_in = st.slider("Temp. Alimentación (°C)", 15, 45, 25)
    p_in = st.slider("Presión Bombeo (bar)", 2.0, 6.0, 4.0)

# Ejecución
planta = ejecutar_simulacion(f_in, t_in, p_in)
datos = extraer_resultados(planta)

# =================================================================
# 4. RENDERIZADO INTERACTIVO (CSS TOOLTIPS)
# =================================================================
svg_b64 = get_svg_base64("Diagrama en blanco2.svg")

if svg_b64:
    # Coordenadas recalibradas para el nuevo diagrama
    zonas = {
        "P-110": {"t": "16%", "l": "12%", "w": "7%", "h": "12%"},
        "V-210": {"t": "18%", "l": "30%", "w": "13%", "h": "10%"},
        "V-310": {"t": "16%", "l": "47%", "w": "7%", "h": "12%"},
        "K-410": {"t": "13%", "l": "70%", "w": "8%", "h": "26%"},
        "P-510": {"t": "66%", "l": "72%", "w": "7%", "h": "12%"},
    }

    hotspots_html = ""
    for uid, pos in zonas.items():
        if uid in datos:
            d = datos[uid]
            hotspots_html += f"""
            <div class="hotspot" style="top:{pos['t']}; left:{pos['l']}; width:{pos['w']}; height:{pos['h']};">
                <div class="tooltip-text">
                    <strong>📊 Equipo: {uid}</strong><br><br>
                    • Temp. Salida: <span class="data-val">{d['temp']} °C</span><br>
                    • Carga Térmica: <span class="data-val">{d['calor']} kW</span><br>
                    • Potencia: <span class="data-val">{d['potencia']} kW</span>
                </div>
            </div>
            """

    full_html = f"""
    <style>
        .main-container {{ position: relative; width: 100%; max-width: 1000px; margin: auto; }}
        .diagram-img {{ width: 100%; height: auto; display: block; }}
        .hotspot {{ position: absolute; cursor: pointer; z-index: 5; transition: background 0.3s; }}
        .hotspot:hover {{ background: rgba(255, 75, 75, 0.1); border: 1px dashed #ff4b4b; }}
        .tooltip-text {{
            visibility: hidden; width: 220px; background-color: #262730; color: #ffffff;
            border-radius: 8px; padding: 15px; position: absolute; z-index: 100;
            bottom: 110%; left: 50%; transform: translateX(-50%);
            opacity: 0; transition: opacity 0.3s; border: 1px solid #ff4b4b;
            font-family: sans-serif; box-shadow: 0px 4px 15px rgba(0,0,0,0.5);
            pointer-events: none;
        }}
        .hotspot:hover .tooltip-text {{ visibility: visible; opacity: 1; }}
        .data-val {{ color: #ff4b4b; font-weight: bold; }}
    </style>
    <div class="main-container">
        <img src="data:image/svg+xml;base64,{svg_b64}" class="diagram-img">
        {hotspots_html}
    </div>
    """
    st.components.v1.html(full_html, height=700)
else:
    st.error("Archivo 'Diagrama en blanco2.svg' no encontrado.")

# =================================================================
# 5. TUTOR IA
# =================================================================
st.divider()
if st.button("Consultar Tutor IA"):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Analiza estos resultados de simulación BioSTEAM: {datos}. ¿Cómo afecta el reciclo de vapor (corriente 6) al precalentamiento en V-210?"
        with st.spinner("Analizando datos de la planta..."):
            st.info(model.generate_content(prompt).text)
    except Exception:
        st.error("Error al conectar con Gemini. Verifique sus Secrets.")
