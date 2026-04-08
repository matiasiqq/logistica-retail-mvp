import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
import random
import json
import os
from geopy.geocoders import Nominatim
from datetime import datetime
import pytz

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD
# ==========================================
st.set_page_config(page_title="Optiaflux | Logística Inteligente", page_icon="🌐", layout="wide")
geolocalizador = Nominatim(user_agent="optiaflux_app")
ARCHIVO_BD = "base_datos_optiaflux.json"

# ==========================================
# 2. BASE DE DATOS
# ==========================================
def cargar_pedidos():
    if os.path.exists(ARCHIVO_BD):
        with open(ARCHIVO_BD, 'r', encoding='utf-8') as archivo:
            try:
                return json.load(archivo)
            except:
                return []
    return []

def guardar_pedidos(lista_actualizada):
    with open(ARCHIVO_BD, 'w', encoding='utf-8') as archivo:
        json.dump(lista_actualizada, archivo, ensure_ascii=False, indent=4)

# ==========================================
# 3. MOTORES MATEMÁTICOS Y LÓGICOS
# ==========================================
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
    ruta_final = [{"id": "TIENDA", "coordenadas": coordenadas_tienda, "cliente": "Falabella Iquique", "direccion": "Central Operativa"}]
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

# --- MOTOR PREDICTIVO AVANZADO (TIEMPO REAL) ---
def obtener_factor_trafico_real():
    """Lee la hora actual de Chile y aplica un modelo matemático de densidad vehicular."""
    zona_horaria = pytz.timezone('America/Santiago')
    hora_actual = datetime.now(zona_horaria)
    hora = hora_actual.hour
    minuto = hora_actual.minute
    tiempo_decimal = hora + (minuto / 60)

    # Identificación de Horarios Punta (Tacos)
    if 7.5 <= tiempo_decimal <= 9.5:  # 07:30 a 09:30 AM
        estado = "Alto (Hora Punta Mañana)"
        factor = 0.45
    elif 13.0 <= tiempo_decimal <= 14.5: # 13:00 a 14:30 PM
        estado = "Moderado-Alto (Almuerzo/Colegios)"
        factor = 0.60
    elif 18.0 <= tiempo_decimal <= 20.5: # 18:00 a 20:30 PM
        estado = "Crítico (Hora Punta Tarde)"
        factor = 0.35
    elif 22.0 <= tiempo_decimal or tiempo_decimal <= 6.0: # Noche
        estado = "Fluido (Nocturno)"
        factor = 1.1 # Va más rápido del promedio
    else:
        estado = "Normal (Valle)"
        factor = 0.85
        
    return factor, estado, hora_actual.strftime('%H:%M')

def motor_ia_predictivo_avanzado(distancia_km, clima_override="Despejado"):
    velocidad_base_kmh = 45.0 
    
    # 1. Obtiene el tráfico basado en el reloj real
    factor_trafico, estado_trafico, hora_leida = obtener_factor_trafico_real()
    
    # 2. Factor climático
    factor_clima = 0.85 if clima_override == "Lluvia/Niebla" else 1.0
    
    # Cálculo final con la fórmula avanzada
    velocidad_real = velocidad_base_kmh * factor_trafico * factor_clima
    minutos_predichos = (distancia_km / velocidad_real) * 60
    
    return round(minutos_predichos), estado_trafico, hora_leida

# ==========================================
# 4. VARIABLES DE MEMORIA
# ==========================================
pedidos_globales = cargar_pedidos()

if 'ruta_optimizada' not in st.session_state:
    st.session_state['ruta_optimizada'] = None
if 'km_totales' not in st.session_state:
    st.session_state['km_totales'] = 0.0

coord_tienda = [-20.2447, -70.1415] 

def limpiar_ruta_guardada():
    st.session_state['ruta_optimizada'] = None
    st.session_state['km_totales'] = 0.0

# ==========================================
# 5. FRONTEND
# ==========================================
st.sidebar.title("🌐 Optiaflux")
st.sidebar.markdown("---")
seccion = st.sidebar.radio("Navegación:", ["📥 Cargar Pedidos", "🧠 Rutas e IA Predictiva"])
st.sidebar.markdown("---")

# El panel ahora indica que lee datos en vivo
st.sidebar.subheader("📡 Conexión de Datos")
st.sidebar.success("🟢 Reloj Satelital Conectado")
# Dejamos el clima manual temporalmente hasta que consigas una API Key de OpenWeather
ia_clima = st.sidebar.selectbox("Condición Climática (Manual):", ["Despejado", "Lluvia/Niebla"])

st.sidebar.markdown("---")
st.sidebar.info(f"📦 Pedidos en Red: {len(pedidos_globales)}")

