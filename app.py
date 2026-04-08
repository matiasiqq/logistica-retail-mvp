import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
from geopy.geocoders import Nominatim

# 1. Nueva Identidad: Optiaflux
st.set_page_config(page_title="Optiaflux | Logística Inteligente", page_icon="🌐", layout="wide")

geolocalizador = Nominatim(user_agent="optiaflux_app")

def obtener_coordenadas(direccion):
    try:
        ubicacion = geolocalizador.geocode(f"{direccion}, Chile")
        if ubicacion:
            return [ubicacion.latitude, ubicacion.longitude]
        return None
    except:
        return None

def calcular_distancia_haversine(coord1, coord2):
    R = 6371.0 
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c 

def calcular_ruta_optima(coordenadas_tienda, lista_pedidos):
    ruta_final = [{"id": "TIENDA", "coordenadas": coordenadas_tienda, "cliente": "Centro de Distribución"}]
    pedidos_pendientes = lista_pedidos.copy()
    punto_actual = coordenadas_tienda
    distancia_total = 0.0

    while pedidos_pendientes:
        siguiente_parada = min(
            pedidos_pendientes, 
            key=lambda p: calcular_distancia_haversine(punto_actual, p['coordenadas'])
        )
        distancia_total += calcular_distancia_haversine(punto_actual, siguiente_parada['coordenadas'])
        ruta_final.append(siguiente_parada)
        punto_actual = siguiente_parada['coordenadas']
        pedidos_pendientes.remove(siguiente_parada)
        
    return ruta_final, distancia_total

# ==========================================
# NUEVO: MOTOR PREDICTIVO IA (Simulación MVP)
# ==========================================
def motor_ia_predictivo(distancia_km, nivel_trafico, clima):
    """
    Simula un modelo de Machine Learning ajustando la velocidad real
    del vehículo según factores externos para predecir el ETA.
    """
    velocidad_base_kmh = 45.0 # Velocidad ideal promedio en ciudad vacía
    
    # Pesos del modelo (simulando los tensores de una red neuronal)
    peso_trafico = {"Bajo (Despejado)": 1.0, "Moderado (Normal)": 0.70, "Alto (Taco)": 0.40}
    peso_clima = {"Óptimo (Despejado)": 1.0, "Adverso (Lluvia/Niebla)": 0.85}
    
    # Calculamos la velocidad real inferida por la IA
    velocidad_real = velocidad_base_kmh * peso_trafico[nivel_trafico] * peso_clima[clima]
    
    # Predecimos los minutos exactos
    minutos_predichos = (distancia_km / velocidad_real) * 60
    return round(minutos_predichos)

if 'lista_pedidos' not in st.session_state:
    st.session_state['lista_pedidos'] = []

coord_tienda = [-20.2730, -70.1030] 

# ==========================================
# MENÚ LATERAL Y PARÁMETROS DE IA
# ==========================================
st.sidebar.title("🌐 Optiaflux")
st.sidebar.markdown("---")
seccion = st.sidebar.radio("Navegación:", ["📥 Cargar Pedidos", "🧠 Rutas e IA Predictiva"])
st.sidebar.markdown("---")

# Controles de IA en el panel lateral para alimentar el modelo
st.sidebar.subheader("⚙️ Parámetros del Entorno (IA)")
st.sidebar.caption("Alimenta el motor predictivo con el estado actual.")
ia_trafico = st.sidebar.selectbox("Nivel de Tráfico actual:", ["Bajo (Despejado)", "Moderado (Normal)", "Alto (Taco)"])
ia_clima = st.sidebar.selectbox("Condición Climática:", ["Óptimo (Despejado)", "Adverso (Lluvia/Niebla)"])

st.sidebar.markdown("---")
st.sidebar.info(f"📦 Pedidos en memoria: {len(st.session_state['lista_pedidos'])}")

# ==========================================
# SECCIÓN 1: INGRESO DE PEDIDOS
# ==========================================
if seccion == "📥 Cargar Pedidos":
    st.title("📥 Gestión de Pedidos - Optiaflux")
    
    col1, col2 = st.columns(2)
    
    with col

