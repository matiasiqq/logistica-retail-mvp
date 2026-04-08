import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
import random
import json
import os
from geopy.geocoders import Nominatim

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD DE MARCA
# ==========================================
st.set_page_config(page_title="Optiaflux | Logística Inteligente", page_icon="🌐", layout="wide")

geolocalizador = Nominatim(user_agent="optiaflux_app")

# ==========================================
# 2. MOTOR DE BASE DE DATOS PERSISTENTE (NUEVO)
# ==========================================
ARCHIVO_BD = "base_datos_optiaflux.json"

def cargar_pedidos():
    """Lee los pedidos guardados en el archivo del servidor para que todos vean lo mismo."""
    if os.path.exists(ARCHIVO_BD):
        with open(ARCHIVO_BD, 'r', encoding='utf-8') as archivo:
            try:
                return json.load(archivo)
            except:
                return []
    return []

def guardar_pedidos(lista_actualizada):
    """Guarda cualquier cambio de pedidos directamente en el disco duro del servidor."""
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

def motor_ia_predictivo(distancia_km, nivel_trafico, clima):
    velocidad_base_kmh = 45.0 
    peso_trafico = {"Bajo (Despejado)": 1.0, "Moderado (Normal)": 0.70, "Alto (Taco)": 0.40}
    peso_clima = {"Óptimo (Despejado)": 1.0, "Adverso (Lluvia/Niebla)": 0.85}
    velocidad_real = velocidad_base_kmh * peso_trafico[nivel_trafico] * peso_clima[clima]
    minutos_predichos = (distancia_km / velocidad_real) * 60
    return round(minutos_predichos)

# ==========================================
# 4. MEMORIA DEL SISTEMA Y DATOS BASE
# ==========================================

# Cargamos los pedidos desde el archivo (visible para todos)
pedidos_globales = cargar_pedidos()

# Mantenemos la ruta en la memoria temporal para que cada usuario pueda jugar con el clima/tráfico por su cuenta
if 'ruta_optimizada' not in st.session_state:
    st.session_state['ruta_optimizada'] = None
if 'km_totales' not in st.session_state:
    st.session_state['km_totales'] = 0.0

coord_tienda = [-20.2447, -70.1415] # Falabella Iquique

def limpiar_ruta_guardada():
    st.session_state['ruta_optimizada'] = None
    st.session_state['km_totales'] = 0.0

# ==========================================
# 5. INTERFAZ GRÁFICA (FRONTEND)
# ==========================================

st.sidebar.title("🌐 Optiaflux")
st.sidebar.markdown("---")
seccion = st.sidebar.radio("Navegación:", ["📥 Cargar Pedidos", "🧠 Rutas e IA Predictiva"])
st.sidebar.markdown("---")

st.sidebar.subheader("⚙️ Parámetros del Entorno (IA)")
ia_trafico = st.sidebar.selectbox("Nivel de Tráfico actual:", ["Bajo (Despejado)", "Moderado (Normal)", "Alto (Taco)"])
ia_clima = st.sidebar.selectbox("Condición Climática:", ["Óptimo (Despejado)", "Adverso (Lluvia/Niebla)"])

st.sidebar.markdown("---")
st.sidebar.info(f"📦 Pedidos en Base de Datos: {len(pedidos_globales)}")

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
            
            btn_guardar = st.form_submit_button("➕ Buscar y Agregar Pedido")
            
            if btn_guardar and nombre_cliente and direccion_texto:
                with st.spinner('Motor Optiaflux buscando coordenadas...'):
                    coords = obtener_coordenadas(direccion_texto)
                    if coords:
                        id_aleatorio = f"PED-{random.randint(1000, 9999)}"
                        nuevo_pedido = {
                            "id": id_aleatorio, 
                            "coordenadas": coords, 
                            "cliente": nombre_cliente,
                            "direccion": direccion_texto
                        }
                        # Agregamos a la lista y GUARDAMOS en el archivo permanente
                        pedidos_globales.append(nuevo_pedido)
                        guardar_pedidos(pedidos_globales)
                        limpiar_ruta_guardada()
                        st.success(f"¡Éxito! Pedido {id_aleatorio} guardado en la base de datos central.")
                        st.rerun() # Refresca para actualizar la tabla abajo
                    else:
                        st.error("❌ Optiaflux no encontró la dirección. Intenta agregar la ciudad.")

    with col2:
        st.subheader("Carga Masiva (BETA)")
        archivo_subido = st.file_uploader("Sube tu archivo .csv", type=["csv"])
        if archivo_subido is not None:
            st.info("Módulo de integración masiva en desarrollo.")

    st.markdown("---")
    st.subheader("📋 Base de Datos Central Compartida")
    
    if len(pedidos_globales) > 0:
        st.write("Cualquier cambio aquí se reflejará a todos los usuarios conectados.")
        for i, pedido in enumerate(pedidos_globales):
            col_info, col_btn = st.columns([5, 1])
            col_info.write(f"📦 **{pedido['id']}** | 👤 {pedido['cliente']} | 📍 {pedido['direccion']}")
            if col_btn.button("❌ Eliminar", key=f"del_{pedido['id']}_{i}"):
                # Borramos de la lista y GUARDAMOS en el archivo permanente
                pedidos_globales.pop(i)
                guardar_pedidos(pedidos_globales)
                limpiar_ruta_guardada()
                st.rerun()
                
        st.markdown("---")
        if st.button("🗑️ Limpiar Base de Datos Completa", type="secondary"):
            guardar_pedidos([]) # Sobrescribe el archivo con una lista vacía
            limpiar_ruta_guardada()
            st.rerun()
    else:
        st.warning("No hay carga logística asignada en la red.")

