import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd

# 1. Configuración general de la página web
st.set_page_config(page_title="Logística Retail IA", layout="wide")


# 2. Motor Matemático: Cálculo de distancia real (Haversine)
def calcular_distancia_haversine(coord1, coord2):
    R = 6371.0  # Radio de la Tierra en kilómetros
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c  # Devuelve la distancia en KM


# 3. Motor Logístico: Enrutamiento Óptimo
def calcular_ruta_optima(coordenadas_tienda, lista_pedidos):
    ruta_final = [{"id": "TIENDA", "coordenadas": coordenadas_tienda, "cliente": "Centro de Distribución"}]
    pedidos_pendientes = lista_pedidos.copy()
    punto_actual = coordenadas_tienda
    distancia_total = 0.0

    while pedidos_pendientes:
        # Busca el pedido más cercano al punto donde está el camión ahora
        siguiente_parada = min(
            pedidos_pendientes,
            key=lambda p: calcular_distancia_haversine(punto_actual, p['coordenadas'])
        )
        distancia_tramo = calcular_distancia_haversine(punto_actual, siguiente_parada['coordenadas'])
        distancia_total += distancia_tramo
        ruta_final.append(siguiente_parada)
        punto_actual = siguiente_parada['coordenadas']
        pedidos_pendientes.remove(siguiente_parada)

    return ruta_final, distancia_total


# ==========================================
# 4. FRONTEND: INTERFAZ DE USUARIO E INTERACTIVIDAD
# ==========================================

st.title("🚚 Panel de Gestión y Rutas (Prototipo V1)")
st.markdown("Sistema inteligente de predicción y ordenamiento logístico.")

# Coordenadas base (Centro de distribución)
coord_tienda = [-20.2730, -70.1030]

# Base de datos simulada de los pedidos del día
pedidos = [
    {"id": "PED-001", "coordenadas": [-20.2650, -70.1100], "cliente": "Juan P."},
    {"id": "PED-002", "coordenadas": [-20.2800, -70.0950], "cliente": "María G."},
    {"id": "PED-003", "coordenadas": [-20.2700, -70.1200], "cliente": "Carlos L."},
    {"id": "PED-004", "coordenadas": [-20.2900, -70.0800], "cliente": "Ana S."}
]

# Dividimos la pantalla en dos columnas (Dashboard a la izq, Mapa a la der)
col1, col2 = st.columns([1, 2])

with col1:
    st.markdown("### 📦 Pedidos Pendientes")
    df_pedidos = pd.DataFrame(pedidos)
    # Mostramos los pedidos en una tabla bonita
    st.dataframe(df_pedidos[['id', 'cliente']], use_container_width=True)

    # Botón interactivo principal
    if st.button("🚀 Calcular Ruta Óptima", type="primary"):
        st.session_state['ruta_calculada'] = True

# Si el usuario apretó el botón, calculamos y mostramos todo
if 'ruta_calculada' in st.session_state:
    ruta_ordenada, total_km = calcular_ruta_optima(coord_tienda, pedidos)

    with col1:
        st.success(f"**Ruta optimizada:** {round(total_km, 2)} km totales a recorrer.")
        # Estimación básica de tiempo (ETA) asumiendo una velocidad en ciudad de 35 km/h
        minutos_estimados = round((total_km / 35) * 60)
        st.info(f"⏱️ **ETA de la Ruta:** {minutos_estimados} minutos.")

    with col2:
        st.markdown("### 🗺️ Mapa de Entregas")
        # Generamos el mapa centrado en la tienda
        mapa = folium.Map(location=coord_tienda, zoom_start=14)

        # Ponemos el pin rojo para la Tienda
        folium.Marker(coord_tienda, popup="TIENDA", icon=folium.Icon(color="red", icon="home")).add_to(mapa)

        # Trazamos la ruta y ponemos los pines azules para los clientes
        puntos_ruta = [coord_tienda]
        for paso in ruta_ordenada[1:]:
            folium.Marker(
                paso['coordenadas'],
                popup=f"{paso['id']} - {paso['cliente']}",
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(mapa)
            puntos_ruta.append(paso['coordenadas'])

        # Dibujamos la línea verde que conecta el trayecto
        folium.PolyLine(puntos_ruta, color="green", weight=4, opacity=0.8).add_to(mapa)

        # Mostramos el mapa en la web
        st_folium(mapa, width=700, height=500)
else:
    with col2:
        st.info(
            "👈 Presiona 'Calcular Ruta Óptima' en el panel izquierdo para visualizar el mapa interactivo y los tiempos estimados.")




