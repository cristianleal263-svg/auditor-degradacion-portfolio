import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly
import io

st.set_page_config(page_title="Auditor de Degradación - SQ v136", layout="wide", page_icon="📊")
st.title("📊 Monitor de Degradación de Portfolio")
st.subheader("Quant Analyzer vs. Cuenta Real (Análisis Mes a Mes)")

# Parámetros
st.sidebar.header("⚙️ Parámetros de Control")
umbral_alerta = st.sidebar.slider("Umbral de Alerta ($)", min_value=0, max_value=2000, value=200, step=50)

col1, col2 = st.columns(2)
with col1:
    st.write("### 📉 1. Datos de Quant Analyzer")
    archivo_qa = st.file_uploader("Subir informe de QA", type=["csv", "xlsx", "html", "htm"], key="qa")
with col2:
    st.write("### 💰 2. Datos del Broker (Real)")
    archivo_real = st.file_uploader("Subir operaciones reales", type=["csv", "xlsx", "html", "htm"], key="real")

def leer_archivo_inteligente(archivo):
    contenido = archivo.read()
    for engine in [lambda: pd.read_excel(io.BytesIO(contenido)), 
                   lambda: pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore'))),
                   lambda: pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore')), sep=';')]:
        try:
            df = engine()
            df.columns = df.columns.str.strip()
            if len(df.columns) > 1: return df
        except: pass
    try:
        tablas = pd.read_html(io.BytesIO(contenido))
        for t in tablas:
            t.columns = t.columns.str.strip()
            if any(c in t.columns for c in ['Fecha', 'Beneficio', 'Profit', 'Time', 'Close time']): return t
        return max(tablas, key=len)
    except: pass
    raise ValueError("Formato no soportado.")

if archivo_qa and archivo_real:
    try:
        # --- PROCESAR COMPONENTE QUANT ANALYZER ---
        df_qa = leer_archivo_inteligente(archivo_qa)
        
        # SI ES UNA LISTA DE OPERACIONES (COMO LA DE TU CAPTURA)
        if 'Close time' in df_qa.columns or 'Open time' in df_qa.columns:
            fecha_col = 'Close time' if 'Close time' in df_qa.columns else 'Open time'
            profit_col = 'Profit/Loss' if 'Profit/Loss' in df_qa.columns else ('P/L in money' if 'P/L in money' in df_qa.columns else 'Profit')
            
            df_qa['Fecha_Clean'] = pd.to_datetime(df_qa[fecha_col], errors='coerce')
            df_qa = df_qa.dropna(subset=['Fecha_Clean'])
            df_qa['Periodo'] = df_qa['Fecha_Clean'].dt.to_period('M').astype(str)
            
            if df_qa[profit_col].dtype == 'object':
                df_qa[profit_col] = df_qa[profit_col].astype(str).str.replace(r'[^\d\.\-]', '', regex=True)
            df_qa['Teorico'] = pd.to_numeric(df_qa[profit_col], errors='coerce').fillna(0)
            df_qa_mensual = df_qa.groupby('Periodo')['Teorico'].sum().reset_index()
            
        # SI ES EL REPORTE MENSUAL TRADICIONAL
        else:
            rename_qa = {'Año': 'Año', 'Year': 'Año', 'año': 'Año', 'Mes': 'Mes', 'Month': 'Mes', 'Ganancia': 'Teorico', 'Profit': 'Teorico', 'Net Profit': 'Teorico'}
            df_qa = df_qa.rename(columns=rename_qa)
            df_qa['Periodo'] = df_qa['Año'].astype(str).str.split('.').str[0] + '-' + df_qa['Mes'].astype(str).str.split('.').str[0].str.zfill(2)
            df_qa_mensual = df_qa.groupby('Periodo')['Teorico'].sum().reset_index()

        # --- PROCESAR CUENTA REAL ---
        df_broker = leer_archivo_inteligente(archivo_real)
        rename_broker = {'Fecha': 'Fecha', 'Time': 'Fecha', 'Date': 'Fecha', 'Close time': 'Fecha', 'Beneficio': 'Beneficio', 'Profit': 'Beneficio', 'Profit/Loss': 'Beneficio'}
        df_broker = df_broker.rename(columns=rename_broker)
        
        df_broker['Fecha'] = pd.to_datetime(df_broker['Fecha'], errors='coerce')
        df_broker = df_broker.dropna(subset=['Fecha'])
        df_broker['Periodo'] = df_broker['Fecha'].dt.to_period('M').astype(str)
        
        if df_broker['Beneficio'].dtype == 'object':
            df_broker['Beneficio'] = df_broker['Beneficio'].astype(str).str.replace(r'[^\d\.\-]', '', regex=True)
        df_broker['Beneficio'] = pd.to_numeric(df_broker['Beneficio'], errors='coerce').fillna(0)
        df_real_mensual = df_broker.groupby('Periodo')['Beneficio'].sum().reset_index().rename(columns={'Beneficio': 'Real'})

        # --- MERGE Y RESULTADOS ---
        df_final = pd.merge(df_qa_mensual, df_real_mensual, on='Periodo', how='outer').fillna(0).sort_values(by='Periodo').reset_index(drop=True)
        df_final['Desviacion'] = df_final['Real'] - df_final['Teorico']
        
        df_final['Estado'] = df_final['Desviacion'].apply(lambda x: '🚨 Apagar / Revisar' if x < -umbral_alerta else ('🚀 Superando' if x >= 0 else '✅ Tolerable'))

        # KPIs
        tot_teorico, tot_real = df_final['Teorico'].sum(), df_final['Real'].sum()
        st.write("---")
        st.write("## 📈 Rendimiento Global")
        k1, k2, k3 = st.columns(3)
        k1.metric("Ganancia Teórica", f"${tot_teorico:,.2f}")
        k2.metric("Ganancia Real", f"${tot_real:,.2f}", delta=f"${tot_real - tot_teorico:,.2f}")
        k3.metric("Degradación %", f"{((tot_real - tot_teorico)/tot_teorico*100 if tot_teorico!=0 else 0):.2f}%")

        # Gráfico
        st.write("---")
        fig = object_plotly.Figure()
        fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Teorico'], name='Teórico (QA)', marker_color='#1f77b4'))
        fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Real'], name='Real (Broker)', marker_color='#2ca02c'))
        fig.add_trace(object_plotly.Scatter(x=df_final['Periodo'], y=df_final['Desviacion'], name='Desviación', line=dict(color='#d62728', width=3, dash='dot')))
        fig.update_layout(barmode='group', template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # Tabla
        st.write("---")
        st.dataframe(df_final, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Error de procesamiento: {e}")

else:
    st.info("💡 Por favor, vuelve a subir los archivos para iniciar la decodificación automática.")
