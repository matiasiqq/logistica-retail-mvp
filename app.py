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
# 1. CONFIGURACIÓN Y ESTILOS CORPORATIVOS
# ==========================================
st.set_page_config(page_title="Optiaflux | Logística Inteligente", layout="wide")

# Inyección de CSS para un diseño limpio y profesional
st.markdown("""
    <style>
    /* Estilo general de la tipografía y fondo */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    /* Estilización de botones */
    .stButton>button {
        border-radius: 5px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    /* Estilo para las métricas */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
        color: #1E3A8A; /* Azul corporativo oscuro */
    }
    /* Títulos sobrios */
    h1, h2, h3 {
        color: #333333;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    </style>
""", unsafe_allow_html=True)

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
# 3. MOTORES LÓGICOS Y OSRM (RUTEO REAL)
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
    todos = [coordenadas_tienda] + [p['coordenadas'] for p in lista_pedidos]
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in todos])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}?annotations=duration"
    try:
        res = requests.get(url).json()
        if res['code'] == 'Ok':
            return res['durations']
    except:
        return None
    return None

def calcular_ruta_optima_real(coordenadas_tienda, lista_pedidos):
    nodos = [{"id": "TIENDA", "coordenadas": coordenadas_tienda, "cliente": "Central de Distribución", "direccion": "Matriz Operativa"}] + lista_pedidos
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
                tiempo = matriz_tiempos[indice_actual][i]
            else:
                lat1, lon1 = nodos[indice_actual]['coordenadas']
                lat2, lon2 = nodos[i]['coordenadas']
                tiempo = math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) 
                
            if tiempo < menor_tiempo:
                menor_tiempo = tiempo
                siguiente_indice = i
                
        if matriz_tiempos:
            tiempo_transito_minutos += (menor_tiempo / 60.0)
            
        ruta_final.append(nodos[siguiente_indice])
        indices_pendientes.remove(siguiente_indice)
        indice_actual = siguiente_indice
        
    return ruta_final, tiempo_transito_minutos

def trazar_ruta_calles(ruta_ordenada):
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

coord_tienda = [-20.2447, -70.1415] # Falabella Iquique

def limpiar_ruta_guardada():
    st.session_state['ruta_optimizada'] = None
    st.session_state['geometria_calles'] = None

# ==========================================
# 5. FRONTEND - INTERFAZ CORPORATIVA
# ==========================================
st.sidebar.title("Optiaflux")
st.sidebar.caption("SISTEMA DE GESTIÓN LOGÍSTICA")
st.sidebar.divider()

seccion = st.sidebar.radio("Navegación del Sistema", ["Módulo de Ingreso", "Optimización y Ruteo"])
st.sidebar.divider()

st.sidebar.subheader("Conexión de Datos")
st.sidebar.success("Servicios Satelitales: En línea")
ia_clima = st.sidebar.selectbox("Condición Climática Local:", ["Despejado", "Lluvia/Niebla"])

st.sidebar.divider()
st.sidebar.metric("Pedidos Activos", len(pedidos_globales))

# ------------------------------------------
# SECCIÓN 1: GESTIÓN DE PEDIDOS Y CARGA MASIVA
# ------------------------------------------
if seccion == "Módulo de Ingreso":
    st.title("Gestión de Manifiestos")
    st.write("Administración de puntos de entrega e integración de datos.")
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Ingreso Manual")
        with st.form("form_pedido"):
            nombre_cliente = st.text_input("Nombre o Razón Social")
            direccion_texto = st.text_input("Dirección de Entrega (Ej: Los Cóndores 123, Alto Hospicio)")
            btn_guardar = st.form_submit_button("Geocodificar y Agregar")
            
            if btn_guardar and nombre_cliente and direccion_texto:
                with st.spinner('Procesando coordenadas...'):
                    coords = obtener_coordenadas(direccion_texto)
                    if coords:
                        id_aleatorio = f"PED-{random.randint(1000, 9999)}"
                        nuevo_pedido = {"id": id_aleatorio, "coordenadas": coords, "cliente": nombre_cliente, "direccion": direccion_texto}
                        pedidos_globales.append(nuevo_pedido)
                        guardar_pedidos(pedidos_globales)
                        limpiar_ruta_guardada()
                        st.success("Registro ingresado correctamente al sistema central.")
                        st.rerun()
                    else:
                        st.error("Error de validación: No se ha podido verificar la dirección introducida.")

    with col2:
        st.subheader("Integración Masiva")
        st.write("Seleccione un archivo de valores separados por comas (.csv). Columnas requeridas: 'Cliente' y 'Direccion'.")
        archivo_subido = st.file_uploader("", type=["csv"])
        
        if archivo_subido is not None:
            df_cargado = pd.read_csv(archivo_subido)
            st.dataframe(df_cargado.head(3))
            
            if st.button("Procesar Archivo Masivo", type="primary"):
                with st.spinner("Procesando lote de datos. Esto puede tomar unos instantes..."):
                    agregados = 0
                    for index, row in df_cargado.iterrows():
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
                        st.success(f"Operación finalizada. {agregados} registros añadidos exitosamente.")
                        st.rerun()
                    else:
                        st.error("Ningún registro válido encontrado en el documento.")

    st.divider()
    st.subheader("Base de Datos Activa")
    if len(pedidos_globales) > 0:
        for i, pedido in enumerate(pedidos_globales):
            col_info, col_btn = st.columns([8, 2])
            col_info.text(f"ID: {pedido['id']} | Cliente: {pedido['cliente']} | Destino: {pedido['direccion']}")
            if col_btn.button("Eliminar Registro", key=f"del_{pedido['id']}_{i}"):
                pedidos_globales.pop(i)
                guardar_pedidos(pedidos_globales)
                limpiar_ruta_guardada()
                st.rerun()
                
        if st.button("Depurar Base de Datos Completa"):
            guardar_pedidos([]) 
            limpiar_ruta_guardada()
            st.rerun()
    else:
        st.info("El sistema no registra órdenes pendientes de asignación.")

