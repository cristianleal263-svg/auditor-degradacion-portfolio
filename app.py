import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly
import io
import re
from datetime import datetime

# 1. Configuración de la página web
st.set_page_config(page_title="Auditor Avanzado - Darwinex Zero", layout="wide", page_icon="📊")

# 2. Base de datos interna para el almacenamiento en tiempo real
if 'registro_operaciones_en_vivo' not in st.session_state:
    st.session_state['registro_operaciones_en_vivo'] = []

# 3. Receptor de datos en segundo plano (Webhook)
query_params = st.query_params
if "action" in query_params and query_params["action"] == "webhook_mt5":
    try:
        nuevo_trade = {
            "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Magic": str(query_params.get("magic", "0")),
            "Simbolo": str(query_params.get("symbol", "PORTFOLIO")),
            "Tipo": str(query_params.get("type", "LIVE")),
            "Beneficio": float(query_params.get("profit", "0.0")),
            "Equity": float(query_params.get("equity", "0.0"))
        }
        # Evitar registros duplicados consecutivos en recargas manuales
        if not st.session_state['registro_operaciones_en_vivo'] or st.session_state['registro_operaciones_en_vivo'][-1]["Equity"] != nuevo_trade["Equity"]:
            st.session_state['registro_operaciones_en_vivo'].append(nuevo_trade)
    except Exception as e:
        pass

# 4. Funciones auxiliares para la Pestaña 1 (Análisis de archivos)
def procesar_csv_sucio(archivo):
    contenido = archivo.read().decode('utf-8', errors='ignore')
    lineas = contenido.splitlines()
    datos_limpios = []
    for linea in lineas:
        linea_limpia = re.sub(r'^\d+,', '', linea)
        datos_limpios.append(linea_limpia)
    texto_final = "\n".join(datos_limpios)
    df = pd.read_csv(io.StringIO(texto_final), sep=',')
    df.columns = df.columns.str.strip()
    return df

