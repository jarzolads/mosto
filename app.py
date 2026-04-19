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
    
    # Corrientes de entrada
    mosto = bst.Stream("1-MOSTO", Water=f_mosto*0.9, Ethanol=f_mosto*0.1, 
                       units="kg/hr", T=t_mosto + 273.15, P=101325)
    
    vinazas_retorno = bst.Stream("Vinazas-Retorno", Water=200, Ethanol=0, 
                                 units="kg/hr", T=95 + 273.15, P=300000)
    
    # Red de equipos
    P100 = bst.Pump("P-100", ins=mosto, P=p_descarga * 101325)
    
    W210 = bst.HXprocess("W-210", 
                         ins=(P100-0, vinazas_retorno), 
                         outs=("3-Mosto-Pre", "Drenaje"), 
                         phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15
    
    W220 = bst.HXutility("W-220", ins=W210-0, outs="Mezcla", T=92 + 273.15)
    
    V100 = bst.IsenthalpicValve("V-100", ins=W220-0, outs="Mezcla-Bifásica", P=101325)
    
    V1 = bst.Flash("V-1", ins=V100-0, outs=("Vapor caliente", "Vinazas"), P=101325, Q=0)
    
    W310 = bst.HXutility("W-310", ins=V1-0, outs="Producto Final", T=25 + 273.15)
    
    P200 = bst.Pump("P-200", ins=V1-1, outs=vinazas_retorno, P=3 * 101325)
    
    # Crear sistema y simular
    sys = bst.System("planta_etanol", path=(P100, W210, W220, V100, V1, W310, P200))
    sys.simulate()
    return sys

def extraer_resultados(sistema):
    resultados = {}
    for u in sistema.units:
        # Prevención de error .duty en tanques adiabáticos
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
# 3. INTERFAZ DE USUARIO (Streamlit)
# =================================================================
st.title("👨‍🏫 Simulador Interactivo: Concentración de Mosto")
st.markdown("Mueva los sliders para ajustar la planta y pase el mouse sobre los equipos en el diagrama.")

with st.sidebar:
    st.header("Parámetros de Entrada")
    f_in = st.slider("Flujo de Mosto (kg/h)", 500, 2000, 1000)
    t_in = st.slider("Temperatura Entrada (°C)", 15, 45, 25)
    p_in = st.slider("Presión Bomba P-100 (bar)", 2.0, 6.0, 4.0)

# Ejecutar simulación
planta = ejecutar_simulacion(f_in, t_in, p_in)
datos = extraer_resultados(planta)

# =================================================================
# 4. RENDERIZADO DEL DIAGRAMA CON TOOLTIPS CSS
# =================================================================
svg_b64 = get_svg_base64("Diagrama en blanco.svg")

if svg_b64:
    # Definición de Hotspots (Coordenadas % para el SVG 1200x800)
    zonas = {
        "P-100": {"t": "7%", "l": "9%", "w": "8%", "h": "12%"},
        "W-210": {"t": "14%", "l": "26%", "w": "15%", "h": "10%"},
        "W-220": {"t": "27%", "l": "43%", "w": "7%", "h": "12%"},
        "V-100": {"t": "40%", "l": "56%", "w": "5%", "h": "8%"},
        "V-1":   {"t": "48%", "l": "64%", "w": "6%", "h": "18%"},
        "W-310": {"t": "33%", "l": "73%", "w": "7%", "h": "12%"},
        "P-200": {"t": "70%", "l": "73%", "w": "7%", "h": "12%"},
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
                    • Q (Calor): <span class="data-val">{d['calor']} kW</span><br>
                    • W (Potencia): <span class="data-val">{d['potencia']} kW</span>
                </div>
            </div>
            """

    full_html = f"""
    <style>
        .main-container {{ position: relative; width: 100%; max-width: 1100px; margin: auto; }}
        .diagram-img {{ width: 100%; height: auto; display: block; }}
        .hotspot {{ position: absolute; cursor: pointer; z-index: 5; transition: background 0.3s; }}
        .hotspot:hover {{ background: rgba(255, 75, 75, 0.1); border: 1px dashed #ff4b4b; }}
        .tooltip-text {{
            visibility: hidden; width: 200px; background-color: #1e1e1e; color: #ffffff;
            border-radius: 6px; padding: 12px; position: absolute; z-index: 100;
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
    st.error("Archivo 'Diagrama en blanco.svg' no encontrado.")

# =================================================================
# 5. INTEGRACIÓN CON GEMINI (TUTOR IA)
# =================================================================
st.divider()
if st.button("Consultar Tutor IA"):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Como experto en ingeniería química, analiza estos resultados de simulación para mis estudiantes: {datos}. ¿Cómo impacta el intercambio de calor en W-210 en la eficiencia global?"
        with st.spinner("El tutor está analizando el proceso..."):
            st.info(model.generate_content(prompt).text)
    except Exception as e:
        st.error("Error en la conexión con Gemini. Verifique su API Key en los Secrets.")
