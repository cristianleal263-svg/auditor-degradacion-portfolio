import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import re
import math
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Centro de Control - Darwinex Zero",
    layout="wide",
    page_icon="🦁"
)

# CSS personalizado
st.markdown("""
<style>
    .metric-card {
        background: #1a1a2e;
        border: 1px solid #16213e;
        border-radius: 8px;
        padding: 16px;
        margin: 4px 0;
    }
    .alert-dd { 
        background: linear-gradient(135deg, #3d0000, #1a0000);
        border-left: 4px solid #ff4444;
        padding: 12px 16px;
        border-radius: 4px;
        color: #ff8888;
        font-weight: bold;
    }
    .alert-ok {
        background: linear-gradient(135deg, #003d00, #001a00);
        border-left: 4px solid #44ff44;
        padding: 12px 16px;
        border-radius: 4px;
        color: #88ff88;
    }
    .stTabs [data-baseweb="tab"] { font-size: 15px; font-weight: 600; }
    div[data-testid="metric-container"] > div { font-size: 13px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
if 'registro_operaciones_en_vivo' not in st.session_state:
    st.session_state['registro_operaciones_en_vivo'] = []
if 'capital_inicial' not in st.session_state:
    st.session_state['capital_inicial'] = 10000.0

# ─────────────────────────────────────────────
# WEBHOOK RECEPTOR
# ─────────────────────────────────────────────
query_params = st.query_params
if "action" in query_params and query_params["action"] == "webhook_mt5":
    try:
        nuevo_trade = {
            "Fecha":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Magic":     str(query_params.get("magic", "0")),
            "Simbolo":   str(query_params.get("symbol", "PORTFOLIO")),
            "Tipo":      str(query_params.get("type", "LIVE")),
            "Beneficio": float(query_params.get("profit", "0.0")),
            "Equity":    float(query_params.get("equity", "0.0"))
        }
        registros = st.session_state['registro_operaciones_en_vivo']
        if not registros or registros[-1]["Equity"] != nuevo_trade["Equity"]:
            registros.append(nuevo_trade)
    except Exception:
        pass

# ─────────────────────────────────────────────
# FUNCIONES AUXILIARES — TAB 1
# ─────────────────────────────────────────────
def procesar_csv_sucio(archivo):
    contenido = archivo.read().decode('utf-8', errors='ignore')
    lineas = contenido.splitlines()
    datos_limpios = [re.sub(r'^\d+,', '', l) for l in lineas]
    df = pd.read_csv(io.StringIO("\n".join(datos_limpios)), sep=',')
    df.columns = df.columns.str.strip()
    return df

def leer_archivo_inteligente(archivo):
    try:
        df = procesar_csv_sucio(archivo)
        if len(df.columns) > 2:
            return df
    except Exception:
        pass
    archivo.seek(0)
    contenido = archivo.read()
    for engine in [
        lambda: pd.read_excel(io.BytesIO(contenido)),
        lambda: pd.read_csv(io.StringIO(contenido.decode('utf-8', errors='ignore')), sep=';')
    ]:
        try:
            df = engine()
            df.columns = df.columns.str.strip()
            if len(df.columns) > 1:
                return df
        except Exception:
            pass
    try:
        tablas = pd.read_html(io.BytesIO(contenido))
        for t in tablas:
            t.columns = t.columns.astype(str).str.strip()
            if len(t.columns) > 3:
                return t
        return max(tablas, key=len)
    except Exception:
        pass
    raise ValueError("Formato no soportado.")

def encontrar_columnas_universal(df):
    col_fecha, col_profit = None, None
    mapeo_fechas  = ['close time','open time','fecha','time','date','tiempo','close_time','open_time','time / ticket']
    mapeo_profits = ['profit/loss','p/l in money','profit','loss','beneficio','p/l','ganancia','ganancia/pérdida','monto']
    columnas_lower = [str(c).lower() for c in df.columns]
    for mf in mapeo_fechas:
        if mf in columnas_lower:
            col_fecha = df.columns[columnas_lower.index(mf)]; break
    for mp in mapeo_profits:
        if mp in columnas_lower:
            col_profit = df.columns[columnas_lower.index(mp)]; break
    if col_fecha is None or col_profit is None:
        for col in df.columns:
            primeros = df[col].dropna().head(15).astype(str)
            if col_fecha is None and primeros.str.contains(r'\d{4}[-./]\d{2}[-./]\d{2}').any():
                col_fecha = col
            if col_profit is None and col != col_fecha:
                nums = pd.to_numeric(primeros.str.replace(r'[^\d\.\-]','',regex=True), errors='coerce')
                if nums.notna().sum() > 3 and not (nums == 0).all():
                    col_profit = col
    return col_fecha, col_profit

# ─────────────────────────────────────────────
# FUNCIONES MÉTRICAS — TAB 2
# ─────────────────────────────────────────────
def calcular_sharpe(serie_retornos, periodos_anuales=252):
    """Sharpe ratio anualizado sobre serie de retornos diarios"""
    if len(serie_retornos) < 2:
        return 0.0
    media = serie_retornos.mean()
    std   = serie_retornos.std()
    if std == 0:
        return 0.0
    return round((media / std) * math.sqrt(periodos_anuales), 2)

def calcular_metricas_portfolio(df_trades):
    """Calcula todas las métricas de calidad del portfolio"""
    if df_trades.empty:
        return {}

    beneficios = df_trades['Beneficio']
    ganancias  = beneficios[beneficios > 0]
    perdidas   = beneficios[beneficios < 0]

    # Profit Factor
    gross_profit = ganancias.sum() if not ganancias.empty else 0
    gross_loss   = abs(perdidas.sum()) if not perdidas.empty else 0
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf')

    # Win Rate
    total_trades = len(beneficios[beneficios != 0])
    win_rate = round(len(ganancias) / total_trades * 100, 1) if total_trades > 0 else 0

    # Avg Win / Avg Loss
    avg_win  = round(ganancias.mean(), 2) if not ganancias.empty else 0
    avg_loss = round(perdidas.mean(), 2) if not perdidas.empty else 0

    # Expectancy
    expectancy = round((win_rate/100 * avg_win) + ((1 - win_rate/100) * abs(avg_loss)) * -1 +
                       (win_rate/100 * avg_win), 2) if total_trades > 0 else 0
    # Fórmula correcta
    expectancy = round((win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss), 2)

    # Sharpe sobre retornos por trade
    retornos = beneficios[beneficios != 0]
    sharpe = calcular_sharpe(retornos, periodos_anuales=len(retornos))

    # Max Drawdown de la serie de equity
    equity_serie = df_trades['Equity']
    if not equity_serie.empty:
        peak = equity_serie.cummax()
        dd_serie = (equity_serie - peak) / peak * 100
        max_dd = round(dd_serie.min(), 2)
    else:
        max_dd = 0.0

    # Recovery Factor
    net_profit = beneficios.sum()
    recovery   = round(net_profit / abs(max_dd) * 100, 2) if max_dd != 0 else 0

    return {
        "profit_factor": pf,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "sharpe": sharpe,
        "max_dd_pct": max_dd,
        "recovery_factor": recovery,
        "total_trades": total_trades,
        "net_profit": round(net_profit, 2)
    }

def color_pf(pf):
    if pf == float('inf') or pf >= 1.5: return "🟢"
    if pf >= 1.2: return "🟡"
    return "🔴"

def color_sharpe(s):
    if s >= 1.0: return "🟢"
    if s >= 0.5: return "🟡"
    return "🔴"

# ─────────────────────────────────────────────
# LAYOUT PRINCIPAL
# ─────────────────────────────────────────────
st.title("🦁 Centro de Control de Portfolio — Darwinex Zero")
tab1, tab2 = st.tabs(["📉 Comparador de Degradación (QA vs Real)", "⚡ Monitor de EAs en Tiempo Real"])

# ══════════════════════════════════════════════
# TAB 1 — ANÁLISIS ESTÁTICO
# ══════════════════════════════════════════════
with tab1:
    st.subheader("Análisis Estático: Quant Analyzer vs. Cuenta Real Darwinex Zero (MT5)")
    umbral_alerta = st.slider("Umbral de Alerta ($)", 0, 2000, 200, 50, key="slider_tab1")

    col1, col2 = st.columns(2)
    with col1:
        archivo_qa   = st.file_uploader("Subir informe de QA", type=["csv","xlsx","html","htm"], key="qa")
    with col2:
        archivo_real = st.file_uploader("Subir reporte exportado de MT5", type=["csv","xlsx","html","htm"], key="real")

    if archivo_qa and archivo_real:
        try:
            df_qa = leer_archivo_inteligente(archivo_qa)
            archivo_real.seek(0)
            f_qa, p_qa = encontrar_columnas_universal(df_qa)
            df_qa['Fecha_Clean'] = pd.to_datetime(df_qa[f_qa], errors='coerce')
            df_qa = df_qa.dropna(subset=['Fecha_Clean'])
            df_qa['Periodo'] = df_qa['Fecha_Clean'].dt.to_period('M').astype(str)
            if df_qa[p_qa].dtype == 'object':
                df_qa[p_qa] = df_qa[p_qa].astype(str).str.replace(r'[^\d\.\-]','',regex=True)
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
                df_broker[p_br] = df_broker[p_br].astype(str).str.replace(' ','').str.replace(',','')
                df_broker[p_br] = df_broker[p_br].str.replace(r'[^\d\.\-]','',regex=True)
            df_broker['Real'] = pd.to_numeric(df_broker[p_br], errors='coerce').fillna(0)
            df_real_mensual = df_broker.groupby('Periodo')['Real'].sum().reset_index()

            df_final = pd.merge(df_qa_mensual, df_real_mensual, on='Periodo', how='outer').fillna(0)
            df_final = df_final.sort_values('Periodo').reset_index(drop=True)
            df_final['Desviacion'] = df_final['Real'] - df_final['Teorico']

            tot_teorico = df_final['Teorico'].sum()
            tot_real    = df_final['Real'].sum()
            degradacion = (tot_real - tot_teorico) / tot_teorico * 100 if tot_teorico != 0 else 0

            st.write("---")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Ganancia Teórica Total",  f"${tot_teorico:,.2f}")
            k2.metric("Ganancia Real Total",      f"${tot_real:,.2f}", delta=f"${tot_real - tot_teorico:,.2f}")
            k3.metric("Degradación del Portfolio", f"{degradacion:.2f}%")
            k4.metric("Meses con Alerta (>${:.0f})".format(umbral_alerta),
                      str(len(df_final[abs(df_final['Desviacion']) > umbral_alerta])))

            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_final['Periodo'], y=df_final['Teorico'],  name='Teórico (QA)',    marker_color='#1f77b4'))
            fig.add_trace(go.Bar(x=df_final['Periodo'], y=df_final['Real'],     name='Real (Broker)',   marker_color='#2ca02c'))
            fig.add_trace(go.Scatter(x=df_final['Periodo'], y=df_final['Desviacion'], name='Desviación Neta',
                                     line=dict(color='#d62728', width=3, dash='dot'), mode='lines+markers'))
            # Banda de umbral
            fig.add_hline(y=umbral_alerta,  line_dash="dash", line_color="orange", annotation_text=f"+${umbral_alerta}")
            fig.add_hline(y=-umbral_alerta, line_dash="dash", line_color="orange", annotation_text=f"-${umbral_alerta}")
            fig.update_layout(barmode='group', template="plotly_dark", xaxis_title="Mes", yaxis_title="Balance ($)",
                              height=420, margin=dict(t=20))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_final, use_container_width=True)

        except Exception as e:
            st.error(f"❌ Error procesando archivos: {e}")
    else:
        st.info("💡 Sube tus archivos históricos para calcular la degradación mensual.")

# ══════════════════════════════════════════════
# TAB 2 — MONITOR EN TIEMPO REAL
# ══════════════════════════════════════════════
with tab2:
    st.subheader("Análisis Dinámico: Monitor Activo de Portfolio (MQL5 → Webhook)")

    # ── Configuración superior ──────────────────
    cfg1, cfg2, cfg3 = st.columns([2, 1, 1])
    with cfg1:
        url_actual = st.text_input("URL de tu app (para el webhook en MT5)",
                                   value="https://TU-APP.streamlit.app")
        st.code(f"{url_actual}/?action=webhook_mt5&magic=22001&symbol=XAUUSD&type=CLOSE&profit=12.50&equity=10250.00",
                language="text")
    with cfg2:
        capital_input = st.number_input("Capital Inicial ($)", min_value=1000.0,
                                        value=st.session_state['capital_inicial'],
                                        step=500.0, format="%.2f")
        st.session_state['capital_inicial'] = capital_input
    with cfg3:
        st.write("")
        st.write("")
        if st.button("🗑️ Reiniciar Métricas en Vivo"):
            st.session_state['registro_operaciones_en_vivo'] = []
            st.rerun()

    st.write("---")

    # ── Sin datos ────────────────────────────────
    if not st.session_state['registro_operaciones_en_vivo']:
        st.info("⏳ Esperando datos desde MT5... El EA enviará métricas cada 10 segundos vía OnTimer().")
        st.stop()

    # ── DataFrame principal ──────────────────────
    df_vivo = pd.DataFrame(st.session_state['registro_operaciones_en_vivo'])
    df_vivo['Fecha'] = pd.to_datetime(df_vivo['Fecha'])

    # ── Selector Magic Number ────────────────────
    magics_disponibles = sorted(df_vivo['Magic'].unique().tolist())
    magic_labels = {m: f"EA {m}" for m in magics_disponibles}
    magic_labels["TODOS"] = "📊 TODOS los EAs"

    col_sel1, col_sel2 = st.columns([1, 3])
    with col_sel1:
        filtro_magic = st.selectbox(
            "Filtrar por EA (Magic Number)",
            options=["TODOS"] + magics_disponibles,
            format_func=lambda x: magic_labels.get(x, x)
        )

    # Aplicar filtro
    if filtro_magic == "TODOS":
        df_filtrado = df_vivo.copy()
    else:
        df_filtrado = df_vivo[df_vivo['Magic'] == filtro_magic].copy()

    # ── Cálculos de riesgo ───────────────────────
    fecha_hoy     = datetime.now().strftime("%Y-%m-%d")
    df_hoy        = df_filtrado[df_filtrado['Fecha'].dt.strftime("%Y-%m-%d") == fecha_hoy]
    if df_hoy.empty:
        df_hoy = df_filtrado.tail(1)

    equity_actual      = df_filtrado['Equity'].iloc[-1]
    max_equity_dia     = df_hoy['Equity'].max()
    min_equity_dia     = df_hoy['Equity'].min()
    pico_historico     = df_filtrado['Equity'].cummax().iloc[-1]
    capital_inicial    = st.session_state['capital_inicial']

    dd_usd = pico_historico - equity_actual
    dd_pct = (dd_usd / pico_historico * 100) if pico_historico > 0 else 0.0
    retorno_total_pct = (equity_actual - capital_inicial) / capital_inicial * 100

    # ── ALERTA DRAWDOWN ──────────────────────────
    if dd_pct > 5.0:
        st.markdown(f'<div class="alert-dd">⛔ ALERTA CRÍTICA: DD en vivo {dd_pct:.2f}% — Supera límite Darwinex Zero (5%)</div>', unsafe_allow_html=True)
    elif dd_pct > 3.0:
        st.markdown(f'<div class="alert-dd">⚠️ ALERTA DD: {dd_pct:.2f}% desde pico de sesión — Zona de vigilancia</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="alert-ok">✅ Drawdown controlado: {dd_pct:.2f}% — Portfolio operando dentro de parámetros</div>', unsafe_allow_html=True)

    st.write("")

    # ── KPIs DE RIESGO ───────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Equity Actual",       f"${equity_actual:,.2f}",  delta=f"{retorno_total_pct:+.2f}%")
    k2.metric("DD Vivo (desde pico)", f"{dd_pct:.2f}%",          delta=f"-${dd_usd:,.2f}", delta_color="inverse")
    k3.metric("High del Día",         f"${max_equity_dia:,.2f}")
    k4.metric("Low del Día",          f"${min_equity_dia:,.2f}")
    k5.metric("Pico Histórico",       f"${pico_historico:,.2f}")

    st.write("---")

    # ── MÉTRICAS DE CALIDAD DEL PORTFOLIO ────────
    st.subheader("📐 Métricas de Calidad — " + ("Portfolio Completo" if filtro_magic == "TODOS" else f"EA {filtro_magic}"))

    # Solo trades cerrados (Beneficio != 0)
    df_trades = df_filtrado[df_filtrado['Beneficio'] != 0].copy()
    metricas  = calcular_metricas_portfolio(df_trades)

    if metricas:
        m1, m2, m3, m4 = st.columns(4)
        pf_val = metricas['profit_factor']
        pf_str = f"{pf_val:.2f}" if pf_val != float('inf') else "∞"
        m1.metric(f"{color_pf(pf_val)} Profit Factor",    pf_str,
                  help="≥1.5 excelente | ≥1.2 aceptable | <1.2 bajo")
        m2.metric(f"{color_sharpe(metricas['sharpe'])} Sharpe Ratio", f"{metricas['sharpe']:.2f}",
                  help="≥1.0 institucional | ≥0.5 aceptable")
        m3.metric("🎯 Win Rate",        f"{metricas['win_rate']:.1f}%")
        m4.metric("💰 Net Profit",      f"${metricas['net_profit']:,.2f}")

        m5, m6, m7, m8 = st.columns(4)
        m5.metric("📈 Avg Win",         f"${metricas['avg_win']:,.2f}")
        m6.metric("📉 Avg Loss",        f"${metricas['avg_loss']:,.2f}")
        m7.metric("⚡ Expectancy/Trade", f"${metricas['expectancy']:,.2f}",
                  help="Ganancia esperada por operación")
        m8.metric("🔄 Recovery Factor", f"{metricas['recovery_factor']:.2f}",
                  help="Profit / MaxDD — >3 es institucional")

        # KPI extra
        m9, m10, _, _ = st.columns(4)
        m9.metric("📊 Max DD (serie)",  f"{metricas['max_dd_pct']:.2f}%")
        m10.metric("🔢 Total Trades",   str(metricas['total_trades']))
    else:
        st.info("Sin trades cerrados para calcular métricas. Los envíos de tipo CLOSE aparecerán aquí.")

    st.write("---")

    # ── GRÁFICO EQUITY + DRAWDOWN ─────────────────
    st.subheader("📈 Curva de Equity en Vivo")

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.05,
        subplot_titles=("Equity", "Drawdown %")
    )

    # Equity line
    fig.add_trace(go.Scatter(
        x=df_filtrado['Fecha'],
        y=df_filtrado['Equity'],
        name="Equity",
        line=dict(color='#00d4ff', width=2),
        fill='tozeroy',
        fillcolor='rgba(0, 212, 255, 0.08)'
    ), row=1, col=1)

    # Capital inicial reference
    fig.add_hline(y=capital_inicial, line_dash="dot", line_color="#888888",
                  annotation_text=f"Capital inicial ${capital_inicial:,.0f}", row=1, col=1)

    # Drawdown subplot
    dd_serie = (df_filtrado['Equity'] - df_filtrado['Equity'].cummax()) / df_filtrado['Equity'].cummax() * 100
    fig.add_trace(go.Scatter(
        x=df_filtrado['Fecha'],
        y=dd_serie,
        name="DD%",
        line=dict(color='#ff4444', width=1.5),
        fill='tozeroy',
        fillcolor='rgba(255, 68, 68, 0.15)'
    ), row=2, col=1)

    # Líneas de alerta DD
    fig.add_hline(y=-3.0, line_dash="dash", line_color="orange", row=2, col=1,
                  annotation_text="-3%")
    fig.add_hline(y=-5.0, line_dash="dash", line_color="red", row=2, col=1,
                  annotation_text="-5% Límite DZ")

    fig.update_layout(
        template="plotly_dark",
        height=520,
        showlegend=True,
        margin=dict(t=30, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── DESGLOSE POR EA ──────────────────────────
    if filtro_magic == "TODOS" and len(magics_disponibles) > 1:
        st.write("---")
        st.subheader("🔬 Desglose por EA (Magic Number)")

        cols_ea = st.columns(min(len(magics_disponibles), 5))
        for idx, magic in enumerate(magics_disponibles):
            df_ea     = df_vivo[df_vivo['Magic'] == magic]
            df_trades_ea = df_ea[df_ea['Beneficio'] != 0]
            met_ea    = calcular_metricas_portfolio(df_trades_ea)
            with cols_ea[idx % 5]:
                pf_ea = met_ea.get('profit_factor', 0)
                pf_str_ea = f"{pf_ea:.2f}" if pf_ea != float('inf') else "∞"
                st.markdown(f"**EA {magic}**")
                st.metric("PF",     pf_str_ea)
                st.metric("Sharpe", f"{met_ea.get('sharpe', 0):.2f}")
                st.metric("WR",     f"{met_ea.get('win_rate', 0):.0f}%")
                st.metric("Trades", str(met_ea.get('total_trades', 0)))

    # ── TABLA DE OPERACIONES ─────────────────────
    with st.expander("📋 Ver historial de operaciones recibidas"):
        st.dataframe(
            df_filtrado.sort_values('Fecha', ascending=False).reset_index(drop=True),
            use_container_width=True
        )