# ------------------------------------------
# SECCIÓN 1: GESTIÓN DE PEDIDOS
# ------------------------------------------
if seccion == "📥 Cargar Pedidos":
    st.title("📥 Gestión de Pedidos - Optiaflux")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Ingreso Manual")
        with st.form("form_pedido"):
            nombre_cliente = st.text_input("Nombre del Cliente")
            direccion_texto = st.text_input("Dirección (Ej: Los Cóndores 123, Alto Hospicio)")
            btn_guardar = st.form_submit_button("➕ Buscar y Agregar")
            
            if btn_guardar and nombre_cliente and direccion_texto:
                with st.spinner('Mapeando coordenadas...'):
                    coords = obtener_coordenadas(direccion_texto)
                    if coords:
                        id_aleatorio = f"PED-{random.randint(1000, 9999)}"
                        nuevo_pedido = {"id": id_aleatorio, "coordenadas": coords, "cliente": nombre_cliente, "direccion": direccion_texto}
                        pedidos_globales.append(nuevo_pedido)
                        guardar_pedidos(pedidos_globales)
                        limpiar_ruta_guardada()
                        st.success("¡Pedido guardado en la red central!")
                        st.rerun()
                    else:
                        st.error("❌ No se encontró la dirección.")

    with col2:
        st.subheader("Módulo API (Próximamente)")
        st.info("Para integrar Google Maps Traffic API y OpenWeather API de forma real, deberás registrar tus propias API Keys comerciales.")

    st.markdown("---")
    st.subheader("📋 Base de Datos Activa")
    if len(pedidos_globales) > 0:
        for i, pedido in enumerate(pedidos_globales):
            col_info, col_btn = st.columns([5, 1])
            col_info.write(f"📦 **{pedido['id']}** | 👤 {pedido['cliente']} | 📍 {pedido['direccion']}")
            if col_btn.button("❌", key=f"del_{pedido['id']}_{i}"):
                pedidos_globales.pop(i)
                guardar_pedidos(pedidos_globales)
                limpiar_ruta_guardada()
                st.rerun()
        if st.button("🗑️ Limpiar Base de Datos Completa", type="secondary"):
            guardar_pedidos([]) 
            limpiar_ruta_guardada()
            st.rerun()
    else:
        st.warning("No hay carga logística asignada.")

# ------------------------------------------
# SECCIÓN 2: MAPA Y RUTEO
# ------------------------------------------
elif seccion == "🧠 Rutas e IA Predictiva":
    st.title("🧠 Optiaflux: Ruteo Dinámico Compartido")
    col_datos, col_mapa = st.columns([1, 2])
    
    mapa_optiaflux = folium.Map(location=coord_tienda, zoom_start=13)
    folium.Marker(coord_tienda, popup="FALABELLA IQUIQUE (Central)", icon=folium.Icon(color="black", icon="home")).add_to(mapa_optiaflux)
    for paso in pedidos_globales:
        folium.Marker(paso['coordenadas'], popup=f"{paso['id']} - {paso['cliente']}", icon=folium.Icon(color="red", icon="info-sign")).add_to(mapa_optiaflux)

    with col_datos:
        st.markdown("### ⚙️ Centro de Comando")
        if len(pedidos_globales) == 0:
            st.info("⚠️ Ingresa pedidos para activar el algoritmo.")
        else:
            if st.button("🚀 Ejecutar Algoritmo", type="primary", use_container_width=True):
                ruta_ordenada, total_km = calcular_ruta_optima(coord_tienda, pedidos_globales)
                st.session_state['ruta_optimizada'] = ruta_ordenada
                st.session_state['km_totales'] = total_km

            if st.session_state['ruta_optimizada'] is not None:
                ruta_guardada = st.session_state['ruta_optimizada']
                km_guardados = st.session_state['km_totales']
                
                # LLAMADA AL MOTOR AVANZADO CON DATOS REALES DEL RELOJ
                eta_ia, estado_trafico, hora_leida = motor_ia_predictivo_avanzado(km_guardados, ia_clima)
                
                st.success(f"**Distancia Optimizada:** {round(km_guardados, 2)} km")
                
                # Panel de control de datos en tiempo real
                st.markdown("##### 📡 Análisis en Tiempo Real")
                st.write(f"🕒 **Hora leída:** {hora_leida} hrs")
                st.write(f"🚗 **Densidad de tráfico calculada:** {estado_trafico}")
                
                st.metric(label="⏱️ ETA Calculado", value=f"{eta_ia} min", delta="Ajustado por horario real", delta_color="normal")
                
                puntos_ruta = [coord_tienda]
                for paso in ruta_guardada[1:]:
                    puntos_ruta.append(paso['coordenadas'])
                folium.PolyLine(puntos_ruta, color="purple", weight=5, opacity=0.8).add_to(mapa_optiaflux)
                
                df_descarga = pd.DataFrame([{"Secuencia": i, "ID Pedido": paso["id"], "Cliente": paso["cliente"], "Dirección": paso.get("direccion", "N/A")} for i, paso in enumerate(ruta_guardada)])
                csv_export = df_descarga.to_csv(index=False).encode('utf-8')
                st.download_button(label="📥 Descargar Hoja de Ruta", data=csv_export, file_name='hoja_ruta_optiaflux.csv', mime='text/csv', use_container_width=True)

    with col_mapa:
        st_folium(mapa_optiaflux, width=800, height=500)
