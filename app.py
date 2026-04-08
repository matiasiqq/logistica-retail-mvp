import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd

# 1. Configuración profesional de la página
st.set_page_config(page_title="Logística Retail Pro", page_icon="🚚", layout="wide")

# 2. Funciones Matemáticas y de Lógica
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

# 3. Inicializar la "Memoria" del software (Session State)
# Esto asegura que los pedidos no se borren al cambiar de pestaña
if 'lista_pedidos' not in st.session_state:
    st.session_state['lista_pedidos'] = []

coord_tienda = [-20.2730, -70.1030] # Coordenadas base (Ej: Alto Hospicio)

# ==========================================
# 4. ESTRUCTURA VISUAL: MENÚ LATERAL
# ==========================================
st.sidebar.title("🚚 Panel de Control")
st.sidebar.markdown("---")
# Creamos las secciones del menú
seccion = st.sidebar.radio("Navegación:", ["📥 Cargar Pedidos", "🗺️ Rutas y Mapa"])
st.sidebar.markdown("---")
st.sidebar.info(f"📦 Pedidos en memoria: {len(st.session_state['lista_pedidos'])}")

# ==========================================
# SECCIÓN 1: INGRESO DE PEDIDOS
# ==========================================
if seccion == "📥 Cargar Pedidos":
    st.title("📥 Sistema de Ingreso de Pedidos")
    st.markdown("Agrega pedidos manualmente o sube una planilla completa.")
    
    col1, col2 = st.columns(2)
    
    # Opción A: Ingreso Manual
    with col1:
        st.subheader("Ingreso Manual")
        with st.form("form_pedido"):
            id_pedido = st.text_input("ID del Pedido (Ej: PED-005)")
            nombre_cliente = st.text_input("Nombre del Cliente")
            lat = st.number_input("Latitud (Ej: -20.2650)", format="%.4f")
            lon = st.number_input("Longitud (Ej: -70.1100)", format="%.4f")
            
            btn_guardar = st.form_submit_button("➕ Agregar Pedido")
            
            if btn_guardar and id_pedido and nombre_cliente:
                nuevo_pedido = {
                    "id": id_pedido, 
                    "coordenadas": [lat, lon], 
                    "cliente": nombre_cliente
                }
                st.session_state['lista_pedidos'].append(nuevo_pedido)
                st.success("¡Pedido agregado a la memoria!")

    # Opción B: Carga Masiva (CSV)
    with col2:
        st.subheader("Carga Masiva (CSV)")
        archivo_subido = st.file_uploader("Sube tu archivo de Excel (.csv)", type=["csv"])
        if archivo_subido is not None:
            # Leemos el archivo usando Pandas
            df_cargado = pd.read_csv(archivo_subido)
            st.dataframe(df_cargado)
            if st.button("Procesar Archivo"):
                st.success("Funcionalidad lista para conectar. (Requiere estandarizar columnas)")

    # Mostrar la tabla actual de pedidos guardados
    st.markdown("---")
    st.subheader("📋 Base de Datos Actual")
    if len(st.session_state['lista_pedidos']) > 0:
        # Transformamos la lista a un DataFrame para que se vea como tabla profesional
        df_mostrar = pd.DataFrame([{
            "ID": p["id"], 
            "Cliente": p["cliente"], 
            "Latitud": p["coordenadas"][0],
            "Longitud": p["coordenadas"][1]
        } for p in st.session_state['lista_pedidos']])
        st.dataframe(df_mostrar, use_container_width=True)
        
        if st.button("🗑️ Borrar todos los pedidos"):
            st.session_state['lista_pedidos'] = []
            st.rerun()
    else:
        st.warning("No hay pedidos cargados en el sistema.")

# ==========================================
# SECCIÓN 2: MAPA Y OPTIMIZACIÓN
# ==========================================
elif seccion == "🗺️ Rutas y Mapa":
    st.title("🗺️ Optimización de Rutas Logísticas")
    
    if len(st.session_state['lista_pedidos']) == 0:
        st.info("⚠️ Ve a la sección 'Cargar Pedidos' e ingresa al menos un pedido para calcular la ruta.")
    else:
        col_datos, col_mapa = st.columns([1, 2])
        
        with col_datos:
            st.markdown("### ⚙️ Panel de Cálculo")
            if st.button("🚀 Calcular Ruta Óptima", type="primary", use_container_width=True):
                ruta_ordenada, total_km = calcular_ruta_optima(coord_tienda, st.session_state['lista_pedidos'])
                
                st.success(f"**Distancia Optimizada:** {round(total_km, 2)} km")
                minutos_estimados = round((total_km / 35) * 60)
                st.info(f"⏱️ **ETA Estimado:** {minutos_estimados} minutos")
                
                # Lista ordenada de entregas
                st.markdown("#### Secuencia de Entrega:")
                for i, paso in enumerate(ruta_ordenada):
                    st.write(f"{i}. {paso['id']} ({paso['cliente']})")
                
                # Renderizar el mapa en la otra columna
                with col_mapa:
                    st.markdown("### 📍 Vista Satelital")
                    mapa = folium.Map(location=coord_tienda, zoom_start=13)
                    folium.Marker(coord_tienda, popup="TIENDA", icon=folium.Icon(color="red", icon="home")).add_to(mapa)
                    
                    puntos_ruta = [coord_tienda]
                    for paso in ruta_ordenada[1:]:
                        folium.Marker(
                            paso['coordenadas'], 
                            popup=f"{paso['id']} - {paso['cliente']}", 
                            icon=folium.Icon(color="blue", icon="info-sign")
                        ).add_to(mapa)
                        puntos_ruta.append(paso['coordenadas'])
                        
                    folium.PolyLine(puntos_ruta, color="green", weight=4, opacity=0.8).add_to(mapa)
                    st_folium(mapa, width=800, height=500)


