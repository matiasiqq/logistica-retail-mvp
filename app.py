import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
from geopy.geocoders import Nominatim

# ==========================================
# 1. CONFIGURACIÓN E IDENTIDAD DE MARCA
# ==========================================
st.set_page_config(page_title="Optiaflux | Logística Inteligente", page_icon="🌐", layout="wide")

# Inicializamos el geocodificador para buscar direcciones
geolocalizador = Nominatim(user_agent="optiaflux_app")

# ==========================================
# 2. MOTORES MATEMÁTICOS Y LÓGICOS
# ==========================================
def obtener_coordenadas(direccion):
    """Convierte texto de dirección en coordenadas."""
    try:
        ubicacion = geolocalizador.geocode(f"{direccion}, Chile")
        if ubicacion:
            return [ubicacion.latitude, ubicacion.longitude]
        return None
    except:
        return None

def calcular_distancia_haversine(coord1, coord2):
    """Calcula distancia real considerando la curvatura de la Tierra."""
    R = 6371.0 
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c 

def calcular_ruta_optima(coordenadas_tienda, lista_pedidos):
    """Algoritmo del vecino más cercano para ruteo logístico."""
    ruta_final = [{"id": "TIENDA", "coordenadas": coordenadas_tienda, "cliente": "Centro de Distribución", "direccion": "Central Operativa"}]
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
    """Motor predictivo simulado de Optiaflux."""
    velocidad_base_kmh = 45.0 
    peso_trafico = {"Bajo (Despejado)": 1.0, "Moderado (Normal)": 0.70, "Alto (Taco)": 0.40}
    peso_clima = {"Óptimo (Despejado)": 1.0, "Adverso (Lluvia/Niebla)": 0.85}
    
    velocidad_real = velocidad_base_kmh * peso_trafico[nivel_trafico] * peso_clima[clima]
    minutos_predichos = (distancia_km / velocidad_real) * 60
    return round(minutos_predichos)

# ==========================================
# 3. MEMORIA DEL SISTEMA Y DATOS BASE
# ==========================================
if 'lista_pedidos' not in st.session_state:
    st.session_state['lista_pedidos'] = []

coord_tienda = [-20.2730, -70.1030] # Base operativa

# ==========================================
# 4. INTERFAZ GRÁFICA (FRONTEND)
# ==========================================

# -- Menú Lateral --
st.sidebar.title("🌐 Optiaflux")
st.sidebar.markdown("---")
seccion = st.sidebar.radio("Navegación:", ["📥 Cargar Pedidos", "🧠 Rutas e IA Predictiva"])
st.sidebar.markdown("---")

st.sidebar.subheader("⚙️ Parámetros del Entorno (IA)")
st.sidebar.caption("Alimenta el motor predictivo con el estado actual.")
ia_trafico = st.sidebar.selectbox("Nivel de Tráfico actual:", ["Bajo (Despejado)", "Moderado (Normal)", "Alto (Taco)"])
ia_clima = st.sidebar.selectbox("Condición Climática:", ["Óptimo (Despejado)", "Adverso (Lluvia/Niebla)"])

st.sidebar.markdown("---")
st.sidebar.info(f"📦 Pedidos en memoria: {len(st.session_state['lista_pedidos'])}")

