import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
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
import base64

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
    .streamlit-expanderHeader { font-weight: bold; color: #333; }
    </style>
""", unsafe_allow_html=True)

geolocalizador = Nominatim(user_agent="optiaflux_erp_app")
COORD_CENTRAL = [-20.2447, -70.1415] 

# ==========================================
# 2. ARQUITECTURA DE BASE DE DATOS Y SECUENCIAS
# ==========================================
def init_db():
    conn = sqlite3.connect('optiaflux.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id TEXT PRIMARY KEY, cliente TEXT, direccion TEXT, lat REAL, lon REAL, estado TEXT, fecha_ingreso TEXT, foto TEXT, fecha_entrega TEXT)''')
    
    # Migraciones seguras para actualizar DBs antiguas
    try: c.execute("ALTER TABLE pedidos ADD COLUMN foto TEXT")
    except: pass
    try: c.execute("ALTER TABLE pedidos ADD COLUMN fecha_entrega TEXT")
    except: pass
        
    conn.commit()
    return conn

conn = init_db()

def obtener_siguiente_id():
    """Genera un ID secuencial ordenado leyendo la base de datos."""
    c = conn.cursor()
    c.execute("SELECT id FROM pedidos")
    filas = c.fetchall()
    if not filas:
        return "PED-0001"
    
    max_num = 0
    for f in filas:
        try:
            num = int(f[0].split("-")[1])
            if num > max_num: max_num = num
        except: pass
    return f"PED-{max_num + 1:04d}"

def guardar_pedido_db(id_ped, cliente, direccion, lat, lon):
    c = conn.cursor()
    fecha = datetime.now(pytz.timezone('America/Santiago')).strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (id_ped, cliente, direccion, lat, lon, "Pendiente", fecha, "", ""))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def obtener_pedidos_db(estado_filtro=None):
    c = conn.cursor()
    if estado_filtro:
        c.execute("SELECT id, cliente, direccion, lat, lon, estado, fecha_ingreso, foto, fecha_entrega FROM pedidos WHERE estado = ?", (estado_filtro,))
    else:
        c.execute("SELECT id, cliente, direccion, lat, lon, estado, fecha_ingreso, foto, fecha_entrega FROM pedidos")
    filas = c.fetchall()
    return [{"id": f[0], "cliente": f[1], "direccion": f[2], "coordenadas": [f[3], f[4]], "estado": f[5], "fecha": f[6], "foto": f[7], "fecha_entrega": f[8]} for f in filas]

def actualizar_estado_y_foto_db(id_ped, nuevo_estado, foto_b64=""):
    c = conn.cursor()
    fecha_ahora = datetime.now(pytz.timezone('America/Santiago')).strftime("%Y-%m-%d %H:%M:%S")
    if nuevo_estado == "Entregado":
        c.execute("UPDATE pedidos SET estado = ?, foto = ?, fecha_entrega = ? WHERE id = ?", (nuevo_estado, foto_b64, fecha_ahora, id_ped))
    else:
        c.execute("UPDATE pedidos SET estado = ?, foto = ? WHERE id = ?", (nuevo_estado, foto_b64, id_ped))
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
            # Ruta Solo Ida: No retorna a la central al finalizar
            if len(ruta_actual) > 1: 
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
# 4. MOTOR IA PREDICTIVO Y BI (GÉNERO/ENTIDAD)
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

def predecir_genero_o_entidad(nombre_completo):
    """Detecta si es Empresa, Hombre o Mujer basado en reglas heurísticas del español."""
    if not nombre_completo: return "Desconocido"
    nombre_lower = nombre_completo.lower()
    
    entidades = ['empresa', 'supermercado', 'tienda', 'comercial', 's.a.', 'ltda', 'spa', 'centro', 'hospital', 'clinica', 'municipalidad', 'colegio', 'condominio', 'hotel', 'mall', 'puerto', 'parroquia', 'bomberos', 'feria', 'autodromo', 'sede']
    if any(word in nombre_lower for word in entidades):
        return "Empresa/Institución"
        
    nombre_pila = nombre_completo.split()[0].lower()
    excepciones_masculinas = ['jose', 'josé', 'rene', 'rené', 'luis', 'carlos', 'juan', 'manuel', 'david', 'ariel', 'felipe', 'gabriel']
    excepciones_femeninas = ['carmen', 'pilar', 'luz', 'paz', 'rosario', 'dolores', 'sol', 'abigail', 'raquel', 'inés', 'ines', 'isabel', 'beatriz']
    
    if nombre_pila in excepciones_masculinas: return "Hombre"
    if nombre_pila in excepciones_femeninas: return "Mujer"
    if nombre_pila.endswith('a'): return "Mujer"
    return "Hombre"

# ==========================================
# 5. MEMORIA DE SESIÓN ROBUSTA
# ==========================================
if 'rutas_calculadas' not in st.session_state: st.session_state['rutas_calculadas'] = None
if 'datos_trazado' not in st.session_state: st.session_state['datos_trazado'] = {}

def limpiar_memoria_rutas():
    st.session_state['rutas_calculadas'] = None
    st.session_state['datos_trazado'] = {}

COLORES_MARCADORES = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'beige', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'pink', 'lightblue', 'lightgreen', 'black']

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
                        id_secuencial = obtener_siguiente_id()
                        if guardar_pedido_db(id_secuencial, cliente, direccion, coords[0], coords[1]):
                            limpiar_memoria_rutas() 
                            st.success(f"Transacción exitosa. Asignado: {id_secuencial}")
                            st.rerun()
                    else:
                        st.error("Error geográfico.")

    with col2:
        st.subheader("Integración Masiva (CSV robusto)")
        archivo = st.file_uploader("Formatos aceptados: .csv", type=["csv"])
        if archivo and st.button("Procesar Lote de Datos", type="primary"):
            try:
                df = pd.read_csv(archivo, sep=None, engine='python', encoding='utf-8')
            except UnicodeDecodeError:
                archivo.seek(0)
                df = pd.read_csv(archivo, sep=None, engine='python', encoding='latin1')
                
            df.columns = df.columns.str.strip().str.lower()
            
            if 'cliente' in df.columns and 'direccion' in df.columns:
                df = df.dropna(subset=['cliente', 'direccion'])
                bar = st.progress(0)
                exito = 0
                for idx, row in df.iterrows():
                    dir_texto = str(row['direccion']).strip()
                    if dir_texto and dir_texto.lower() != 'nan':
                        coords = obtener_coordenadas(dir_texto)
                        if coords:
                            id_secuencial = obtener_siguiente_id()
                            guardar_pedido_db(id_secuencial, str(row['cliente']).strip(), dir_texto, coords[0], coords[1])
                            exito += 1
                    bar.progress((idx + 1) / len(df))
                limpiar_memoria_rutas()
                st.success(f"Lote procesado. {exito} registros insertados ordenadamente.")
                st.rerun()
            else:
                st.error("El archivo CSV debe contener exactamente las columnas 'cliente' y 'direccion'.")

    st.divider()
    st.subheader("Base de Datos Activa (Visualizador de PoD)")
    pedidos_todos = obtener_pedidos_db()
    if pedidos_todos:
        for i, p in enumerate(pedidos_todos):
            col_info, col_btn = st.columns([8, 2])
            
            with col_info:
                with st.expander(f"📦 {p['id']} | 👤 {p['cliente']} | 📍 {p['direccion']} | 🚦 {p['estado']}"):
                    st.write(f"**Fecha de Ingreso:** {p['fecha']}")
                    if p['estado'] == 'Entregado':
                        st.write(f"**Fecha de Entrega:** {p['fecha_entrega']}")
                        if p['foto']:
                            st.image(base64.b64decode(p['foto']), caption="📸 Fotografía de Comprobación", use_container_width=True)
                        else:
                            st.info("Entrega marcada manualmente sin evidencia fotográfica.")
                    else:
                        st.warning("Entrega pendiente de ejecución en terreno.")
                        
            with col_btn:
                if st.button("❌ Eliminar", key=f"del_{p['id']}"):
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
                colores_lineas = ['#1E3A8A', '#10B981', '#F59E0B', '#DC2626', '#8B5CF6', '#14B8A6']
                
                for i, (vehiculo, ruta) in enumerate(st.session_state['rutas_calculadas'].items()):
                    color_v = colores_lineas[i % len(colores_lineas)]
                    
                    if vehiculo in st.session_state.get('datos_trazado', {}):
                        datos_v = st.session_state['datos_trazado'][vehiculo]
                        
                        eta_ia, estado_trafico, hora_leida = motor_ia_predictivo_avanzado(datos_v["tiempo"], ia_clima)
                        
                        st.markdown(f"### 🚚 {vehiculo}")
                        st.write(f"**Distancia (Solo Ida):** {round(datos_v['dist'], 1)} km | **Tráfico:** {estado_trafico}")
                        st.metric(label=f"⏱️ ETA Real a Último Cliente", value=f"{eta_ia} min")
                        
                        folium.PolyLine(datos_v["geom"], color=color_v, weight=6, opacity=0.85).add_to(mapa)
                    else:
                        st.warning(f"⚠️ Datos en proceso para {vehiculo}.")

    with col_mapa:
        for j, p in enumerate(pedidos_pendientes):
            color_marcador = COLORES_MARCADORES[j % len(COLORES_MARCADORES)]
            folium.Marker(p['coordenadas'], popup=f"{p['id']} - {p['cliente']}", icon=folium.Icon(color=color_marcador, icon="info-sign")).add_to(mapa)
        st_folium(mapa, width=800, height=600)

# ------------------------------------------
# MÓDULO 3: PORTAL CONDUCTOR (TERRENO)
# ------------------------------------------
elif modulo == "3️⃣ Portal Conductor (Terreno)":
    st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>📱 Portal Operador Terreno</h2>", unsafe_allow_html=True)
    st.divider()
    
    pedidos_pendientes = obtener_pedidos_db(estado_filtro="Pendiente")
    if not pedidos_pendientes:
        st.success("🎉 Ruta completada. No hay órdenes pendientes.")
    else:
        for p in pedidos_pendientes:
            with st.expander(f"📍 {p['direccion']} | {p['cliente']}"):
                st.write(f"**ID:** {p['id']}")
                st.info("Usa el icono de rotación 🔄 de tu cámara móvil para alternar entre cámara frontal o trasera.")
                
                foto_capturada = st.camera_input("Capturar evidencia fotográfica", key=f"cam_{p['id']}")
                
                if st.button("✅ Confirmar Entrega", key=f"btn_{p['id']}", type="primary", use_container_width=True):
                    if foto_capturada:
                        foto_b64 = base64.b64encode(foto_capturada.getvalue()).decode()
                        actualizar_estado_y_foto_db(p['id'], "Entregado", foto_b64)
                    else:
                        actualizar_estado_y_foto_db(p['id'], "Entregado", "")
                        
                    limpiar_memoria_rutas() 
                    st.success("Información transmitida a la Central.")
                    st.rerun()

# ------------------------------------------
# MÓDULO 4: INTELIGENCIA DE NEGOCIOS (BI)
# ------------------------------------------
elif modulo == "4️⃣ Inteligencia de Negocios (BI)":
    st.title("📊 Analítica de Datos Integral")
    st.divider()
    
    datos_brutos = obtener_pedidos_db()
    if not datos_brutos:
        st.info("El sistema requiere data histórica para los análisis.")
    else:
        df = pd.DataFrame(datos_brutos)
        
        # Procesamiento Cronológico y SLA (Acuerdo de Nivel de Servicio)
        df['fecha_ingreso_dt'] = pd.to_datetime(df['fecha'], errors='coerce')
        df['fecha_entrega_dt'] = pd.to_datetime(df['fecha_entrega'], errors='coerce')
        
        # Fechas y Agrupaciones
        df['dia'] = df['fecha_ingreso_dt'].dt.date
        df['mes'] = df['fecha_ingreso_dt'].dt.to_period('M').astype(str)
        df['año'] = df['fecha_ingreso_dt'].dt.year
        
        # Estimación de Demora y SLA (Consideramos "A tiempo" si se entrega dentro de 180 min - 3 horas)
        df['minutos_demora'] = (df['fecha_entrega_dt'] - df['fecha_ingreso_dt']).dt.total_seconds() / 60
        df['cumple_tiempo'] = df.apply(lambda x: "A tiempo" if pd.notnull(x['minutos_demora']) and x['minutos_demora'] <= 180 else ("Atrasado" if pd.notnull(x['minutos_demora']) else "Pendiente"), axis=1)
        
        # Estimación de Género/Entidad
        df['perfil_cliente'] = df['cliente'].apply(predecir_genero_o_entidad)
        
        # Métricas Globales
        total = len(df)
        entregados = len(df[df['estado'] == 'Entregado'])
        pendientes = total - entregados
        
        st.subheader("Resumen General")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Volumen Total Operado", total)
        col2.metric("Entregas Exitosas", entregados)
        col3.metric("Manifiestos en Tránsito", pendientes)
        
        a_tiempo_count = len(df[df['cumple_tiempo'] == 'A tiempo'])
        tasa_sla = round((a_tiempo_count / entregados) * 100, 1) if entregados > 0 else 0
        col4.metric("Nivel de SLA (A Tiempo)", f"{tasa_sla}%")
        
        st.divider()
        
        # Gráficos Analíticos
        r1_col1, r1_col2 = st.columns(2)
        
        with r1_col1:
            st.markdown("#### 📈 Flujo de Pedidos por Día")
            pedidos_por_dia = df.groupby('dia').size().reset_index(name='Cantidad')
            fig_bar = px.bar(pedidos_por_dia, x='dia', y='Cantidad', labels={'dia': 'Fecha', 'Cantidad': 'Nº de Pedidos'})
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with r1_col2:
            st.markdown("#### 🎯 Cumplimiento de Tiempos (SLA)")
            fig_sla = px.pie(df[df['estado'] == 'Entregado'], names='cumple_tiempo', hole=0.4, color='cumple_tiempo', color_discrete_map={'A tiempo':'#10B981', 'Atrasado':'#EF4444'})
            if entregados > 0: st.plotly_chart(fig_sla, use_container_width=True)
            else: st.info("No hay entregas registradas para analizar tiempos.")
            
        st.divider()
        r2_col1, r2_col2 = st.columns(2)
        
        with r2_col1:
            st.markdown("#### 👥 Perfil Demográfico del Cliente")
            fig_gen = px.pie(df, names='perfil_cliente', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_gen, use_container_width=True)
            
        with r2_col2:
            st.markdown("#### 📍 Densidad Espacial de la Demanda")
            mapa_calor = folium.Map(location=COORD_CENTRAL, zoom_start=13)
            coordenadas_calor = [[p['lat'], p['lon']] for _, p in df.iterrows()]
            HeatMap(coordenadas_calor, radius=18, blur=12).add_to(mapa_calor)
            st_folium(mapa_calor, width=500, height=350)
            
        # Tabla resumen por periodos
        st.divider()
        st.markdown("#### 🗓️ Desglose de Operaciones Históricas")
        c_mes, c_ano = st.columns(2)
        with c_mes:
            st.write("**Entregas Consolidadas por Mes:**")
            st.dataframe(df[df['estado'] == 'Entregado'].groupby('mes').size().reset_index(name='Pedidos Completados'), use_container_width=True)
        with c_ano:
            st.write("**Entregas Consolidadas por Año:**")
            st.dataframe(df[df['estado'] == 'Entregado'].groupby('año').size().reset_index(name='Pedidos Completados'), use_container_width=True)
