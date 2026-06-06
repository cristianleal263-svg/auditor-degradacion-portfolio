import streamlit as st
import pandas as pd
import plotly.graph_objects as object_plotly
import io

# Configuración de la página web
st.set_page_config(page_title="Auditor de Degradación - SQ v136", layout="wide", page_icon="📊")

st.title("📊 Monitor de Degradación de Portfolio")
st.subheader("Quant Analyzer vs. Cuenta Real (Análisis Mes a Mes)")
st.markdown("Carga tus archivos de QA y Broker (Acepta cualquier formato CSV, Excel o informes exportados de MT4/MT5).")

# Panel Lateral para parámetros de control
st.sidebar.header("⚙️ Parámetros de Control")
umbral_alerta = st.sidebar.slider("Umbral de Alerta ($)", min_value=0, max_value=2000, value=200, step=50,
                                  help="Te avisa si la realidad rinde este valor por debajo de la teoría.")

# Distribución de columnas para subida de archivos
col1, col2 = st.columns(2)

with col1:
    st.write("### 📉 1. Datos de Quant Analyzer")
    archivo_qa = st.file_uploader("Subir informe de QA", type=["csv", "xlsx", "html", "htm"], key="qa")
    
with col2:
    st.write("### 💰 2. Datos del Broker (Real)")
    archivo_real = st.file_uploader("Subir operaciones reales", type=["csv", "xlsx", "html", "htm"], key="real")

# Función inteligente para leer archivos corruptos o mal formateados
def leer_archivo_inteligente(archivo):
    contenido = archivo.read()
    
    # Intento 1: Probar como Excel nativo moderno
    try:
        df = pd.read_excel(io.BytesIO(contenido))
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        pass

    # Intento 2: Probar como CSV (Delimitado por comas)
    try:
        df = pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore')))
        df.columns = df.columns.str.strip()
        if len(df.columns) > 1:
            return df
    except Exception:
        pass

    # Intento 3: Probar como CSV (Delimitado por punto y coma, clásico de Excel en español)
    try:
        df = pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore')), sep=';')
        df.columns = df.columns.str.strip()
        if len(df.columns) > 1:
            return df
    except Exception:
        pass

    # Intento 4: Probar si es un reporte HTML renombrado a XLSX (Típico de MetaTrader)
    try:
        tablas = pd.read_html(io.BytesIO(contenido))
        for df_tabla in tablas:
            df_tabla.columns = df_tabla.columns.str.strip()
            # Buscar que tenga columnas útiles
            if any(col in df_tabla.columns for col in ['Fecha', 'Beneficio', 'Profit', 'Time', 'Año', 'Mes', 'Ganancia']):
                return df_tabla
        # Si no tiene los nombres correctos, devolver la tabla más grande encontrada
        return max(tablas, key=len)
    except Exception:
        pass

    raise ValueError("No se pudo descifrar la estructura del archivo. Intenta exportarlo de nuevo en formato CSV estándar.")

# Procesamiento principal si ambos archivos están cargados
if archivo_qa and archivo_real:
    try:
        # --- PROCESAR QUANT ANALYZER ---
        df_qa = leer_archivo_inteligente(archivo_qa)
        
        # Mapear nombres si están en inglés o minúsculas
        rename_qa = {
            'Año': 'Año', 'Year': 'Año', 'año': 'Año', 'year': 'Año',
            'Mes': 'Mes', 'Month': 'Mes', 'mes': 'Mes', 'month': 'Mes',
            'Ganancia': 'Ganancia', 'Profit': 'Ganancia', 'ganancia': 'Ganancia', 'profit': 'Ganancia', 'Net Profit': 'Ganancia'
        }
        df_qa = df_qa.rename(columns=rename_qa)
        
        if not all(col in df_qa.columns for col in ['Año', 'Mes', 'Ganancia']):
            st.error(f"❌ El archivo de Quant Analyzer no tiene las columnas requeridas. Encontradas: {list(df_qa.columns)}")
            st.stop()
            
        # Formatear el periodo (Año-Mes)
        df_qa['Periodo'] = df_qa['Año'].astype(str).str.split('.').str[0] + '-' + df_qa['Mes'].astype(str).str.split('.').str[0].str.zfill(2)
        df_qa = df_qa.rename(columns={'Ganancia': 'Teorico'})[['Periodo', 'Teorico']]
        df_qa = df_qa.groupby('Periodo')['Teorico'].sum().reset_index()

        # --- PROCESAR CUENTA REAL ---
        df_broker = leer_archivo_inteligente(archivo_real)
        
        # Mapear nombres comunes del broker
        rename_broker = {
            'Fecha': 'Fecha', 'Time': 'Fecha', 'Date': 'Fecha', 'fecha': 'Fecha', 'time': 'Fecha',
            'Beneficio': 'Beneficio', 'Profit': 'Beneficio', 'beneficio': 'Beneficio', 'profit': 'Beneficio'
        }
        df_broker = df_broker.rename(columns=rename_broker)
        
        if not all(col in df_broker.columns for col in ['Fecha', 'Beneficio']):
            st.error(f"❌ El archivo del Broker no tiene las columnas requeridas. Encontradas: {list(df_broker.columns)}")
            st.stop()
        
        # Limpieza de fechas y cálculo mensual
        df_broker['Fecha'] = pd.to_datetime(df_broker['Fecha'], errors='coerce')
        df_broker = df_broker.dropna(subset=['Fecha'])
        df_broker['Periodo'] = df_broker['Fecha'].dt.to_period('M').astype(str)
        
        # Limpieza de valores numéricos por si vienen con texto o símbolos de moneda
        if df_broker['Beneficio'].dtype == 'object':
            df_broker['Beneficio'] = df_broker['Beneficio'].astype(str).str.replace(r'[^\d\.\-]', '', regex=True)
        df_broker['Beneficio'] = pd.to_numeric(df_broker['Beneficio'], errors='coerce').fillna(0)
        
        df_real_mensual = df_broker.groupby('Periodo')['Beneficio'].sum().reset_index()
        df_real_mensual = df_real_mensual.rename(columns={'Beneficio': 'Real'})

        # --- MERGE Y MÉTRICAS ---
        df_final = pd.merge(df_qa, df_real_mensual, on='Periodo', how='outer').fillna(0)
        df_final = df_final.sort_values(by='Periodo').reset_index(drop=True)
        df_final['Desviacion'] = df_final['Real'] - df_final['Teorico']
        
        def evaluar_estado(row):
            if row['Desviacion'] < -umbral_alerta:
                return '🚨 Apagar / Revisar'
            elif row['Desviacion'] >= 0 and row['Teorico'] != 0:
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
        st.error(f"❌ Error al procesar los datos: {e}")
else:
    st.info("💡 Por favor, vuelve a subir los archivos para iniciar la decodificación automática.")