# -- Sección 1: Gestión de Pedidos --
if seccion == "📥 Cargar Pedidos":
    st.title("📥 Gestión de Pedidos - Optiaflux")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Geocodificador (Ingreso Manual)")
        with st.form("form_pedido"):
            id_pedido = st.text_input("ID del Pedido (Ej: PED-005)")
            nombre_cliente = st.text_input("Nombre del Cliente")
            direccion_texto = st.text_input("Dirección (Ej: Los Cóndores 123, Alto Hospicio)")
            
            btn_guardar = st.form_submit_button("➕ Buscar y Agregar Pedido")
            
            if btn_guardar and id_pedido and nombre_cliente and direccion_texto:
                with st.spinner('Motor Optiaflux buscando coordenadas...'):
                    coords = obtener_coordenadas(direccion_texto)
                    if coords:
                        nuevo_pedido = {
                            "id": id_pedido, 
                            "coordenadas": coords, 
                            "cliente": nombre_cliente,
                            "direccion": direccion_texto
                        }
                        st.session_state['lista_pedidos'].append(nuevo_pedido)
                        st.success(f"¡Éxito! Coordenadas mapeadas para: {direccion_texto}")
                    else:
                        st.error("❌ Optiaflux no encontró la dirección. Intenta agregar la ciudad.")

    with col2:
        st.subheader("Carga Masiva (BETA)")
        archivo_subido = st.file_uploader("Sube tu archivo .csv", type=["csv"])
        if archivo_subido is not None:
            df_cargado = pd.read_csv(archivo_subido)
            st.dataframe(df_cargado)
            st.info("Módulo de integración masiva en desarrollo.")

    st.markdown("---")
    st.subheader("📋 Base de Datos Optiaflux")
    if len(st.session_state['lista_pedidos']) > 0:
        df_mostrar = pd.DataFrame([{
            "ID": p["id"], 
            "Cliente": p["cliente"], 
            "Dirección": p["direccion"]
        } for p in st.session_state['lista_pedidos']])
        st.dataframe(df_mostrar, use_container_width=True)
        
        if st.button("🗑️ Limpiar Memoria"):
            st.session_state['lista_pedidos'] = []
            st.rerun()
    else:
        st.warning("No hay carga logística asignada.")

# -- Sección 2: Mapa y Ruteo Predictivo --
elif seccion == "🧠 Rutas e IA Predictiva":
    st.title("🧠 Optiaflux: Motor de Ruteo Predictivo")
    
    if len(st.session_state['lista_pedidos']) == 0:
        st.info("⚠️ Ingresa pedidos en la sección anterior para activar el motor.")
    else:
        col_datos, col_mapa = st.columns([1, 2])
        
        with col_datos:
            st.markdown("### ⚙️ Centro de Comando")
            if st.button("🚀 Ejecutar Algoritmo de Ruteo", type="primary", use_container_width=True):
                ruta_ordenada, total_km = calcular_ruta_optima(coord_tienda, st.session_state['lista_pedidos'])
                eta_ia = motor_ia_predictivo(total_km, ia_trafico, ia_clima)
                
                st.success(f"**Distancia Optimizada:** {round(total_km, 2)} km")
                st.metric(label="⏱️ ETA Predicho por Optiaflux IA", value=f"{eta_ia} min", delta=f"Tráfico: {ia_trafico.split(' ')[0]}", delta_color="inverse")
                
                # --- NUEVO: Generación de Archivo Descargable ---
                df_descarga = pd.DataFrame([{
                    "Secuencia": i,
                    "ID Pedido": paso["id"],
                    "Cliente": paso["cliente"],
                    "Dirección": paso.get("direccion", "N/A")
                } for i, paso in enumerate(ruta_ordenada)])
                
                csv_export = df_descarga.to_csv(index=False).encode('utf-8')
                
                st.download_button(
                    label="📥 Descargar Hoja de Ruta (CSV/Excel)",
                    data=csv_export,
                    file_name='hoja_ruta_optiaflux.csv',
                    mime='text/csv',
                    use_container_width=True
                )
                st.markdown("---")
                # ------------------------------------------------
                
                st.markdown("#### Manifiesto de Ruta:")
                for i, paso in enumerate(ruta_ordenada):
                    dir_mostrar = paso.get('direccion', 'Centro de Distribución')
                    st.write(f"**{i}.** {paso['id']} ({dir_mostrar})")
                
                with col_mapa:
                    st.markdown("### 📍 Panel de Rastreo Satelital")
                    mapa = folium.Map(location=coord_tienda, zoom_start=13)
                    folium.Marker(coord_tienda, popup="OPERA CENTRAL", icon=folium.Icon(color="black", icon="home")).add_to(mapa)
                    
                    puntos_ruta = [coord_tienda]
                    for paso in ruta_ordenada[1:]:
                        folium.Marker(
                            paso['coordenadas'], 
                            popup=f"{paso['id']} - {paso['cliente']}", 
                            icon=folium.Icon(color="red", icon="info-sign")
                        ).add_to(mapa)
                        puntos_ruta.append(paso['coordenadas'])
                        
                    folium.PolyLine(puntos_ruta, color="purple", weight=5, opacity=0.8).add_to(mapa)
                    st_folium(mapa, width=800, height=500)
