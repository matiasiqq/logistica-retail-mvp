import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
import random
import os
import sqlite3
import requests
from geopy.geocoders import Nominatim
from datetime import datetime
import pytz
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import plotly.express as px
from folium.plugins import HeatMap

# ==========================================
# 1. CONFIGURACIÓN Y ESTILOS CORPORATIVOS
# ==========================================
st.set_page_config(page_title="Optiaflux | Plataforma Logística", layout="wide", page_icon="🌐")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .stButton>button { border-radius: 5px; font-weight: 600; }
    h1, h2, h3 { color: #1E3A8A; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #1E3A8A; }
    .stExpander { border: 1px solid #E2E8F0; border-radius: 8px; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

geolocalizador = Nominatim(user_agent="optiaflux_erp_v14_5")
COORD_CENTRAL = [-20.2447, -70.1415] # Ubicación: Falabella Iquique

# ==========================================
# 2. ARQUITECTURA DE BASE DE DATOS (SQLite)
# ==========================================
def init_db():
    conn = sqlite3.connect('optiaflux_full.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id TEXT PRIMARY KEY, cliente TEXT, direccion TEXT, lat REAL, lon REAL, estado TEXT, fecha_ingreso TEXT)''')
    conn.commit()
    return conn

conn_db = init_db()

def guardar_pedido_db(id_ped, cliente, direccion, lat, lon):
    c = conn_db.cursor()
    fecha = datetime.now(pytz.timezone('America/Santiago')).strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?)", (id_ped, cliente, direccion, lat, lon, "Pendiente", fecha))
        conn_db.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def obtener_pedidos_db(estado_filtro=None):
    c = conn_db.cursor()
    if estado_filtro:
        c.execute("SELECT * FROM pedidos WHERE estado = ?", (estado_filtro,))
    else:
        c.execute("SELECT * FROM pedidos")
    filas = c.fetchall()
    return [{"id": f[0], "cliente": f[1], "direccion": f[2], "coordenadas": [f[3], f[4]], "estado": f[5], "fecha": f[6]} for f in filas]

def actualizar_estado_db(id_ped, nuevo_estado):
    c = conn_db.cursor()
    c.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (nuevo_estado, id_ped))
    conn_db.commit()

def borrar_pedido_db(id_ped):
    c = conn_db.cursor()
    c.execute("DELETE FROM pedidos WHERE id = ?", (id_ped,))
    conn_db.commit()

def purgar_db():
    c = conn_db.cursor()
    c.execute("DELETE FROM pedidos")
    conn_db.commit()

# ==========================================
# 3. MOTORES LÓGICOS Y OSRM (RUTEO REAL)
# ==========================================
def obtener_coordenadas(direccion):
    try:
        ubicacion = geolocalizador.geocode(f"{direccion}, Provincia de Iquique, Región de Tarapacá, Chile")
        if ubicacion: return [ubicacion.latitude, ubicacion.longitude]
        return None
    except: return None

def calcular_distancia_haversine(coord1, coord2):
    R = 6371.0 
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def obtener_matriz_tiempos_reales(nodos):
    coords_str = ";".join([f"{n['coordenadas'][1]},{n['coordenadas'][0]}" for n in nodos])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}?annotations=duration"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get('code') == 'Ok':
            return res['durations']
    except: return None

