import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly
import io
import re
from datetime import datetime

# Configuración inicial de la página
st.set_page_config(page_title="Auditor Avanzado - Darwinex Zero", layout="wide", page_icon="📊")

# --- BASE DE DATOS TEMPORAL PARA TIEMPO REAL ---
if 'registro_operaciones_en_vivo' not in st.session_state:
    st.session_state['registro_operaciones_en_vivo'] = []

# --- ENDPOINT RECEPTOR DE DATOS (WEBHOOK DE MT5) ---
# Streamlit permite capturar parámetros de la URL para recibir datos de fuera
query_params = st.query_params
if "action" in query_params and query_params["action"] == "webhook_mt5":
    try:
        nuevo_trade = {
            "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Magic": query_params.get("magic", "0"),
            "Simbolo": query_params.get("symbol", "EURUSD"),
            "Tipo": query_params.get("type", "BUY/SELL"),
            "Beneficio": float(query_params.get("profit", "0.0")),
            "Equity": float(query_params.get("equity", "0.0"))
        }
        st.session_state['registro_operaciones_en_vivo'].append(nuevo_trade)
        st.success("Dato recibido de MT5 con éxito")
    except Exception as e:
        st.error(f"Error procesando webhook: {e}")

# --- MENÚ DE PESTAÑAS (NAVEGACIÓN) ---
tab1, tab2 = st.tabs(["📉 Comparador de Degradación (QA vs Real)", "⚡ Monitor de EAs en Tiempo Real"])

# ==========================================
# PESTAÑA 1: COMPARADOR DE DEGRADACIÓN (CÓDIGO ANTERIOR)
# ==========================================
with tab1:
    st.title("📊 Monitor de Degradación de Portfolio")
    st.subheader("Quant Analyzer vs. Cuenta Real Darwinex Zero (MT5)")
    
    st.sidebar.header("⚙️ Parámetros de Control")
    umbral_alerta = st.sidebar.slider("Umbral de Alerta ($)", min_value=0, max_value=2000, value=200, step=50)

    col1, col2 = st.columns(2)
    with col1:
        archivo_qa = st.file_uploader("Subir informe de QA (CSV amontonado o agrupado)", type=["csv", "xlsx", "html", "htm"], key="qa")
    with col2:
        archivo_real = st.file_uploader("Subir reporte exportado de MT5", type=["csv", "xlsx", "html", "htm"], key="real")

    # [Aquí va exactamente el mismo bloque de procesamiento matemático de archivos que te di en la respuesta anterior para no duplicar espacio de texto]
    # (Si necesitas el bloque completo fusionado me avisas, pero es pegar la lógica anterior aquí dentro)

# ==========================================
# PESTAÑA 2: MONITOR EN TIEMPO REAL VÍA WEBHOOK
# ==========================================
with tab2:
    st.title("⚡ Monitor de EAs en Vivo")
    st.markdown("Esta pantalla se actualiza automáticamente cada vez que tus robots ejecutan o cierran una operación en tu MT5.")

    # URL del Webhook para configurar en tu EA
    url_app = "https://streamlit.app" # Cambia esto por tu URL real de Streamlit Cloud
    url_webhook = f"{url_app}/?action=webhook_mt5&magic=12345&symbol=EURUSD&type=BUY&profit=50.5&equity=10500"
    
    st.code(f"🔗 URL Base para Webhook en MT5:\n{url_app}/?action=webhook_mt5", language="text")
    st.info("💡 Copia la URL de arriba y configúrala en los parámetros del EA que te dejo abajo.")

    # Acciones de control de la base de datos en vivo
    if st.button("🗑️ Limpiar Historial en Vivo"):
        st.session_state['registro_operaciones_en_vivo'] = []
        st.rerun()

    # Mostrar métricas en tiempo real si hay datos
    if st.session_state['registro_operaciones_en_vivo']:
        df_vivo = pd.DataFrame(st.session_state['registro_operaciones_en_vivo'])
        
        # KPIs en vivo
        m1, m2, m3 = st.columns(3)
        m1.metric("Última Equity Recibida", f"${df_vivo['Equity'].iloc[-1]:,.2f}")
        m2.metric("Flujo Neto en Vivo", f"${df_vivo['Beneficio'].sum():,.2f}", 
                  delta=f"${df_vivo['Beneficio'].iloc[-1]} último trade")
        m3.metric("Total de Trades Capturados", f"{len(df_vivo)}")

        # Gráfico de curva de equidad en tiempo real
        st.write("### 📈 Curva de Equity en Tiempo Real")
        fig_vivo = object_plotly.Figure()
        fig_vivo.add_trace(object_plotly.Scatter(x=df_vivo['Fecha'], y=df_vivo['Equity'], mode='lines+markers', name='Equity en Vivo', line=dict(color='#2ca02c', width=3)))
        fig_vivo.update_layout(template="plotly_dark", xaxis_title="Tiempo / Fecha", yaxis_title="Balance de Cuenta ($)")
        st.plotly_chart(fig_vivo, use_container_width=True)

        # Tabla detallada de operaciones del robot
        st.write("### 📋 Registro de Transacciones Recientes")
        st.dataframe(df_vivo.sort_index(ascending=False), use_container_width=True)
    else:
        st.warning("⏳ Esperando la conexión con MT5... Ningún dato ha llegado todavía al Webhook.")
