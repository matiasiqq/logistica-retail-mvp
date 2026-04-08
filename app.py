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
    </style>
""", unsafe_allow_html=True)

geolocalizador = Nominatim(user_agent="optiaflux_erp_app")
COORD_CENTRAL = [-20.2447, -70.1415] 

# ==========================================
# 2. ARQUITECTURA DE BASE DE DATOS (SQLite)
# ==========================================
def init_db():
    conn = sqlite3.connect('optiaflux.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id TEXT PRIMARY KEY, cliente TEXT, direccion TEXT, lat REAL, lon REAL, estado TEXT, fecha_ingreso TEXT)''')
    conn.commit()
    return conn

conn = init_db()

def guardar_pedido_db(id_ped, cliente, direccion, lat, lon):
    c = conn.cursor()
    fecha = datetime.now(pytz.timezone('America/Santiago')).strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?)", (id_ped, cliente, direccion, lat, lon, "Pendiente", fecha))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def obtener_pedidos_db(estado_filtro=None):
    c = conn.cursor()
    if estado_filtro:
        c.execute("SELECT * FROM pedidos WHERE estado = ?", (estado_filtro,))
    else:
        c.execute("SELECT * FROM pedidos")
    filas = c.fetchall()
    return [{"id": f[0], "cliente": f[1], "direccion": f[2], "coordenadas": [f[3], f[4]], "estado": f[5], "fecha": f[6]} for f in filas]

def actualizar_estado_db(id_ped, nuevo_estado):
    c = conn.cursor()
    c.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (nuevo_estado, id_ped))
    conn.commit()

def borrar_pedido_db(id_ped):
    c = conn.cursor()
    c.execute("DELETE FROM pedidos WHERE id = ?", (id_ped,))
    conn.commit()

def purgar_db():
    c = conn.cursor()
    c.execute("DELETE FROM pedidos")
    conn.commit()

# ==========================================
# 3. MOTORES LÓGICOS Y OSRM (RUTEO REAL POR CALLES)
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
    except:
        return None
    return None

def resolver_vrp_multivehiculo(coordenadas_tienda, lista_pedidos, num_vehiculos):
    nodos = [{"id": "CENTRAL", "coordenadas": coordenadas_tienda, "cliente": "Central", "direccion": "Matriz Operativa"}] + lista_pedidos
    matriz_tiempos = obtener_matriz_tiempos_reales(nodos)
    
    # CORRECCIÓN DE BUG: Transformar la matriz de OSRM (decimales) a Enteros para OR-Tools
    if matriz_tiempos:
        matriz_tiempos = [[int(valor) for valor in fila] for fila in matriz_tiempos]
    else: 
        matriz_tiempos = []
        for i in range(len(nodos)):
            fila = []
            for j in range(len(nodos)):
                fila.append(int(calcular_distancia_haversine(nodos[i]['coordenadas'], nodos[j]['coordenadas']) * 100))
            matriz_tiempos.append(fila)

    manager = pywrapcp.RoutingIndexManager(len(matriz_tiempos), num_vehiculos, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return matriz_tiempos[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    dimension_name = 'Distance'
    # CORRECCIÓN DE BUG: Aumentar el límite de distancia drásticamente a 9,000,000 para evitar colapsos
    routing.AddDimension(transit_callback_index, 0, 9000000, True, dimension_name)
    distance_dimension = routing.GetDimensionOrDie(dimension_name)
    distance_dimension.SetGlobalSpanCostCoefficient(100)

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

def trazar_ruta_calles(ruta_ordenada):
    coords_str = ";".join([f"{p['coordenadas'][1]},{p['coordenadas'][0]}" for p in ruta_ordenada])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get('code') == 'Ok':
            coords_calle = res['routes'][0]['geometry']['coordinates']
            geometria_completa = [[lat, lon] for lon, lat in coords_calle]
            dist_km = res['routes'][0]['distance'] / 1000.0
            tiempo_min = res['routes'][0]['duration'] / 60.0
            return geometria_completa, dist_km, tiempo_min
    except:
        pass
    
    geometria_completa = [p['coordenadas'] for p in ruta_ordenada]
    dist_km = sum(calcular_distancia_haversine(ruta_ordenada[i]['coordenadas'], ruta_ordenada[i+1]['coordenadas']) for i in range(len(ruta_ordenada)-1))
    return geometria_completa, dist_km, dist_km * 2 

# ==========================================
# 4. ESTADÍSTICA PREDICTIVA (PERCENTILES P50 / P90)
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

def motor_estadistico_ventanas(tiempo_base_minutos, clima_override):
    factor_trafico, estado_trafico, hora_leida = obtener_factor_trafico_real()
    factor_clima = 1.15 if clima_override == "Lluvia/Niebla" else 1.0
    
    minutos_esperados = tiempo_base_minutos * factor_trafico * factor_clima
    eta_p50 = round(minutos_esperados)
    varianza = 0.35 if "Punta" in estado_trafico else 0.15
    eta_p90 = round(minutos_esperados * (1 + varianza))
    return eta_p50, eta_p90, estado_trafico, hora_leida

# ==========================================
# 5. MEMORIA DE SESIÓN ROBUSTA
# ==========================================
if 'rutas_calculadas' not in st.session_state: st.session_state['rutas_calculadas'] = None
if 'datos_trazado' not in st.session_state: st.session_state['datos_trazado'] = {}

def limpiar_memoria_rutas():
    st.session_state['rutas_calculadas'] = None
    st.session_state['datos_trazado'] = {}

# ==========================================
# 6. ESTRUCTURA FRONTEND (ERP LOGÍSTICO)
# ==========================================
st.sidebar.title("Optiaflux ERP")
st.sidebar.caption("SISTEMA CENTRAL DE OPERACIONES")
st.sidebar.divider()

modulo = st.sidebar.radio("Módulos del Sistema:", [
    "1️⃣ Control de Manifiestos", 
    "2️⃣ Ruteo y Optimización", 
    "3️⃣ Portal Conductor (Terreno)", 
    "4️⃣ Inteligencia de Negocios (BI)"
])

st.sidebar.divider()
st.sidebar.success("🟢 OR-Tools y OSRM Conectados")
ia_clima = st.sidebar.selectbox("Condición Climática Local:", ["Despejado", "Lluvia/Niebla"])

# ------------------------------------------
# MÓDULO 1: CONTROL DE MANIFIESTOS (ADMIN)
# ------------------------------------------
if modulo == "1️⃣ Control de Manifiestos":
    st.title("Control Integrado de Manifiestos")
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Ingreso Manual")
        with st.form("form_pedido"):
            cliente = st.text_input("Razón Social / Cliente")
            direccion = st.text_input("Dirección Exacta")
            if st.form_submit_button("Registrar Operación"):
                with st.spinner("Geocodificando..."):
                    coords = obtener_coordenadas(direccion)
                    if coords:
                        id_ped = f"PED-{random.randint(10000, 99999)}"
                        if guardar_pedido_db(id_ped, cliente, direccion, coords[0], coords[1]):
                            limpiar_memoria_rutas() 
                            st.success("Transacción exitosa.")
                            st.rerun()
                    else:
                        st.error("Error geográfico.")

    with col2:
        st.subheader("Integración Masiva (CSV robusto)")
        archivo = st.file_uploader("Formatos aceptados: .csv", type=["csv"])
        if archivo and st.button("Procesar Lote de Datos", type="primary"):
            df = pd.read_csv(archivo)
            df.columns = df.columns.str.strip().str.lower()
            
            if 'cliente' in df.columns and 'direccion' in df.columns:
                bar = st.progress(0)
                exito = 0
                for idx, row in df.iterrows():
                    dir_texto = str(row['direccion'])
                    if dir_texto.strip() and dir_texto != 'nan':
                        coords = obtener_coordenadas(dir_texto)
                        if coords:
                            id_ped = f"PED-{random.randint(10000, 99999)}"
                            guardar_pedido_db(id_ped, str(row['cliente']), dir_texto, coords[0], coords[1])
                            exito += 1
                    bar.progress((idx + 1) / len(df))
                limpiar_memoria_rutas()
                st.success(f"Lote procesado. {exito} registros insertados.")
                st.rerun()
            else:
                st.error("El archivo CSV debe contener exactamente las columnas 'cliente' y 'direccion'.")

    st.divider()
    st.subheader("Base de Datos Activa (Interactiva)")
    pedidos_todos = obtener_pedidos_db()
    if pedidos_todos:
        for i, p in enumerate(pedidos_todos):
            col_info, col_btn = st.columns([8, 2])
            col_info.markdown(f"📦 **{p['id']}** | 👤 {p['cliente']} | 📍 {p['direccion']} | 🚦 {p['estado']}")
            if col_btn.button("❌ Eliminar", key=f"del_{p['id']}"):
                borrar_pedido_db(p['id'])
                limpiar_memoria_rutas()
                st.rerun()
                
        st.write("")
        if st.button("Depurar Base de Datos Completa (RESET)", type="secondary"):
            purgar_db()
            limpiar_memoria_rutas()
            st.rerun()
    else:
        st.info("La base de datos operativa se encuentra vacía.")

# ------------------------------------------
# MÓDULO 2: RUTEO MULTI-FLOTA CON CALLES REALES
# ------------------------------------------
elif modulo == "2️⃣ Ruteo y Optimización":
    st.title("Panel de Optimización OSRM y OR-Tools")
    st.divider()
    pedidos_pendientes = obtener_pedidos_db(estado_filtro="Pendiente")
    
    col_param, col_mapa = st.columns([1, 2])
    mapa = folium.Map(location=COORD_CENTRAL, zoom_start=14)
    folium.Marker(COORD_CENTRAL, popup="Matriz Central", icon=folium.Icon(color="black", icon="briefcase")).add_to(mapa)
    
    with col_param:
        flota_disponible = st.number_input("Vehículos disponibles:", min_value=1, max_value=10, value=2)
        if len(pedidos_pendientes) == 0:
            st.warning("No hay manifiestos pendientes.")
        else:
            if st.button("Generar Ruteo Inteligente", type="primary", use_container_width=True):
                with st.spinner("Conectando con satélites OSRM y motores Google..."):
                    rutas = resolver_vrp_multivehiculo(COORD_CENTRAL, pedidos_pendientes, flota_disponible)
                    st.session_state['rutas_calculadas'] = rutas
                    st.session_state['datos_trazado'] = {}
                    
                    for vehiculo, ruta in rutas.items():
                        geom, dist, tiempo = trazar_ruta_calles(ruta)
                        st.session_state['datos_trazado'][vehiculo] = {"geom": geom, "dist": dist, "tiempo": tiempo}
            
            if st.session_state['rutas_calculadas']:
                colores = ['#1E3A8A', '#10B981', '#F59E0B', '#DC2626', '#8B5CF6', '#14B8A6']
                
                for i, (vehiculo, ruta) in enumerate(st.session_state['rutas_calculadas'].items()):
                    color_v = colores[i % len(colores)]
                    
                    if vehiculo in st.session_state.get('datos_trazado', {}):
                        datos_v = st.session_state['datos_trazado'][vehiculo]
                        
                        eta_p50, eta_p90, estado_trafico, hora_leida = motor_estadistico_ventanas(datos_v["tiempo"], ia_clima)
                        
                        st.markdown(f"### 🚚 {vehiculo}")
                        st.write(f"**Distancia:** {round(datos_v['dist'], 1)} km | **Tráfico:** {estado_trafico}")
                        st.metric(label=f"Ventana de Entrega (P50-P90)", value=f"{eta_p50} - {eta_p90} min")
                        
                        folium.PolyLine(datos_v["geom"], color=color_v, weight=6, opacity=0.85).add_to(mapa)
                    else:
                        st.warning(f"⚠️ Datos en proceso para {vehiculo}.")

    with col_mapa:
        for p in pedidos_pendientes:
            folium.Marker(p['coordenadas'], popup=f"{p['id']}", icon=folium.Icon(color="lightgray", icon="info-sign")).add_to(mapa)
        st_folium(mapa, width=800, height=600)

# ------------------------------------------
# MÓDULO 3: PORTAL CONDUCTOR (TERRENO)
# ------------------------------------------
elif modulo == "3️⃣ Portal Conductor (Terreno)":
    st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>📱 Portal Operador Terreno</h2>", unsafe_allow_html=True)
    st.divider()
    
    pedidos_pendientes = obtener_pedidos_db(estado_filtro="Pendiente")
    if not pedidos_pendientes:
        st.success("🎉 Ruta completada.")
    else:
        for p in pedidos_pendientes:
            with st.expander(f"📍 {p['direccion']} | {p['cliente']}"):
                st.write(f"**ID:** {p['id']}")
                foto = st.camera_input("Capturar evidencia fotográfica", key=f"cam_{p['id']}")
                if foto:
                    if st.button("✅ Confirmar Entrega", key=f"btn_{p['id']}", type="primary", use_container_width=True):
                        actualizar_estado_db(p['id'], "Entregado")
                        limpiar_memoria_rutas() 
                        st.success("Información transmitida a la Central.")
                        st.rerun()

# ------------------------------------------
# MÓDULO 4: INTELIGENCIA DE NEGOCIOS (BI)
# ------------------------------------------
elif modulo == "4️⃣ Inteligencia de Negocios (BI)":
    st.title("📊 Analítica de Datos")
    st.divider()
    
    pedidos_todos = obtener_pedidos_db()
    if not pedidos_todos:
        st.info("El sistema requiere data histórica.")
    else:
        df = pd.DataFrame(pedidos_todos)
        total = len(df)
        entregados = len(df[df['estado'] == 'Entregado'])
        pendientes = total - entregados
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Volumen Total Operado", total)
        tasa_sla = round((entregados/total)*100, 1) if total>0 else 0
        col2.metric("Nivel de Servicio (SLA)", f"{tasa_sla}%")
        col3.metric("Manifiestos en Tránsito", pendientes)
        
        st.divider()
        col_graf, col_calor = st.columns(2)
        
        with col_graf:
            st.subheader("Estatus Operativo Global")
            fig = px.pie(df, names='estado', hole=0.4, color='estado', color_discrete_map={'Entregado':'#10B981', 'Pendiente':'#F59E0B'})
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
            
        with col_calor:
            st.subheader("Densidad Espacial de la Demanda")
            mapa_calor = folium.Map(location=COORD_CENTRAL, zoom_start=13)
            coordenadas_calor = [[p['coordenadas'][0], p['coordenadas'][1]] for p in pedidos_todos]
            HeatMap(coordenadas_calor, radius=18, blur=12).add_to(mapa_calor)
            st_folium(mapa_calor, width=500, height=350)