def leer_archivo_inteligente(archivo):
    try:
        df = procesar_csv_sucio(archivo)
        if len(df.columns) > 2: return df
    except: pass
    
    archivo.seek(0)
    contenido = archivo.read()
    
    for engine in [lambda: pd.read_excel(io.BytesIO(contenido)), 
                   lambda: pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore')), sep=';')]:
        try:
            df = engine()
            df.columns = df.columns.str.strip()
            if len(df.columns) > 1: return df
        except: pass
    try:
        tablas = pd.read_html(io.BytesIO(contenido))
        for t in tablas:
            t.columns = t.columns.astype(str).str.strip()
            if len(t.columns) > 3: return t
        return max(tablas, key=len)
    except: pass
    raise ValueError("Formato no soportado.")

def encontrar_columnas_universal(df):
    col_fecha, col_profit = None, None
    mapeo_fechas = ['close time', 'open time', 'fecha', 'time', 'date', 'tiempo', 'close_time', 'open_time', 'time / ticket']
    mapeo_profits = ['profit/loss', 'p/l in money', 'profit', 'loss', 'beneficio', 'p/l', 'ganancia', 'ganancia/pérdida', 'monto']
    columnas_lower = [str(c).lower() for c in df.columns]
    
    for mf in mapeo_fechas:
        if mf in columnas_lower:
            col_fecha = df.columns[columnas_lower.index(mf)]
            break
    for mp in mapeo_profits:
        if mp in columnas_lower:
            col_profit = df.columns[columnas_lower.index(mp)]
            break
            
    if col_fecha is None or col_profit is None:
        for col in df.columns:
            primeros_valores = df[col].dropna().head(15).astype(str)
            if col_fecha is None and primeros_valores.str.contains(r'\d{4}[-./]\d{2}[-./]\d{2}').any():
                col_fecha = col
            if col_profit is None and col != col_fecha:
                valores_numericos = pd.to_numeric(primeros_valores.str.replace(r'[^\d\.\-]', '', regex=True), errors='coerce')
                if valores_numericos.notna().sum() > 3 and not (valores_numericos == 0).all():
                    col_profit = col
    return col_fecha, col_profit

# 5. Estructura de navegación por pestañas
st.title("📊 Centro de Control de Portfolio")
tab1, tab2 = st.tabs(["📉 Comparador de Degradación (QA vs Real)", "⚡ Monitor de EAs en Tiempo Real"])

# ==========================================
# PESTAÑA 1: COMPARADOR DE REPORTES DEGRADACIÓN
# ==========================================
with tab1:
    st.subheader("Análisis Estático: Quant Analyzer vs. Cuenta Real Darwinex Zero (MT5)")
    umbral_alerta = st.slider("Umbral de Alerta ($)", min_value=0, max_value=2000, value=200, step=50, key="slider_tab1")

    col1, col2 = st.columns(2)
    with col1:
        archivo_qa = st.file_uploader("Subir informe de QA", type=["csv", "xlsx", "html", "htm"], key="qa")
    with col2:
        archivo_real = st.file_uploader("Subir reporte exportado de MT5", type=["csv", "xlsx", "html", "htm"], key="real")

    if archivo_qa and archivo_real:
        try:
            df_qa = leer_archivo_inteligente(archivo_qa)
            archivo_real.seek(0)
            f_qa, p_qa = encontrar_columnas_universal(df_qa)
            df_qa['Fecha_Clean'] = pd.to_datetime(df_qa[f_qa], errors='coerce')
            df_qa = df_qa.dropna(subset=['Fecha_Clean'])
            df_qa['Periodo'] = df_qa['Fecha_Clean'].dt.to_period('M').astype(str)
            
            if df_qa[p_qa].dtype == 'object':
                df_qa[p_qa] = df_qa[p_qa].astype(str).str.replace(r'[^\d\.\-]', '', regex=True)
            df_qa['Teorico'] = pd.to_numeric(df_qa[p_qa], errors='coerce').fillna(0)
            df_qa_mensual = df_qa.groupby('Periodo')['Teorico'].sum().reset_index()

            df_broker = leer_archivo_inteligente(archivo_real)
            f_br, p_br = encontrar_columnas_universal(df_broker)
            df_broker['Fecha_Clean'] = pd.to_datetime(df_broker[f_br], errors='coerce')
            if df_broker['Fecha_Clean'].isna().all():
                df_broker['Fecha_Clean'] = pd.to_datetime(df_broker[f_br], format='mixed', errors='coerce')
            df_broker = df_broker.dropna(subset=['Fecha_Clean'])
            df_broker['Periodo'] = df_broker['Fecha_Clean'].dt.to_period('M').astype(str)
            
            if df_broker[p_br].dtype == 'object':
                df_broker[p_br] = df_broker[p_br].astype(str).str.replace(' ', '').str.replace(',', '')
                df_broker[p_br] = df_broker[p_br].str.replace(r'[^\d\.\-]', '', regex=True)
            df_broker['Real'] = pd.to_numeric(df_broker[p_br], errors='coerce').fillna(0)
            df_real_mensual = df_broker.groupby('Periodo')['Real'].sum().reset_index()

            df_final = pd.merge(df_qa_mensual, df_real_mensual, on='Periodo', how='outer').fillna(0).sort_values(by='Periodo').reset_index(drop=True)
            df_final['Desviacion'] = df_final['Real'] - df_final['Teorico']

            tot_teorico, tot_real = df_final['Teorico'].sum(), df_final['Real'].sum()
            
            st.write("---")
            k1, k2, k3 = st.columns(3)
            k1.metric("Ganancia Teórica Total", f"${tot_teorico:,.2f}")
            k2.metric("Ganancia Real Total", f"${tot_real:,.2f}", delta=f"${tot_real - tot_teorico:,.2f}")
            k3.metric("Degradación del Portfolio", f"{((tot_real - tot_teorico)/tot_teorico*100 if tot_teorico!=0 else 0):.2f}%")

            fig = object_plotly.Figure()
            fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Teorico'], name='Teórico (QA)', marker_color='#1f77b4'))
            fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Real'], name='Real (Broker)', marker_color='#2ca02c'))
            fig.add_trace(object_plotly.Scatter(x=df_final['Periodo'], y=df_final['Desviacion'], name='Desviación Neta', line=dict(color='#d62728', width=3, dash='dot')))
            fig.update_layout(barmode='group', template="plotly_dark", xaxis_title="Mes", yaxis_title="Balance ($)")
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(df_final, use_container_width=True)
        except Exception as e:
            st.error(f"❌ Error procesando archivos de reportes: {e}")
    else:
        st.info("💡 Sube tus archivos históricos en los paneles superiores para calcular la degradación mensual.")

# ==========================================
# PESTAÑA 2: MONITOR EN TIEMPO REAL VÍA WEBHOOK
# ==========================================
with tab2:
    st.subheader("Análisis Dinámico: Monitoreo Activo de Flotante y Riesgo (MQL5 Link)")
    
    url_app = "https://streamlit.app"
    st.code(f"🔗 URL Base para Webhook en MT5:\n{url_app}/?action=webhook_mt5", language="text")

    if st.button("🗑️ Reiniciar Métricas en Vivo", key="btn_reset_live"):
        st.session_state['registro_operaciones_en_vivo'] = []
        st.rerun()

    if st.session_state['registro_operaciones_en_vivo']:
        df_vivo = pd.DataFrame(st.session_state['registro_operaciones_en_vivo'])
        df_vivo['Fecha'] = pd.to_datetime(df_vivo['Fecha'])
        
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        df_hoy = df_vivo[df_vivo['Fecha'].dt.strftime("%Y-%m-%d") == fecha_hoy]
        if df_hoy.empty:
            df_hoy = df_vivo.tail(1)

        equity_actual = df_vivo['Equity'].iloc[-1]
        max_equity_dia = df_hoy['Equity'].max()
        min_equity_dia = df_hoy['Equity'].min()
        
        pico_historico_sesion = df_vivo['Equity'].cummax().iloc[-1]
        if pico_historico_sesion > 0:
            drawdown_en_vivo_usd = pico_historico_sesion - equity_actual
            drawdown_en_vivo_pct = (drawdown_en_vivo_usd / pico_historico_sesion) * 100
        else:
            drawdown_en_vivo_usd, drawdown_en_vivo_pct = 0.0, 0.0

        st.write("---")
        if drawdown_en_vivo_pct > 3.0:
            st.error(f"⚠️ **ALERTA DE DRAWDOWN:** El flotante actual consume un **{drawdown_en_vivo_pct:.2f}%** de la cuenta.")

        kpi_dd, kpi_max, kpi_min = st.columns(3)