def resolver_vrp_multivehiculo(coordenadas_tienda, lista_pedidos, num_vehiculos):
    nodos = [{"id": "CENTRAL", "coordenadas": coordenadas_tienda, "cliente": "Central", "direccion": "Matriz Operativa"}] + lista_pedidos
    matriz_osrm = obtener_matriz_tiempos_reales(nodos)
    
    if matriz_osrm:
        matriz = [[int(valor) for valor in fila] for fila in matriz_osrm]
    else:
        matriz = [[int(calcular_distancia_haversine(nodos[i]['coordenadas'], nodos[j]['coordenadas']) * 1000) for j in range(len(nodos))] for i in range(len(nodos))]

    manager = pywrapcp.RoutingIndexManager(len(matriz), num_vehiculos, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return matriz[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    routing.AddDimension(transit_callback_index, 0, 9000000, True, 'Distance')

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    solution = routing.SolveWithParameters(search_parameters)
    rutas_vehiculos = {}
    if solution:
        for vehicle_id in range(num_vehiculos):
            index = routing.Start(vehicle_id)
            ruta_actual = []
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                ruta_actual.append(nodos[node_index])
                index = solution.Value(routing.NextVar(index))
            ruta_actual.append(nodos[manager.IndexToNode(index)]) 
            if len(ruta_actual) > 2: 
                rutas_vehiculos[f"Vehículo {vehicle_id + 1}"] = ruta_actual
    return rutas_vehiculos

# ==========================================
# 4. DETERMINACIÓN DE TIEMPOS REALES
# ==========================================
def obtener_factor_trafico_real():
    zona_horaria = pytz.timezone('America/Santiago')
    hora_actual = datetime.now(zona_horaria)
    tiempo_decimal = hora_actual.hour + (hora_actual.minute / 60)

    if 7.5 <= tiempo_decimal <= 9.5:  return 1.4, "Alto (Punta Mañana)", hora_actual.strftime('%H:%M')
    elif 13.0 <= tiempo_decimal <= 14.5: return 1.2, "Moderado (Almuerzo)", hora_actual.strftime('%H:%M')
    elif 18.0 <= tiempo_decimal <= 20.5: return 1.5, "Crítico (Punta Tarde)", hora_actual.strftime('%H:%M')
    elif 22.0 <= tiempo_decimal or tiempo_decimal <= 6.0: return 0.9, "Fluido (Nocturno)", hora_actual.strftime('%H:%M')
    else: return 1.0, "Normal (Valle)", hora_actual.strftime('%H:%M')

def motor_ia_predictivo_avanzado(tiempo_base_minutos, clima_override):
    factor_trafico, estado_trafico, hora_leida = obtener_factor_trafico_real()
    factor_clima = 1.15 if clima_override == "Lluvia/Niebla" else 1.0
    minutos_finales = tiempo_base_minutos * factor_trafico * factor_clima
    return round(minutos_finales), estado_trafico, hora_leida

def trazar_geometria_y_cronograma(ruta_ordenada, factor_trafico, factor_clima):
    """Genera el trazado de calles y el ETA 'Solo Ida' acumulado."""
    geometria = []
    cronograma = []
    tiempo_acumulado = 0.0
    distancia_total = 0.0
    
    for i in range(len(ruta_ordenada)-1):
        c1 = ruta_ordenada[i]['coordenadas']
        c2 = ruta_ordenada[i+1]['coordenadas']
        url = f"http://router.project-osrm.org/route/v1/driving/{c1[1]},{c1[0]};{c2[1]},{c2[0]}?overview=full&geometries=geojson"
        try:
            res = requests.get(url, timeout=5).json()
            if res['code'] == 'Ok':
                segmento = res['routes'][0]['geometry']['coordinates']
                geometria.extend([[lat, lon] for lon, lat in segmento])
                
                # Cálculo de tiempo de este tramo
                segundos_tramo = res['routes'][0]['duration']
                minutos_tramo = (segundos_tramo / 60.0) * factor_trafico * factor_clima
                tiempo_acumulado += minutos_tramo
                distancia_total += res['routes'][0]['distance'] / 1000.0
                
                # Guardar llegada al cliente (No retorno a central)
                if i < len(ruta_ordenada) - 2:
                    cronograma.append({
                        "cliente": ruta_ordenada[i+1]['cliente'],
                        "llegada_min": round(tiempo_acumulado)
                    })
        except:
            geometria.extend([c1, c2])
    return geometria, distancia_total, cronograma

# ==========================================
# 5. MEMORIA DE SESIÓN
# ==========================================
if 'rutas_calculadas' not in st.session_state: st.session_state['rutas_calculadas'] = None
if 'datos_trazado' not in st.session_state: st.session_state['datos_trazado'] = {}

def limpiar_memoria_rutas():
    st.session_state['rutas_calculadas'] = None
    st.session_state['datos_trazado'] = {}

# ==========================================
# 6. ESTRUCTURA FRONTEND (ERP COMPLETO)
# ==========================================
st.sidebar.title("Optiaflux ERP")
st.sidebar.caption("LOGÍSTICA DE ALTA PRECISIÓN")
st.sidebar.divider()

modulo = st.sidebar.radio("Módulos del Sistema:", [
    "1️⃣ Control de Manifiestos", 
    "2️⃣ Ruteo y Optimización", 
    "3️⃣ Portal Conductor (Terreno)", 
    "4️⃣ Inteligencia de Negocios (BI)"
])

st.sidebar.divider()
st.sidebar.success("🟢 Motores Satelitales Conectados")
ia_clima = st.sidebar.selectbox("Condición Climática Local:", ["Despejado", "Lluvia/Niebla"])
factor_clima_val = 1.15 if ia_clima == "Lluvia/Niebla" else 1.0

# --- MÓDULO 1: MANIFIESTOS ---
if modulo == "1️⃣ Control de Manifiestos":
    st.title("Gestión de Manifiestos SQL")
    st.write("Administración de carga y persistencia de datos relacionales.")
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Ingreso Manual")
        with st.form("form_manual"):
            cli = st.text_input("Razón Social / Cliente")
            dir_ = st.text_input("Dirección (Ej: Los Cóndores 123)")
            if st.form_submit_button("Geocodificar y Guardar"):
                with st.spinner("Procesando..."):
                    coor = obtener_coordenadas(dir_)
                    if coor:
                        id_p = f"PED-{random.randint(10000, 99999)}"
                        if guardar_pedido_db(id_p, cli, dir_, coor[0], coor[1]):
                            limpiar_memoria_rutas(); st.success("Registrado."); st.rerun()
                    else: st.error("Error: Dirección no encontrada.")

    with col2:
        st.subheader("Integración Masiva (CSV)")
        st.write("El archivo debe contener las columnas 'Cliente' y 'Direccion'.")
        archivo = st.file_uploader("Subir Manifiesto", type=["csv"])
        if archivo and st.button("🚀 Inyectar Lote a la Base de Datos"):
            df = pd.read_csv(archivo)
            df.columns = df.columns.str.strip().str.lower()
            bar = st.progress(0)
            exito = 0
            for idx, row in df.iterrows():
                c_coor = obtener_coordenadas(str(row['direccion']))
                if c_coor:
                    id_p = f"PED-{random.randint(10000, 99999)}"
                    guardar_pedido_db(id_p, str(row['cliente']), str(row['direccion']), c_coor[0], c_coor[1])
                    exito += 1
                bar.progress((idx + 1) / len(df))
            limpiar_memoria_rutas(); st.success(f"Operación exitosa: {exito} pedidos guardados permanentemente."); st.rerun()

    st.divider()
    st.subheader("Base de Datos Activa")
    pedidos_db = obtener_pedidos_db()
    if pedidos_db:
        for p in pedidos_db:
            c_info, c_btn = st.columns([8, 2])
            c_info.write(f"📦 **{p['id']}** | {p['cliente']} | {p['direccion']} | **{p['estado']}**")
            if c_btn.button("❌ Eliminar", key=p['id']):
                borrar_pedido_db(p['id']); limpiar_memoria_rutas(); st.rerun()
        
        st.write("")
        if st.button("🗑️ Purgar Sistema Completo"):
            purgar_db(); limpiar_memoria_rutas(); st.rerun()
    else: st.info("No hay pedidos registrados.")

# --- MÓDULO 2: RUTEO (TIEMPOS REALES SOLO IDA) ---
elif modulo == "2️⃣ Ruteo y Optimización":
    st.title("Optimización de Flota")
    st.write("Análisis de tránsito en tiempo real y ruteo por calles.")
    st.divider()
    pedidos_p = obtener_pedidos_db(estado_filtro="Pendiente")
    
    col_c, col_m = st.columns([1, 2])
    mapa = folium.Map(location=COORD_CENTRAL, zoom_start=13)
    folium.Marker(COORD_CENTRAL, icon=folium.Icon(color="black", icon="home")).add_to(mapa)
    
    with col_c:
        n_veh = st.slider("Unidades Disponibles", 1, 10, 2)
        if st.button("🚀 Iniciar Optimización Satelital", type="primary", use_container_width=True):
            if not pedidos_p: st.warning("No hay carga pendiente.")
            else:
                with st.spinner("Sincronizando con motores OSRM..."):
                    st.session_state['rutas_calculadas'] = resolver_vrp_multivehiculo(COORD_CENTRAL, pedidos_p, n_veh)
                    st.session_state['datos_trazado'] = {}
                    f_trafico, desc_t, hora_t = obtener_factor_trafico_real()
                    
                    for v, ruta in st.session_state['rutas_calculadas'].items():
                        geom, dist, crono = trazar_geometria_y_cronograma(ruta, f_trafico, factor_clima_val)
                        st.session_state['datos_trazado'][v] = {"geom": geom, "dist": dist, "crono": crono, "info_t": f"{desc_t} ({hora_t})"}
        
        if st.session_state['rutas_calculadas']:
            colores = ['#1E3A8A', '#10B981', '#F59E0B', '#DC2626', '#8B5CF6']
            for i, (v, ruta) in enumerate(st.session_state['rutas_calculadas'].items()):
                dv = st.session_state['datos_trazado'].get(v)
                if dv:
                    st.markdown(f"### 🚚 {v}")
                    st.caption(f"📡 {dv['info_t']} | Recorrido: {round(dv['dist'],1)} km")
                    for c in dv['crono']:
                        st.write(f"📍 {c['cliente']}: **+ {c['llegada_min']} min**")
                    folium.PolyLine(dv['geom'], color=colores[i % len(colores)], weight=5, opacity=0.8).add_to(mapa)

    with col_m:
        for p in pedidos_p:
            folium.Marker(p['coordenadas'], popup=p['id'], icon=folium.Icon(color="gray")).add_to(mapa)
        st_folium(mapa, width=800, height=600)

# --- MÓDULO 3: PORTAL CONDUCTOR (CÁMARA DUAL) ---
elif modulo == "3️⃣ Portal Conductor (Terreno)":
    st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>📱 Portal Conductor Terreno</h2>", unsafe_allow_html=True)
    st.divider()
    pedidos = obtener_pedidos_db(estado_filtro="Pendiente")
    if not pedidos: st.success("🎉 Todas las entregas han sido completadas.")
    else:
        st.write("Seleccione el pedido para gestionar la entrega:")
        for p in pedidos:
            with st.expander(f"ORDEN: {p['id']} | {p['cliente']}"):
                st.write(f"📍 Dirección: {p['direccion']}")
                st.info("💡 Tip: Para cambiar de cámara, utiliza el icono de rotación en la interfaz de cámara de tu dispositivo.")
                foto = st.camera_input("Prueba de Entrega (PoD)", key=f"cam_{p['id']}")
                if foto:
                    if st.button("Confirmar Entrega", key=f"btn_{p['id']}", type="primary"):
                        actualizar_estado_db(p['id'], "Entregado")
                        limpiar_memoria_rutas(); st.rerun()

# --- MÓDULO 4: BI ANALÍTICA ---
elif modulo == "4️⃣ Inteligencia de Negocios (BI)":
    st.title("Business Intelligence")
    df = pd.DataFrame(obtener_pedidos_db())
    if not df.empty:
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.pie(df, names='estado', title="Cumplimiento SLA", hole=0.4, color='estado', color_discrete_map={'Entregado':'#10B981', 'Pendiente':'#F59E0B'}))
        with c2:
            st.subheader("Mapa de Calor de Demanda")
            m_h = folium.Map(location=COORD_CENTRAL, zoom_start=12)
            HeatMap(df[['lat', 'lon']].values.tolist()).add_to(m_h)
            st_folium(m_h, width=500, height=400)
