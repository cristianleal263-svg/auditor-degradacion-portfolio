import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly
import io
import re

st.set_page_config(page_title="Auditor de Degradación - Darwinex Zero", layout="wide", page_icon="📊")
st.title("📊 Monitor de Degradación de Portfolio")
st.subheader("Quant Analyzer vs. Cuenta Real Darwinex Zero (MT5)")

st.sidebar.header("⚙️ Parámetros de Control")
umbral_alerta = st.sidebar.slider("Umbral de Alerta ($)", min_value=0, max_value=2000, value=200, step=50)

col1, col2 = st.columns(2)
with col1:
    st.write("### 📉 1. Datos de Quant Analyzer")
    archivo_qa = st.file_uploader("Subir informe de QA (CSV amontonado o agrupado)", type=["csv", "xlsx", "html", "htm"], key="qa")
with col2:
    st.write("### 💰 2. Historial de Darwinex Zero / MT5")
    archivo_real = st.file_uploader("Subir reporte exportado de MT5", type=["csv", "xlsx", "html", "htm"], key="real")

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
    
    # Intentar como Excel nativo
    try:
        df = pd.read_excel(io.BytesIO(contenido))
        df.columns = df.columns.astype(str).str.strip()
        if len(df.columns) > 1: return df
    except: pass

    # Intentar como HTML estructurado (El formato real que genera MT5 cuando guardas como reporte)
    try:
        tablas = pd.read_html(io.BytesIO(contenido))
        for t in tablas:
            t.columns = t.columns.astype(str).str.strip()
            # Buscar patrones típicos de MetaTrader 5 (Órdenes o Posiciones)
            columnas_lower = [str(c).lower() for c in t.columns]
            if any(x in columnas_lower for x in ['time', 'tiempo', 'close time', 'fecha']) and any(y in columnas_lower for y in ['profit', 'beneficio', 'profit/loss']):
                return t
        return max(tablas, key=len)
    except: pass
    
    # Intentar como CSV tradicional
    archivo.seek(0)
    try:
        df = pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore')), sep=';')
        df.columns = df.columns.str.strip()
        return df
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

if archivo_qa and archivo_real:
    try:
        # --- PROCESAR COMPONENTE QUANT ANALYZER ---
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

        # --- PROCESAR HISTORIAL REAL MT5 / DARWINEX ZERO ---
        df_broker = leer_archivo_inteligente(archivo_real)
        f_br, p_br = encontrar_columnas_universal(df_broker)
        
        if f_br is None or p_br is None:
            st.error("❌ No se pudieron mapear las columnas de MT5 de forma automática. Revisa el archivo.")
            st.stop()
            
        # Parseo flexible para las fechas con hora de MT5 (ej: 2026.04.12 15:30:22)
        df_broker['Fecha_Clean'] = pd.to_datetime(df_broker[f_br], errors='coerce')
        if df_broker['Fecha_Clean'].isna().all():
            df_broker['Fecha_Clean'] = pd.to_datetime(df_broker[f_br], format='mixed', errors='coerce')
            
        df_broker = df_broker.dropna(subset=['Fecha_Clean'])
        df_broker['Periodo'] = df_broker['Fecha_Clean'].dt.to_period('M').astype(str)
        
        # Limpieza rigurosa de los beneficios de MT5 (Remueve textos, comisiones encubiertas o símbolos de moneda)
        if df_broker[p_br].dtype == 'object':
            df_broker[p_br] = df_broker[p_br].astype(str).str.replace(' ', '')
            df_broker[p_br] = df_broker[p_br].str.replace(',', '')
            df_broker[p_br] = df_broker[p_br].str.replace(r'[^\d\.\-]', '', regex=True)
            
        df_broker['Real'] = pd.to_numeric(df_broker[p_br], errors='coerce').fillna(0)
        df_real_mensual = df_broker.groupby('Periodo')['Real'].sum().reset_index()

        # --- FUSIONAR RESULTADOS ---
        df_final = pd.merge(df_qa_mensual, df_real_mensual, on='Periodo', how='outer').fillna(0).sort_values(by='Periodo').reset_index(drop=True)
        df_final['Desviacion'] = df_final['Real'] - df_final['Teorico']
        
        df_final['Estado'] = df_final['Desviacion'].apply(lambda x: '🚨 Apagar / Revisar' if x < -umbral_alerta else ('🚀 Superando Backtest' if x >= 0 else '✅ Tolerable'))

        # KPIs Globales
        tot_teorico, tot_real = df_final['Teorico'].sum(), df_final['Real'].sum()
        st.write("---")
        st.write("## 📈 Rendimiento Global en Darwinex Zero")
        k1, k2, k3 = st.columns(3)
        k1.metric("Ganancia Teórica (Backtest)", f"${tot_teorico:,.2f}")
        k2.metric("Ganancia Real (MT5 Live)", f"${tot_real:,.2f}", delta=f"${tot_real - tot_teorico:,.2f}")
        
        pct_deg = ((tot_real - tot_teorico)/tot_teorico*100 if tot_teorico != 0 else 0)
        k3.metric("Degradación de Cartera", f"{pct_deg:.2f}%", delta="Pérdida de Edge" if pct_deg < -15 else "Estable", delta_color="inverse")

        # Gráfico Temporal
        st.write("---")
        st.write("## 📊 Comparativa Temporal Mes a Mes")
        fig = object_plotly.Figure()
        fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Teorico'], name='Teórico (Quant Analyzer)', marker_color='#1f77b4'))
        fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Real'], name='Real (Darwinex Zero MT5)', marker_color='#2ca02c'))
        fig.add_trace(object_plotly.Scatter(x=df_final['Periodo'], y=df_final['Desviacion'], name='Desviación Neta (Diferencial)', line=dict(color='#d62728', width=3, dash='dot')))
        fig.update_layout(barmode='group', template="plotly_dark", xaxis_title="Mes", yaxis_title="Balance ($)", legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
        st.plotly_chart(fig, use_container_width=True)

        # Tabla de Datos
        st.write("---")
        st.write("## 📋 Desglose Analítico Mensual")
        
        df_visual = df_final.copy()
        df_visual['Teorico'] = df_visual['Teorico'].map('${:,.2f}'.format)
        df_visual['Real'] = df_visual['Real'].map('${:,.2f}'.format)
        df_visual['Desviacion'] = df_visual['Desviacion'].map('${:,.2f}'.format)
        st.dataframe(df_visual, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Error crítico en el análisis de datos: {e}")
