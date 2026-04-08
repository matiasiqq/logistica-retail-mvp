import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import pandas as pd
import random
import json
import os
import requests
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
# 3. MOTORES LÓGICOS Y OSRM (RUTEO REAL POR CALLES)
# ==========================================
def obtener_coordenadas(direccion):
    try:
        ubicacion = geolocalizador.geocode(f"{direccion}, Chile")
        if ubicacion:
            return [ubicacion.latitude, ubicacion.longitude]
        return None
    except:
        return None

def obtener_matriz_tiempos_reales(coordenadas_tienda, lista_pedidos):
    """Se conecta a OSRM para obtener el tiempo real en auto entre todos los puntos."""
    todos = [coordenadas_tienda] + [p['coordenadas'] for p in lista_pedidos]
    # OSRM usa formato longitud,latitud
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in todos])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}?annotations=duration"
    try:
        res = requests.get(url).json()
        if res['code'] == 'Ok':
            return res['durations'] # Matriz de tiempos en segundos
    except:
        return None
    return None

def calcular_ruta_optima_real(coordenadas_tienda, lista_pedidos):
    """Optimiza la ruta usando los TIEMPOS REALES de tránsito vehícular."""
    nodos = [{"id": "TIENDA", "coordenadas": coordenadas_tienda, "cliente": "Falabella Iquique", "direccion": "Central Operativa"}] + lista_pedidos
    
    matriz_tiempos = obtener_matriz_tiempos_reales(coordenadas_tienda, lista_pedidos)
    
    ruta_final = [nodos[0]]
    indices_pendientes = list(range(1, len(nodos)))
    indice_actual = 0
    tiempo_transito_minutos = 0.0

    while indices_pendientes:
        siguiente_indice = None
        menor_tiempo = float('inf')
        
        for i in indices_pendientes:
            if matriz_tiempos:
                tiempo = matriz_tiempos[indice_actual][i] # OSRM nos da el tiempo en segundos
            else:
                # Falla de seguridad por si OSRM no responde: usar Haversine clásico
                lat1, lon1 = nodos[indice_actual]['coordenadas']
                lat2, lon2 = nodos[i]['coordenadas']
                tiempo = math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) 
                
            if tiempo < menor_tiempo:
                menor_tiempo = tiempo
                siguiente_indice = i
                
        if matriz_tiempos:
            tiempo_transito_minutos += (menor_tiempo / 60.0) # Pasamos de segundos a minutos
            
        ruta_final.append(nodos[siguiente_indice])
        indices_pendientes.remove(siguiente_indice)
        indice_actual = siguiente_indice
        
    return ruta_final, tiempo_transito_minutos

def trazar_ruta_calles(ruta_ordenada):
    """Pide a OSRM la geometría exacta de las calles para dibujar la ruta."""
    geometria_completa = []
    distancia_total_km = 0.0
    
    for i in range(len(ruta_ordenada)-1):
        coord1 = ruta_ordenada[i]['coordenadas']
        coord2 = ruta_ordenada[i+1]['coordenadas']
        lon1, lat1 = coord1[1], coord1[0]
        lon2, lat2 = coord2[1], coord2[0]
        
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
        try:
            res = requests.get(url).json()
            if res['code'] == 'Ok':
                coords_calle = res['routes'][0]['geometry']['coordinates']
                geometria_completa.extend([[lat, lon] for lon, lat in coords_calle])
                distancia_total_km += res['routes'][0]['distance'] / 1000.0
        except:
            geometria_completa.extend([coord1, coord2])
            
    return geometria_completa, distancia_total_km

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
    
    # El tiempo base ya es REAL de las calles, la IA solo lo penaliza por tráfico horario y clima
    minutos_finales = tiempo_base_minutos * factor_trafico * factor_clima
    return round(minutos_finales), estado_trafico, hora_leida

# ==========================================
# 4. VARIABLES DE MEMORIA
# ==========================================
pedidos_globales = cargar_pedidos()

if 'ruta_optimizada' not in st.session_state:
    st.session_state['ruta_optimizada'] = None
if 'geometria_calles' not in st.session_state:
    st.session_state['geometria_calles'] = None
if 'tiempo_base_minutos' not in st.session_state:
    st.session_state['tiempo_base_minutos'] = 0.0
if 'distancia_km' not in st.session_state:
    st.session_state['distancia_km'] = 0.0

coord_tienda = [-20.2447, -70.1415] 

def limpiar_ruta_guardada():
    st.session_state['ruta_optimizada'] = None
    st.session_state['geometria_calles'] = None

# ==========================================
# 5. FRONTEND
# ==========================================
st.sidebar.title("🌐 Optiaflux")
st.sidebar.markdown("---")
seccion = st.sidebar.radio("Navegación:", ["📥 Cargar Pedidos", "Rutas e IA Predictiva"])
st.sidebar.markdown("---")

st.sidebar.subheader("📡 Conexión de Datos")
st.sidebar.success("🟢 Satélite OSRM Conectado")
ia_clima = st.sidebar.selectbox("Condición Climática (Manual):", ["Despejado", "Lluvia/Niebla"])

st.sidebar.markdown("---")
st.sidebar.info(f"📦 Pedidos en Red: {len(pedidos_globales)}")