# ------------------------------------------
# SECCIÓN 2: MAPA PERMANENTE Y RUTEO
# ------------------------------------------
elif seccion == "🧠 Rutas e IA Predictiva":
    st.title("🧠 Optiaflux: Ruteo Dinámico Compartido")
    
    col_datos, col_mapa = st.columns([1, 2])
    
    mapa_optiaflux = folium.Map(location=coord_tienda, zoom_start=13)
    folium.Marker(
        coord_tienda, 
        popup="FALABELLA IQUIQUE (Central)", 
        icon=folium.Icon(color="black", icon="home")
    ).add_to(mapa_optiaflux)
    
    for paso in pedidos_globales:
        folium.Marker(
            paso['coordenadas'], 
            popup=f"{paso['id']} - {paso['cliente']}", 
            icon=folium.Icon(color="red", icon="info-sign")
        ).add_to(mapa_optiaflux)

    with col_datos:
        st.markdown("### ⚙️ Centro de Comando")
        
        if len(pedidos_globales) == 0:
            st.info("⚠️ Ingresa pedidos en la sección anterior para activar el algoritmo.")
        else:
            if st.button("🚀 Ejecutar Algoritmo de Ruteo", type="primary", use_container_width=True):
                ruta_ordenada, total_km = calcular_ruta_optima(coord_tienda, pedidos_globales)
                st.session_state['ruta_optimizada'] = ruta_ordenada
                st.session_state['km_totales'] = total_km

            if st.session_state['ruta_optimizada'] is not None:
                ruta_guardada = st.session_state['ruta_optimizada']
                km_guardados = st.session_state['km_totales']
                
                eta_ia = motor_ia_predictivo(km_guardados, ia_trafico, ia_clima)
                
                st.success(f"**Distancia Optimizada:** {round(km_guardados, 2)} km")
                st.metric(label="⏱️ ETA Predicho por Optiaflux IA", value=f"{eta_ia} min", delta=f"Tráfico: {ia_trafico.split(' ')[0]}", delta_color="inverse")
                
                puntos_ruta = [coord_tienda]
                for paso in ruta_guardada[1:]:
                    puntos_ruta.append(paso['coordenadas'])
                folium.PolyLine(puntos_ruta, color="purple", weight=5, opacity=0.8).add_to(mapa_optiaflux)
                
                df_descarga = pd.DataFrame([{
                    "Secuencia": i,
                    "ID Pedido": paso["id"],
                    "Cliente": paso["cliente"],
                    "Dirección": paso.get("direccion", "N/A")
                } for i, paso in enumerate(ruta_guardada)])
                
                csv_export = df_descarga.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Descargar Hoja de Ruta",
                    data=csv_export,
                    file_name='hoja_ruta_optiaflux.csv',
                    mime='text/csv',
                    use_container_width=True
                )
                
                st.markdown("---")
                st.markdown("#### Manifiesto de Ruta:")
                for i, paso in enumerate(ruta_guardada):
                    dir_mostrar = paso.get('direccion', 'Centro de Distribución')
                    st.write(f"**{i}.** {paso['id']} ({dir_mostrar})")

    with col_mapa:
        st.markdown("### 📍 Panel de Rastreo Satelital")
        st_folium(mapa_optiaflux, width=800, height=500)
