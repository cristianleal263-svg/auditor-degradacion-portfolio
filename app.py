import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly

# Configuración de la página web
st.set_page_config(page_title="Auditor de Degradación - SQ v136", layout="wide", page_icon="📊")

st.title("📊 Monitor de Degradación de Portfolio")
st.subheader("Quant Analyzer vs. Cuenta Real (Análisis Mes a Mes)")
st.markdown("Carga tus archivos CSV o Excel (XLSX) para auditar la pérdida de ventaja (*edge*) de tus robots.")

# Panel Lateral para parámetros de control
st.sidebar.header("⚙️ Parámetros de Control")
umbral_alerta = st.sidebar.slider("Umbral de Alerta ($)", min_value=0, max_value=2000, value=200, step=50,
                                  help="Te avisa si la realidad rinde este valor por debajo de la teoría.")

# Distribución de columnas para subida de archivos
col1, col2 = st.columns(2)

with col1:
    st.write("### 📉 1. Datos de Quant Analyzer")
    archivo_qa = st.file_uploader("Subir informe de QA (Año, Mes, Ganancia)", type=["csv", "xlsx"], key="qa")
    
with col2:
    st.write("### 💰 2. Datos del Broker (Real)")
    archivo_real = st.file_uploader("Subir operaciones reales (Fecha, Beneficio)", type=["csv", "xlsx"], key="real")

# Función auxiliar para leer CSV o Excel de forma segura
def leer_archivo(archivo):
    if archivo.name.endswith('.csv'):
        df = pd.read_csv(archivo)
    else:
        df = pd.read_excel(archivo)
    df.columns = df.columns.str.strip() # Limpiar espacios en los nombres de las columnas
    return df

# Procesamiento principal si ambos archivos están cargados
if archivo_qa and archivo_real:
    try:
        # --- PROCESAR QUANT ANALYZER ---
        df_qa = leer_archivo(archivo_qa)
        
        # Verificar columnas mínimas requeridas
        if not all(col in df_qa.columns for col in ['Año', 'Mes', 'Ganancia']):
            st.error("❌ El archivo de Quant Analyzer debe contener las columnas: 'Año', 'Mes' y 'Ganancia'")
            st.stop()
            
        # Formatear el periodo (Año-Mes)
        df_qa['Periodo'] = df_qa['Año'].astype(str) + '-' + df_qa['Mes'].astype(str).str.zfill(2)
        df_qa = df_qa.rename(columns={'Ganancia': 'Teorico'})[['Periodo', 'Teorico']]

        # --- PROCESAR CUENTA REAL ---
        df_broker = leer_archivo(archivo_real)
        
        if not all(col in df_broker.columns for col in ['Fecha', 'Beneficio']):
            st.error("❌ El archivo del Broker debe contener las columnas: 'Fecha' y 'Beneficio'")
            st.stop()
        
        # Convertir fecha de forma flexible y agrupar por mes
        df_broker['Fecha'] = pd.to_datetime(df_broker['Fecha'])
        df_broker['Periodo'] = df_broker['Fecha'].dt.to_period('M').astype(str)
        df_real_mensual = df_broker.groupby('Periodo')['Beneficio'].sum().reset_index()
        df_real_mensual = df_real_mensual.rename(columns={'Beneficio': 'Real'})

        # --- MERGE Y MÉTRICAS ---
        df_final = pd.merge(df_qa, df_real_mensual, on='Periodo', how='outer').fillna(0)
        df_final['Desviacion'] = df_final['Real'] - df_final['Teorico']
        
        # Sistema de alertas condicionales
        def evaluar_estado(row):
            if row['Desviacion'] < -umbral_alerta:
                return '🚨 Apagar / Revisar'
            elif row['Desviacion'] >= 0:
                return '🚀 Superando Backtest'
            else:
                return '✅ Tolerable'
                
        df_final['Estado'] = df_final.apply(evaluar_estado, axis=1)

        # --- KPIs TOTALES ---
        tot_teorico = df_final['Teorico'].sum()
        tot_real = df_final['Real'].sum()
        degradacion_total = tot_real - tot_teorico
        
        st.write("---")
        st.write("## 📈 Rendimiento Global")
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Ganancia Teórica (QA)", f"${tot_teorico:,.2f}")
        kpi2.metric("Ganancia Real (Broker)", f"${tot_real:,.2f}", delta=f"${degradacion_total:,.2f}")
        
        pct_degradacion = (degradacion_total / tot_teorico * 100) if tot_teorico != 0 else 0
        kpi3.metric("Degradación Total (%)", f"{pct_degradacion:.2f}%", 
                   delta="¡Pérdida de Edge!" if pct_degradacion < 0 else "Estable", 
                   delta_color="inverse")

        # --- GRÁFICO INTERACTIVO ---
        st.write("---")
        st.write("## 📊 Comparativa Temporal")
        
        fig = object_plotly.Figure()
        fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Teorico'], name='Teórico (QA)', marker_color='#1f77b4'))
        fig.add_trace(object_plotly.Bar(x=df_final['Periodo'], y=df_final['Real'], name='Real (Broker)', marker_color='#2ca02c'))
        fig.add_trace(object_plotly.Scatter(x=df_final['Periodo'], y=df_final['Desviacion'], name='Desviación Neta', line=dict(color='#d62728', width=3, dash='dot')))
        
        fig.update_layout(barmode='group', title="Rendimiento Mensual y Desviación", xaxis_title="Mes", yaxis_title="Dinero ($)", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # --- TABLA DE DATOS DETALLADA ---
        st.write("---")
        st.write("## 📋 Desglose Mensual")
        
        def estilar_filas(val):
            if '🚨' in str(val): return 'background-color: #ffcccc; color: #cc0000; font-weight: bold;'
            if '🚀' in str(val): return 'background-color: #ccffcc; color: #006600; font-weight: bold;'
            return ''
            
        df_visual = df_final.copy()
        df_visual['Teorico'] = df_visual['Teorico'].map('${:,.2f}'.format)
        df_visual['Real'] = df_visual['Real'].map('${:,.2f}'.format)
        df_visual['Desviacion'] = df_visual['Desviacion'].map('${:,.2f}'.format)
        
        st.dataframe(df_visual.style.applymap(estilar_filas, subset=['Estado']), use_container_width=True)

    except Exception as e:
        st.error(f"❌ Error al procesar los archivos: {e}. Revisa el formato interno.")
else:
    st.info("💡 Por favor, arrastra y suelta ambos archivos en los paneles superiores para comenzar el análisis.")
