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
    div[data-testid="stMetricValue"] { font-size: 2rem; color: #1E3A8A; }
    </style>
""", unsafe_allow_html=True)

geolocalizador = Nominatim(user_agent="optiaflux_erp_app")
COORD_CENTRAL = [-20.2447, -70.1415] # Matriz Operativa: Iquique

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
        c.execute("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?)", 
                  (id_ped, cliente, direccion, lat, lon, "Pendiente", fecha))
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
# 3. MOTORES LÓGICOS Y MULTI-FLOTA (OR-TOOLS)
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

def resolver_vrp_multivehiculo(coordenadas_tienda, lista_pedidos, num_vehiculos):
    """Calcula las rutas óptimas para una flota de múltiples vehículos."""
    nodos = [{"id": "CENTRAL", "coordenadas": coordenadas_tienda, "cliente": "Central", "direccion": "Matriz Operativa"}] + lista_pedidos
    
    matriz_distancias = []
    for i in range(len(nodos)):
        fila = []
        for j in range(len(nodos)):
            dist = calcular_distancia_haversine(nodos[i]['coordenadas'], nodos[j]['coordenadas'])
            fila.append(int(dist * 1000)) # Ajuste a metros para OR-Tools
        matriz_distancias.append(fila)

    manager = pywrapcp.RoutingIndexManager(len(matriz_distancias), num_vehiculos, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return matriz_distancias[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    dimension_name = 'Distance'
    routing.AddDimension(
        transit_callback_index,
        0,       # Sin holgura
        300000,  # Límite máximo de recorrido por vehículo
        True,    # Iniciar acumulado en cero
        dimension_name)
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

# ==========================================
# 4. MEMORIA DE SESIÓN TEMPORAL
# ==========================================
if 'rutas_calculadas' not in st.session_state: 
    st.session_state['rutas_calculadas'] = None

# ==========================================
# 5. ESTRUCTURA FRONTEND (ERP LOGÍSTICO)
# ==========================================
st.sidebar.title("Optiaflux ERP")
st.sidebar.caption("SISTEMA CENTRAL DE OPERACIONES")
st.sidebar.divider()

modulo = st.sidebar.radio("Módulos del Sistema:", [
    "1️⃣ Control de Manifiestos", 
    "2️⃣ Ruteo Multi-Flota", 
    "3️⃣ Portal Conductor (Terreno)", 
    "4️⃣ Inteligencia de Negocios (BI)"
])

st.sidebar.divider()
st.sidebar.info("Estado de Conexión: Estable 🟢")

# ------------------------------------------
# MÓDULO 1: CONTROL DE MANIFIESTOS (ADMIN)
# ------------------------------------------
if modulo == "1️⃣ Control de Manifiestos":
    st.title("Control Integrado de Manifiestos")
    st.write("Gestión centralizada de requerimientos logísticos e integración de datos.")
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Ingreso Manual")
        with st.form("form_pedido"):
            cliente = st.text_input("Razón Social / Cliente")
            direccion = st.text_input("Dirección Exacta (Ej: Los Cóndores 123, Alto Hospicio)")
            if st.form_submit_button("Registrar Operación"):
                with st.spinner("Geocodificando y asignando ID..."):
                    coords = obtener_coordenadas(direccion)
                    if coords:
                        id_ped = f"PED-{random.randint(10000, 99999)}"
                        if guardar_pedido_db(id_ped, cliente, direccion, coords[0], coords[1]):
                            st.session_state['rutas_calculadas'] = None
                            st.success(f"Transacción exitosa. ID asignado: {id_ped}")
                            st.rerun()
                    else:
                        st.error("Error geográfico: Verifique la dirección ingresada.")

    with col2:
        st.subheader("Integración Masiva (CSV)")
        st.write("Estructura requerida: Columnas 'Cliente' y 'Direccion'.")
        archivo = st.file_uploader("", type=["csv"])
        if archivo and st.button("Procesar Lote de Datos", type="primary"):
            df = pd.read_csv(archivo)
            bar = st.progress(0)
            exito = 0
            for idx, row in df.iterrows():
                dir_texto = str(row.get('Direccion', ''))
                if dir_texto.strip() and dir_texto != 'nan':
                    coords = obtener_coordenadas(dir_texto)
                    if coords:
                        id_ped = f"PED-{random.randint(10000, 99999)}"
                        guardar_pedido_db(id_ped, str(row.get('Cliente','')), dir_texto, coords[0], coords[1])
                        exito += 1
                bar.progress((idx + 1) / len(df))
            st.session_state['rutas_calculadas'] = None
            st.success(f"Lote procesado. {exito} registros insertados exitosamente.")
            st.rerun()

    st.divider()
    st.subheader("Tabla Maestra de Operaciones")
    pedidos_todos = obtener_pedidos_db()
    if pedidos_todos:
        df_mostrar = pd.DataFrame(pedidos_todos)
        st.dataframe(df_mostrar[['id', 'cliente', 'direccion', 'estado', 'fecha']], use_container_width=True)
        
        col_borrar, col_purgar = st.columns([1, 4])
        with col_borrar:
            id_a_borrar = st.text_input("ID a eliminar (Ej: PED-12345)")
            if st.button("Eliminar Registro"):
                borrar_pedido_db(id_a_borrar)
                st.session_state['rutas_calculadas'] = None
                st.rerun()
        with col_purgar:
            if st.button("Depurar Base de Datos Completa (RESET)", type="secondary"):
                purgar_db()
                st.session_state['rutas_calculadas'] = None
                st.rerun()
    else:
        st.info("La base de datos operativa se encuentra vacía.")

# ------------------------------------------
# MÓDULO 2: RUTEO MULTI-FLOTA (ADMIN)
# ------------------------------------------
elif modulo == "2️⃣ Ruteo Multi-Flota":
    st.title("Enrutamiento y Asignación de Flota")
    st.write("Motor de optimización OR-Tools para múltiples vehículos.")
    st.divider()
    
    pedidos_pendientes = obtener_pedidos_db(estado_filtro="Pendiente")
    
    col_param, col_mapa = st.columns([1, 2])
    
    with col_param:
        st.subheader("Parámetros Operativos")
        flota_disponible = st.number_input("Número de vehículos disponibles:", min_value=1, max_value=20, value=2)
        
        if len(pedidos_pendientes) == 0:
            st.warning("No hay manifiestos en estado 'Pendiente' para optimizar.")
        else:
            st.info(f"Carga de trabajo: {len(pedidos_pendientes)} entregas pendientes.")
            if st.button("Generar Solución Logística Global", type="primary", use_container_width=True):
                with st.spinner("Modelando CVRP en servidores matriciales..."):
                    rutas = resolver_vrp_multivehiculo(COORD_CENTRAL, pedidos_pendientes, flota_disponible)
                    st.session_state['rutas_calculadas'] = rutas
            
            if st.session_state['rutas_calculadas']:
                st.success("Distribución óptima calculada.")
                colores = ['purple', 'blue', 'green', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'black']
                
                datos_csv = []
                for i, (vehiculo, ruta) in enumerate(st.session_state['rutas_calculadas'].items()):
                    st.markdown(f"**🚚 {vehiculo}** (Trazo: {colores[i % len(colores)].upper()})")
                    for paso in ruta[1:-1]: 
                        st.write(f"- {paso['id']} ({paso['cliente']})")
                        datos_csv.append({"Vehículo": vehiculo, "ID Pedido": paso['id'], "Cliente": paso['cliente'], "Dirección": paso['direccion']})
                
                df_manifiesto = pd.DataFrame(datos_csv)
                st.write("")
                st.download_button("Exportar Manifiestos de Flota (CSV)", data=df_manifiesto.to_csv(index=False).encode('utf-8'), file_name="manifiestos_flota_optiaflux.csv", mime="text/csv", use_container_width=True)

    with col_mapa:
        mapa = folium.Map(location=COORD_CENTRAL, zoom_start=13)
        folium.Marker(COORD_CENTRAL, popup="Matriz Central", icon=folium.Icon(color="black", icon="briefcase")).add_to(mapa)
        
        for p in pedidos_pendientes:
            folium.Marker(p['coordenadas'], popup=f"{p['id']} - {p['cliente']}", icon=folium.Icon(color="lightgray", icon="info-sign")).add_to(mapa)
            
        if st.session_state['rutas_calculadas']:
            colores = ['purple', 'blue', 'green', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'black']
            for i, (vehiculo, ruta) in enumerate(st.session_state['rutas_calculadas'].items()):
                puntos = [nodo['coordenadas'] for nodo in ruta]
                folium.PolyLine(puntos, color=colores[i % len(colores)], weight=6, opacity=0.8).add_to(mapa)
                
        st_folium(mapa, width=800, height=600)

# ------------------------------------------
# MÓDULO 3: PORTAL CONDUCTOR (TERRENO)
# ------------------------------------------
elif modulo == "3️⃣ Portal Conductor (Terreno)":
    st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>📱 Portal Operador Terreno</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Aplicación móvil de gestión de entregas (PoD)</p>", unsafe_allow_html=True)
    st.divider()
    
    pedidos_pendientes = obtener_pedidos_db(estado_filtro="Pendiente")
    if not pedidos_pendientes:
        st.success("🎉 Ruta completada. No hay manifiestos pendientes asignados a su unidad.")
    else:
        st.write("**Manifiestos Activos en su Zona:**")
        for p in pedidos_pendientes:
            with st.expander(f"📍 {p['direccion']} | {p['cliente']}"):
                st.write(f"**ID:** {p['id']}")
                st.write(f"**Hora de Ingreso:** {p['fecha']}")
                
                st.write("---")
                st.write("**Prueba de Entrega (PoD)**")
                foto = st.camera_input("Capturar evidencia fotográfica", key=f"cam_{p['id']}")
                if foto:
                    if st.button("✅ Confirmar Entrega y Cerrar Manifiesto", key=f"btn_{p['id']}", type="primary", use_container_width=True):
                        actualizar_estado_db(p['id'], "Entregado")
                        st.success("Información transmitida a la Central.")
                        st.rerun()

# ------------------------------------------
# MÓDULO 4: INTELIGENCIA DE NEGOCIOS (BI)
# ------------------------------------------
elif modulo == "4️⃣ Inteligencia de Negocios (BI)":
    st.title("📊 Analítica de Datos y KPIs Gerenciales")
    st.write("Monitorización del rendimiento operativo y proyecciones espaciales.")
    st.divider()
    
    pedidos_todos = obtener_pedidos_db()
    if not pedidos_todos:
        st.info("El sistema requiere data histórica para inicializar los modelos analíticos.")
    else:
        df = pd.DataFrame(pedidos_todos)
        total = len(df)
        entregados = len(df[df['estado'] == 'Entregado'])
        pendientes = total - entregados
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Volumen Total Operado", total, delta="Total Histórico")
        tasa_sla = round((entregados/total)*100, 1) if total>0 else 0
        col2.metric("Nivel de Servicio (SLA)", f"{tasa_sla}%", delta=f"{entregados} completados", delta_color="normal")
        col3.metric("Manifiestos en Tránsito", pendientes, delta="Operativa actual", delta_color="inverse")
        
        st.divider()
        col_graf, col_calor = st.columns(2)
        
        with col_graf:
            st.subheader("Estatus Operativo Global")
            fig = px.pie(df, names='estado', hole=0.4, 
                         color='estado', color_discrete_map={'Entregado':'#10B981', 'Pendiente':'#F59E0B'})
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
            
        with col_calor:
            st.subheader("Densidad Espacial de la Demanda")
            st.caption("Mapa de Calor para evaluación de zonas estratégicas y Dark Stores.")
            
            mapa_calor = folium.Map(location=COORD_CENTRAL, zoom_start=13)
            coordenadas_calor = [[p['coordenadas'][0], p['coordenadas'][1]] for p in pedidos_todos]
            HeatMap(coordenadas_calor, radius=18, blur=12, gradient={0.4: 'blue', 0.65: 'lime', 1: 'red'}).add_to(mapa_calor)
            st_folium(mapa_calor, width=500, height=350)
