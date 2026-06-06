import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly
import io
import re
from datetime import datetime

# Configuración inicial de la página
st.set_page_config(page_title="Auditor Avanzado - Darwinex Zero", layout="wide", page_icon="📊")

# --- BASE DE DATOS LOCAL SEGURA ---
if 'registro_operaciones_en_vivo' not in st.session_state:
    st.session_state['registro_operaciones_en_vivo'] = []

# --- RECEPTOR MEJORADO DE WEBHOOKS ---
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
        # Evitar duplicados rápidos en recargas de página
        if not st.session_state['registro_operaciones_en_vivo'] or st.session_state['registro_operaciones_en_vivo'][-1]["Equity"] != nuevo_trade["Equity"]:
            st.session_state['registro_operaciones_en_vivo'].append(nuevo_trade)
    except Exception as e:
        st.error(f"Error procesando datos: {e}")

# [El resto del código de pestañas, KPIs y gráficos se mantiene exactamente igual]
