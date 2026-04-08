import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
import random
import sqlite3
import requests
from geopy.geocoders import Nominatim
from datetime import datetime
import pytz
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# ==========================================
# CONFIG
# ==========================================
st.set_page_config(page_title="Optiaflux PRO", layout="wide")

geolocalizador = Nominatim(user_agent="optiaflux_pro")
COORD_CENTRAL = [-20.2447, -70.1415]

# ==========================================
# DB SQLITE
# ==========================================
def init_db():
    conn = sqlite3.connect('optiaflux.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id TEXT PRIMARY KEY, cliente TEXT, direccion TEXT, lat REAL, lon REAL, estado TEXT, fecha TEXT)''')
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
    except:
        return False

def obtener_pedidos_db():
    c = conn.cursor()
    c.execute("SELECT * FROM pedidos")
    filas = c.fetchall()
    return [{"id": f[0], "cliente": f[1], "direccion": f[2], "coordenadas": [f[3], f[4]], "estado": f[5]} for f in filas]

def borrar_pedido(id_ped):
    conn.cursor().execute("DELETE FROM pedidos WHERE id=?", (id_ped,))
    conn.commit()

# ==========================================
# GEO
# ==========================================
def obtener_coordenadas(direccion):
    try:
        loc = geolocalizador.geocode(f"{direccion}, Chile")
        if loc:
            return [loc.latitude, loc.longitude]
    except:
        return None

# ==========================================
# OSRM MATRIZ TIEMPOS
# ==========================================
def obtener_matriz_tiempos_osrm(nodos):
    coords = ";".join([f"{n['coordenadas'][1]},{n['coordenadas'][0]}" for n in nodos])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords}?annotations=duration"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get('code') == 'Ok':
            return [[int(x) for x in fila] for fila in res['durations']]
    except:
        return None
    return None

# ==========================================
# FALLBACK DISTANCIA
# ==========================================
def haversine(c1, c2):
    R = 6371
    lat1, lon1 = map(math.radians, c1)
    lat2, lon2 = map(math.radians, c2)
    dlat, dlon = lat2-lat1, lon2-lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ==========================================
# VRP CON OSRM
# ==========================================
def resolver_ruta(coordenadas_tienda, pedidos, vehiculos):
    nodos = [{"id":"CENTRAL","coordenadas":coordenadas_tienda}] + pedidos
    matriz = obtener_matriz_tiempos_osrm(nodos)

    if not matriz:
        matriz = [[int(haversine(nodos[i]['coordenadas'], nodos[j]['coordenadas'])*120)
                  for j in range(len(nodos))] for i in range(len(nodos))]

    manager = pywrapcp.RoutingIndexManager(len(matriz), vehiculos, 0)
    routing = pywrapcp.RoutingModel(manager)

    def cb(i, j):
        return matriz[manager.IndexToNode(i)][manager.IndexToNode(j)]

    transit = routing.RegisterTransitCallback(cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    routing.AddDimension(transit, 0, 9000000, True, "Time")

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    sol = routing.SolveWithParameters(params)

    rutas = {}
    if sol:
        for v in range(vehiculos):
            idx = routing.Start(v)
            ruta = []
            while not routing.IsEnd(idx):
                ruta.append(nodos[manager.IndexToNode(idx)])
                idx = sol.Value(routing.NextVar(idx))
            ruta.append(nodos[manager.IndexToNode(idx)])

            if len(ruta) > 2:
                rutas[f"Vehículo {v+1}"] = ruta
    return rutas

# ==========================================
# RUTA CALLES
# ==========================================
def trazar_ruta(ruta):
    coords = ";".join([f"{p['coordenadas'][1]},{p['coordenadas'][0]}" for p in ruta])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
    try:
        res = requests.get(url).json()
        geo = [[lat, lon] for lon, lat in res['routes'][0]['geometry']['coordinates']]
        dist = res['routes'][0]['distance']/1000
        tiempo = res['routes'][0]['duration']/60
        return geo, dist, tiempo
    except:
        return [p['coordenadas'] for p in ruta], 0, 0

# ==========================================
# ETA AVANZADO
# ==========================================
def trafico():
    h = datetime.now(pytz.timezone('America/Santiago')).hour
    if 7<=h<=9: return 1.4
    if 18<=h<=20: return 1.5
    return 1.0

def eta(t_base, clima):
    factor = trafico()
    if clima=="Lluvia": factor*=1.15
    p50 = round(t_base*factor)
    p90 = round(p50*1.3)
    return p50, p90

# ==========================================
# CSV ROBUSTO
# ==========================================
def procesar_csv(file):
    df = pd.read_csv(file)
    df.columns = df.columns.str.lower().str.strip()

    if 'cliente' not in df or 'direccion' not in df:
        return 0

    ok = 0
    barra = st.progress(0)

    for i,row in df.iterrows():
        dir = str(row['direccion'])
        if dir and dir!='nan':
            c = obtener_coordenadas(dir)
            if c:
                guardar_pedido_db(f"PED-{random.randint(10000,99999)}",
                                  row['cliente'], dir, c[0], c[1])
                ok+=1
        barra.progress((i+1)/len(df))
    return ok

# ==========================================
# UI
# ==========================================
st.sidebar.title("Optiaflux PRO")
mod = st.sidebar.radio("Módulos", ["Pedidos","Ruteo"])

# ------------------------------------------
# PEDIDOS
# ------------------------------------------
if mod=="Pedidos":
    st.title("Gestión de Pedidos")

    col1,col2 = st.columns(2)

    with col1:
        cliente = st.text_input("Cliente")
        direccion = st.text_input("Dirección")
        if st.button("Agregar"):
            c = obtener_coordenadas(direccion)
            if c:
                guardar_pedido_db(f"PED-{random.randint(10000,99999)}",
                                  cliente,direccion,c[0],c[1])
                st.success("OK")

    with col2:
        file = st.file_uploader("CSV")
        if file and st.button("Procesar CSV"):
            n = procesar_csv(file)
            st.success(f"{n} cargados")

    pedidos = obtener_pedidos_db()
    for p in pedidos:
        colA,colB = st.columns([4,1])
        colA.write(f"{p['cliente']} - {p['direccion']}")
        if colB.button("X", key=p['id']):
            borrar_pedido(p['id'])
            st.rerun()

# ------------------------------------------
# RUTEO
# ------------------------------------------
if mod=="Ruteo":
    st.title("Optimización de Rutas")

    pedidos = obtener_pedidos_db()
    mapa = folium.Map(location=COORD_CENTRAL, zoom_start=13)

    for p in pedidos:
        folium.Marker(p['coordenadas']).add_to(mapa)

    veh = st.number_input("Vehículos",1,5,2)
    clima = st.selectbox("Clima",["Despejado","Lluvia"])

    if st.button("Optimizar"):
        rutas = resolver_ruta(COORD_CENTRAL, pedidos, veh)

        for r in rutas.values():
            geo, dist, tiempo = trazar_ruta(r)
            p50,p90 = eta(tiempo, clima)

            st.write(f"Distancia: {round(dist,1)} km")
            st.write(f"ETA: {p50}-{p90} min")

            folium.PolyLine(geo).add_to(mapa)

    st_folium(mapa, width=800, height=500)