# ------------------------------------------
# SECCIÓN 2: MAPA Y RUTEO (CALLES REALES)
# ------------------------------------------
elif seccion == "Optimización y Ruteo":
    st.title("Panel de Optimización de Rutas")
    st.write("Análisis topológico y asignación predictiva de tiempos.")
    st.divider()
    
    col_datos, col_mapa = st.columns([1, 2])
    
    mapa_optiaflux = folium.Map(location=coord_tienda, zoom_start=14)
    # Marcadores en tonos profesionales (azul corporativo para la central, gris claro para clientes)
    folium.Marker(coord_tienda, popup="Matriz Operativa", icon=folium.Icon(color="darkblue", icon="briefcase")).add_to(mapa_optiaflux)
    
    for paso in pedidos_globales:
        folium.Marker(paso['coordenadas'], popup=f"ID: {paso['id']} - {paso['cliente']}", icon=folium.Icon(color="lightgray", icon="info-sign")).add_to(mapa_optiaflux)

    with col_datos:
        st.subheader("Centro de Análisis")
        if len(pedidos_globales) == 0:
            st.info("Requiere ingreso de manifiestos previos para habilitar el análisis.")
        else:
            if st.button("Ejecutar Algoritmo de Optimización", type="primary", use_container_width=True):
                with st.spinner("Estableciendo conexión con servidores de ruteo OSRM..."):
                    ruta_ordenada, tiempo_base = calcular_ruta_optima_real(coord_tienda, pedidos_globales)
                    forma_calles, distancia_km = trazar_ruta_calles(ruta_ordenada)
                    
                    st.session_state['ruta_optimizada'] = ruta_ordenada
                    st.session_state['geometria_calles'] = forma_calles
                    st.session_state['tiempo_base_minutos'] = tiempo_base
                    st.session_state['distancia_km'] = distancia_km

            if st.session_state['ruta_optimizada'] is not None:
                ruta_guardada = st.session_state['ruta_optimizada']
                geometria_guardada = st.session_state['geometria_calles']
                
                eta_ia, estado_trafico, hora_leida = motor_ia_predictivo_avanzado(st.session_state['tiempo_base_minutos'], ia_clima)
                
                # Diseño de reporte analítico limpio
                st.write("")
                st.markdown("**Resumen de Ruta**")
                st.write(f"Distancia Total Calculada: {round(st.session_state['distancia_km'], 2)} km")
                st.write(f"Densidad Vehicular: {estado_trafico}")
                st.write(f"Lectura de Servidor: {hora_leida} hrs")
                
                st.metric(label="Tiempo Estimado (ETA)", value=f"{eta_ia} min", delta="Ajustado algorítmicamente", delta_color="normal")
                
                # Línea de ruta en azul corporativo
                folium.PolyLine(geometria_guardada, color="#1E3A8A", weight=5, opacity=0.85).add_to(mapa_optiaflux)
                
                df_descarga = pd.DataFrame([{"Secuencia": i, "ID Registro": paso["id"], "Razón Social": paso["cliente"], "Dirección": paso.get("direccion", "N/A")} for i, paso in enumerate(ruta_guardada)])
                csv_export = df_descarga.to_csv(index=False).encode('utf-8')
                
                st.write("")
                st.download_button(label="Exportar Manifiesto CSV", data=csv_export, file_name='manifiesto_optiaflux.csv', mime='text/csv', use_container_width=True)

    with col_mapa:
        # Se elimina el título innecesario arriba del mapa para aprovechar la pantalla completa
        st_folium(mapa_optiaflux, width=800, height=600)