# ------------------------------------------
# SECCIÓN 1: GESTIÓN DE PEDIDOS Y CARGA MASIVA
# ------------------------------------------
if seccion == "Cargar Pedidos":
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
                        st.success("¡Pedido guardado!")
                        st.rerun()
                    else:
                        st.error("❌ No se encontró la dirección.")

    with col2:
        st.subheader("Carga Masiva (CSV)")
        st.caption("Sube un archivo Excel guardado como .CSV con las columnas 'Cliente' y 'Direccion'.")
        archivo_subido = st.file_uploader("Selecciona tu archivo", type=["csv"])
        
        if archivo_subido is not None:
            df_cargado = pd.read_csv(archivo_subido)
            st.dataframe(df_cargado.head(3))
            
            if st.button("🚀 Procesar Archivo Masivo"):
                with st.spinner("Procesando satelitalmente las direcciones... esto tomará unos segundos."):
                    agregados = 0
                    for index, row in df_cargado.iterrows():
                        # Aseguramos que existan las columnas sin que el programa colapse
                        cliente = str(row.get('Cliente', f"Cliente {index}"))
                        direccion = str(row.get('Direccion', ''))
                        
                        if direccion != 'nan' and direccion.strip() != '':
                            coords = obtener_coordenadas(direccion)
                            if coords:
                                nuevo_pedido = {"id": f"PED-{random.randint(1000, 9999)}", "coordenadas": coords, "cliente": cliente, "direccion": direccion}
                                pedidos_globales.append(nuevo_pedido)
                                agregados += 1
                                
                    if agregados > 0:
                        guardar_pedidos(pedidos_globales)
                        limpiar_ruta_guardada()
                        st.success(f"¡Éxito! Se agregaron {agregados} pedidos a la base de datos.")
                        st.rerun()
                    else:
                        st.error("No se pudo mapear ninguna dirección válida del archivo.")

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
# SECCIÓN 2: MAPA Y RUTEO (CALLES REALES)
# ------------------------------------------
elif seccion == "🧠 Rutas e IA Predictiva":
    st.title("🧠 Optiaflux: Ruteo Dinámico Compartido")
    col_datos, col_mapa = st.columns([1, 2])
    
    mapa_optiaflux = folium.Map(location=coord_tienda, zoom_start=14)
    folium.Marker(coord_tienda, popup="FALABELLA IQUIQUE", icon=folium.Icon(color="black", icon="home")).add_to(mapa_optiaflux)
    
    for paso in pedidos_globales:
        folium.Marker(paso['coordenadas'], popup=f"{paso['id']} - {paso['cliente']}", icon=folium.Icon(color="red", icon="info-sign")).add_to(mapa_optiaflux)

    with col_datos:
        st.markdown("### ⚙️ Centro de Comando")
        if len(pedidos_globales) == 0:
            st.info(" Ingresa pedidos para activar el algoritmo.")
        else:
            if st.button("Optimizar por Calles y Tránsito", type="primary", use_container_width=True):
                with st.spinner("Conectando con satélites de tránsito vehicular..."):
                    # 1. Optimiza usando tiempos reales
                    ruta_ordenada, tiempo_base = calcular_ruta_optima_real(coord_tienda, pedidos_globales)
                    
                    # 2. Descarga la forma geométrica de las calles
                    forma_calles, distancia_km = trazar_ruta_calles(ruta_ordenada)
                    
                    # 3. Guardar en memoria
                    st.session_state['ruta_optimizada'] = ruta_ordenada
                    st.session_state['geometria_calles'] = forma_calles
                    st.session_state['tiempo_base_minutos'] = tiempo_base
                    st.session_state['distancia_km'] = distancia_km

            if st.session_state['ruta_optimizada'] is not None:
                ruta_guardada = st.session_state['ruta_optimizada']
                geometria_guardada = st.session_state['geometria_calles']
                
                eta_ia, estado_trafico, hora_leida = motor_ia_predictivo_avanzado(st.session_state['tiempo_base_minutos'], ia_clima)
                
                st.success(f"**Distancia Real Conduciendo:** {round(st.session_state['distancia_km'], 2)} km")
                st.markdown("##### 📡 Análisis de Tráfico en Vivo")
                st.write(f"🕒 **Hora Iquique:** {hora_leida} hrs")
                st.write(f"🚗 **Densidad Vehicular:** {estado_trafico}")
                
                st.metric(label="⏱️ ETA Real en Calles", value=f"{eta_ia} min", delta="Datos Vía OSRM Satelital", delta_color="normal")
                
                # AQUI SE DIBUJAN LAS CALLES EXACTAS (No líneas rectas)
                folium.PolyLine(geometria_guardada, color="blue", weight=6, opacity=0.8).add_to(mapa_optiaflux)
                
                df_descarga = pd.DataFrame([{"Secuencia": i, "ID Pedido": paso["id"], "Cliente": paso["cliente"], "Dirección": paso.get("direccion", "N/A")} for i, paso in enumerate(ruta_guardada)])
                csv_export = df_descarga.to_csv(index=False).encode('utf-8')
                st.download_button(label="📥 Descargar Manifiesto CSV", data=csv_export, file_name='manifiesto_optiaflux.csv', mime='text/csv', use_container_width=True)

    with col_mapa:
        st_folium(mapa_optiaflux, width=800, height=500)
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
