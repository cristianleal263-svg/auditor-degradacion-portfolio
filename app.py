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
if 'snapshots' not in st.session_state:
    st.session_state['snapshots'] = []          # historial equity/balance/margin
if 'posiciones_abiertas' not in st.session_state:
    st.session_state['posiciones_abiertas'] = {} # ticket → datos
if 'capital_inicial' not in st.session_state:
    st.session_state['capital_inicial'] = 10000.0

# ─────────────────────────────────────────────
# WEBHOOK RECEPTOR
# ─────────────────────────────────────────────
query_params = st.query_params
if "action" in query_params and query_params["action"] == "webhook_mt5":
    try:
        tipo = str(query_params.get("type", "LIVE"))
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if tipo == "SNAPSHOT":
            snap = {
                "Fecha":      ts,
                "Equity":     float(query_params.get("equity", 0)),
                "Balance":    float(query_params.get("balance", 0)),
                "Margin":     float(query_params.get("margin", 0)),
                "FreeMargin": float(query_params.get("free_margin", 0)),
                "ProfitFlot": float(query_params.get("profit_flot", 0)),
                "DD_Equity":  float(query_params.get("dd_equity", 0)),
                "DD_Balance": float(query_params.get("dd_balance", 0)),
            }
            snaps = st.session_state['snapshots']
            if not snaps or snaps[-1]["Equity"] != snap["Equity"]:
                snaps.append(snap)
            # También al registro general para mantener compatibilidad
            st.session_state['registro_operaciones_en_vivo'].append({
                "Fecha": ts, "Magic": "0", "Simbolo": "ACCOUNT",
                "Tipo": "SNAPSHOT", "Beneficio": snap["ProfitFlot"], "Equity": snap["Equity"],
                "Balance": snap["Balance"], "Commission": 0, "Swap": 0, "ProfitNeto": snap["ProfitFlot"]
            })

        elif tipo == "POSITION_OPEN":
            ticket = str(query_params.get("ticket", "0"))
            st.session_state['posiciones_abiertas'][ticket] = {
                "Fecha":      ts,
                "Magic":      str(query_params.get("magic", "0")),
                "Simbolo":    str(query_params.get("symbol", "")),
                "Direccion":  str(query_params.get("direction", "")),
                "Lots":       float(query_params.get("lots", 0)),
                "PriceOpen":  float(query_params.get("price_open", 0)),
                "PriceCur":   float(query_params.get("price_cur", 0)),
                "Profit":     float(query_params.get("profit", 0)),
                "Swap":       float(query_params.get("swap", 0)),
                "SL":         float(query_params.get("sl", 0)),
                "TP":         float(query_params.get("tp", 0)),
            }

        elif tipo == "CLOSE":
            ticket = str(query_params.get("ticket", "0"))
            profit_neto = float(query_params.get("profit_net",
                          float(query_params.get("profit", 0))))
            nuevo_trade = {
                "Fecha":       ts,
                "Magic":       str(query_params.get("magic", "0")),
                "Simbolo":     str(query_params.get("symbol", "")),
                "Tipo":        "CLOSE",
                "Direccion":   str(query_params.get("direction", "")),
                "Lots":        float(query_params.get("lots", 0)),
                "Precio":      float(query_params.get("price", 0)),
                "Beneficio":   float(query_params.get("profit", 0)),
                "Commission":  float(query_params.get("commission", 0)),
                "Swap":        float(query_params.get("swap", 0)),
                "ProfitNeto":  profit_neto,
                "Equity":      float(query_params.get("equity", 0)),
                "Balance":     float(query_params.get("equity", 0)),  # approx
            }
            # Evitar duplicados por ticket
            registros = st.session_state['registro_operaciones_en_vivo']
            tickets_existentes = [r.get("Ticket","") for r in registros]
            if ticket not in tickets_existentes:
                nuevo_trade["Ticket"] = ticket
                registros.append(nuevo_trade)
            # Remover de posiciones abiertas si estaba
            st.session_state['posiciones_abiertas'].pop(ticket, None)

        else:
            # Compatibilidad con envíos legacy
            nuevo_trade = {
                "Fecha": ts, "Magic": str(query_params.get("magic","0")),
                "Simbolo": str(query_params.get("symbol","PORTFOLIO")),
                "Tipo": tipo, "Beneficio": float(query_params.get("profit",0)),
                "Equity": float(query_params.get("equity",0)),
                "Commission": 0, "Swap": 0, "ProfitNeto": float(query_params.get("profit",0))
            }
            registros = st.session_state['registro_operaciones_en_vivo']
            if not registros or registros[-1]["Equity"] != nuevo_trade["Equity"]:
                registros.append(nuevo_trade)
    except Exception as e:
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
tab1, tab2, tab3 = st.tabs(["📉 Comparador de Degradación (QA vs Real)", "⚡ Monitor de EAs en Tiempo Real", "📊 Análisis Histórico por EA"])

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

    # ── POSICIONES ABIERTAS ──────────────────────
    posiciones = st.session_state.get('posiciones_abiertas', {})
    if posiciones:
        st.write("---")
        st.subheader("🔴 Posiciones Abiertas en este Momento")
        df_pos = pd.DataFrame(list(posiciones.values()))
        if filtro_magic != "TODOS":
            df_pos = df_pos[df_pos['Magic'] == filtro_magic]
        if not df_pos.empty:
            cols_mostrar = ['Magic','Simbolo','Direccion','Lots','PriceOpen','PriceCur','Profit','Swap','SL','TP']
            cols_mostrar = [c for c in cols_mostrar if c in df_pos.columns]
            st.dataframe(df_pos[cols_mostrar], use_container_width=True)
            st.metric("💰 P&L Flotante Total", f"${df_pos['Profit'].sum():,.2f}")

    # ── TABLA DE OPERACIONES ─────────────────────
    with st.expander("📋 Ver historial de operaciones cerradas"):
        df_closed = df_filtrado[df_filtrado['Tipo']=='CLOSE'] if 'Tipo' in df_filtrado.columns else df_filtrado
        st.dataframe(df_closed.sort_values('Fecha', ascending=False).reset_index(drop=True), use_container_width=True)

# ══════════════════════════════════════════════
# TAB 3 — ANÁLISIS HISTÓRICO POR EA
# ══════════════════════════════════════════════
with tab3:
    st.subheader("📊 Análisis Histórico por EA — Reporte MT5")
    st.caption("Subí el reporte de historial de MT5 (HTML o CSV). Se desglosa automáticamente por Magic Number.")

    archivo_hist = st.file_uploader(
        "Subir historial completo de MT5 (Statement / Account History)",
        type=["csv","xlsx","html","htm"], key="hist_ea"
    )

    if archivo_hist:
        try:
            df_hist = leer_archivo_inteligente(archivo_hist)

            # Detectar columnas clave
            cols_lower = {str(c).lower().strip(): c for c in df_hist.columns}

            # Fecha
            col_fecha = None
            for k in ['close time','time','fecha','date','open time','close_time']:
                if k in cols_lower:
                    col_fecha = cols_lower[k]; break

            # Profit
            col_profit = None
            for k in ['profit','profit/loss','p/l in money','beneficio','ganancia','p/l']:
                if k in cols_lower:
                    col_profit = cols_lower[k]; break

            # Magic
            col_magic = None
            for k in ['magic','magic number','magic_number']:
                if k in cols_lower:
                    col_magic = cols_lower[k]; break

            # Symbol
            col_symbol = None
            for k in ['symbol','simbolo','instrumento','instrument']:
                if k in cols_lower:
                    col_symbol = cols_lower[k]; break

            # Commission / Swap
            col_comm = cols_lower.get('commission', cols_lower.get('comision', None))
            col_swap = cols_lower.get('swap', None)

            if col_fecha is None or col_profit is None:
                st.error("❌ No se encontraron columnas de Fecha y/o Profit. Verificá el formato del archivo.")
                st.dataframe(df_hist.head(5))
                st.stop()

            # Limpieza
            df_hist['_fecha'] = pd.to_datetime(df_hist[col_fecha], errors='coerce')
            df_hist = df_hist.dropna(subset=['_fecha'])
            df_hist['_periodo'] = df_hist['_fecha'].dt.to_period('M').astype(str)

            profit_col = df_hist[col_profit].astype(str).str.replace(r'[^\d\.\-]','',regex=True)
            df_hist['_profit'] = pd.to_numeric(profit_col, errors='coerce').fillna(0)

            if col_comm:
                df_hist['_comm'] = pd.to_numeric(
                    df_hist[col_comm].astype(str).str.replace(r'[^\d\.\-]','',regex=True),
                    errors='coerce').fillna(0)
            else:
                df_hist['_comm'] = 0

            if col_swap:
                df_hist['_swap'] = pd.to_numeric(
                    df_hist[col_swap].astype(str).str.replace(r'[^\d\.\-]','',regex=True),
                    errors='coerce').fillna(0)
            else:
                df_hist['_swap'] = 0

            df_hist['_profit_neto'] = df_hist['_profit'] + df_hist['_comm'] + df_hist['_swap']

            # Magic Number
            if col_magic:
                df_hist['_magic'] = df_hist[col_magic].astype(str).str.strip()
            else:
                # Si no hay columna magic, agrupar por symbol como fallback
                if col_symbol:
                    df_hist['_magic'] = df_hist[col_symbol].astype(str).str.strip()
                    st.warning("⚠️ No se encontró columna Magic Number. Agrupando por Symbol.")
                else:
                    df_hist['_magic'] = "CUENTA"

            # Filtrar solo trades (profit != 0)
            df_trades_hist = df_hist[df_hist['_profit'] != 0].copy()

            if df_trades_hist.empty:
                st.warning("No se encontraron trades con profit ≠ 0 en el archivo.")
                st.stop()

            magics_hist = sorted(df_trades_hist['_magic'].unique().tolist())
            periodos_hist = sorted(df_trades_hist['_periodo'].unique().tolist())

            st.success(f"✅ {len(df_trades_hist)} trades | {len(magics_hist)} EAs detectados | {len(periodos_hist)} meses")
            st.write("---")

            # ── Selector de EA ──────────────────────────
            ea_sel = st.selectbox("Seleccioná un EA para analizar",
                                  ["TODOS"] + magics_hist,
                                  format_func=lambda x: f"📊 Portfolio Completo" if x=="TODOS" else f"🤖 EA {x}")

            df_ea_sel = df_trades_hist if ea_sel == "TODOS" else df_trades_hist[df_trades_hist['_magic']==ea_sel]

            # ── Métricas globales del EA seleccionado ───
            ganancias_h = df_ea_sel[df_ea_sel['_profit'] > 0]['_profit']
            perdidas_h  = df_ea_sel[df_ea_sel['_profit'] < 0]['_profit']
            gross_p = ganancias_h.sum()
            gross_l = abs(perdidas_h.sum())
            pf_h    = round(gross_p / gross_l, 2) if gross_l > 0 else float('inf')
            wr_h    = round(len(ganancias_h) / len(df_ea_sel) * 100, 1) if len(df_ea_sel) > 0 else 0
            net_h   = df_ea_sel['_profit_neto'].sum()
            avg_w_h = round(ganancias_h.mean(), 2) if not ganancias_h.empty else 0
            avg_l_h = round(perdidas_h.mean(), 2)  if not perdidas_h.empty else 0
            exp_h   = round((wr_h/100 * avg_w_h) + ((1-wr_h/100) * avg_l_h), 2)
            total_comm_h = df_ea_sel['_comm'].sum()
            total_swap_h = df_ea_sel['_swap'].sum()

            g1,g2,g3,g4,g5 = st.columns(5)
            pf_str_h = f"{pf_h:.2f}" if pf_h != float('inf') else "∞"
            g1.metric("Profit Factor",    pf_str_h)
            g2.metric("Win Rate",         f"{wr_h:.1f}%")
            g3.metric("Net Profit",       f"${net_h:,.2f}")
            g4.metric("Expectancy",       f"${exp_h:,.2f}")
            g5.metric("Total Trades",     str(len(df_ea_sel)))

            g6,g7,g8,_,_ = st.columns(5)
            g6.metric("Avg Win",          f"${avg_w_h:,.2f}")
            g7.metric("Avg Loss",         f"${avg_l_h:,.2f}")
            g8.metric("Costos (Com+Swap)", f"${total_comm_h+total_swap_h:,.2f}")

            st.write("---")

            # ── Tabla mensual ────────────────────────────
            st.subheader("📅 Desglose Mensual")

            def metricas_mes(grp):
                g = grp[grp['_profit'] > 0]['_profit']
                l = grp[grp['_profit'] < 0]['_profit']
                pf_m = round(g.sum()/abs(l.sum()), 2) if abs(l.sum()) > 0 else float('inf')
                wr_m = round(len(g)/len(grp)*100, 1) if len(grp) > 0 else 0
                return pd.Series({
                    'Trades':      len(grp),
                    'Net Profit':  round(grp['_profit_neto'].sum(), 2),
                    'Gross Profit':round(g.sum(), 2),
                    'Gross Loss':  round(l.sum(), 2),
                    'PF':          pf_m if pf_m != float('inf') else 999,
                    'WR%':         wr_m,
                    'Avg Win':     round(g.mean(), 2) if not g.empty else 0,
                    'Avg Loss':    round(l.mean(), 2) if not l.empty else 0,
                    'Comisiones':  round(grp['_comm'].sum(), 2),
                    'Swap':        round(grp['_swap'].sum(), 2),
                })

            df_mensual = df_ea_sel.groupby('_periodo').apply(metricas_mes).reset_index()
            df_mensual.rename(columns={'_periodo':'Mes'}, inplace=True)

            # Semáforo degradación: últimos 2 meses vs promedio histórico
            if len(df_mensual) >= 3:
                pf_hist_avg = df_mensual['PF'][:-2].mean()
                wr_hist_avg = df_mensual['WR%'][:-2].mean()
                np_hist_avg = df_mensual['Net Profit'][:-2].mean()

                def semaforo_pf(val):
                    if val >= pf_hist_avg * 0.9: return '🟢'
                    if val >= pf_hist_avg * 0.7: return '🟡'
                    return '🔴'
                def semaforo_wr(val):
                    if val >= wr_hist_avg * 0.9: return '🟢'
                    if val >= wr_hist_avg * 0.7: return '🟡'
                    return '🔴'

                df_mensual['Estado PF'] = df_mensual['PF'].apply(semaforo_pf)
                df_mensual['Estado WR'] = df_mensual['WR%'].apply(semaforo_wr)

                st.caption(f"Semáforo basado en promedio histórico — PF ref: {pf_hist_avg:.2f} | WR ref: {wr_hist_avg:.1f}%")

            st.dataframe(df_mensual, use_container_width=True, hide_index=True)

            # ── Gráfico mensual ──────────────────────────
            st.write("---")
            st.subheader("📈 Equity Acumulada & Profit Mensual")

            fig3 = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                 row_heights=[0.6, 0.4], vertical_spacing=0.06,
                                 subplot_titles=("Equity Acumulada", "Profit Neto Mensual"))

            equity_acum = df_mensual['Net Profit'].cumsum()
            fig3.add_trace(go.Scatter(
                x=df_mensual['Mes'], y=equity_acum,
                name="Equity Acum.", line=dict(color='#00d4ff', width=2),
                fill='tozeroy', fillcolor='rgba(0,212,255,0.08)'
            ), row=1, col=1)

            colores_bars = ['#2ecc71' if v >= 0 else '#e74c3c' for v in df_mensual['Net Profit']]
            fig3.add_trace(go.Bar(
                x=df_mensual['Mes'], y=df_mensual['Net Profit'],
                name="Profit Mensual", marker_color=colores_bars
            ), row=2, col=1)

            fig3.add_hline(y=0, line_dash="dot", line_color="#666", row=2, col=1)
            fig3.update_layout(template="plotly_dark", height=480,
                               margin=dict(t=30,b=20), showlegend=False)
            st.plotly_chart(fig3, use_container_width=True)

            # ── Comparador entre EAs ─────────────────────
            if ea_sel == "TODOS" and len(magics_hist) > 1:
                st.write("---")
                st.subheader("🔬 Ranking de EAs por Profit Factor")

                resumen_eas = []
                for mg in magics_hist:
                    d = df_trades_hist[df_trades_hist['_magic']==mg]
                    g = d[d['_profit']>0]['_profit']
                    l = d[d['_profit']<0]['_profit']
                    pf_ea = round(g.sum()/abs(l.sum()),2) if abs(l.sum())>0 else 999
                    resumen_eas.append({
                        'EA (Magic)':   mg,
                        'Trades':       len(d),
                        'Net Profit':   round(d['_profit_neto'].sum(), 2),
                        'PF':           pf_ea,
                        'WR%':          round(len(g)/len(d)*100,1) if len(d)>0 else 0,
                        'Avg Win':      round(g.mean(),2) if not g.empty else 0,
                        'Avg Loss':     round(l.mean(),2) if not l.empty else 0,
                        'Costos':       round(d['_comm'].sum()+d['_swap'].sum(),2),
                    })
                df_rank = pd.DataFrame(resumen_eas).sort_values('PF', ascending=False).reset_index(drop=True)

                # Barras de PF por EA
                fig_rank = go.Figure(go.Bar(
                    x=df_rank['EA (Magic)'].astype(str),
                    y=df_rank['PF'],
                    marker_color=['#2ecc71' if v>=1.5 else '#f39c12' if v>=1.2 else '#e74c3c'
                                  for v in df_rank['PF']],
                    text=df_rank['PF'].apply(lambda x: f"{x:.2f}"),
                    textposition='outside'
                ))
                fig_rank.add_hline(y=1.5, line_dash="dash", line_color="#2ecc71",
                                   annotation_text="PF 1.5 objetivo")
                fig_rank.add_hline(y=1.2, line_dash="dash", line_color="#f39c12",
                                   annotation_text="PF 1.2 mínimo")
                fig_rank.update_layout(template="plotly_dark", height=320,
                                       xaxis_title="EA", yaxis_title="Profit Factor",
                                       margin=dict(t=20,b=20))
                st.plotly_chart(fig_rank, use_container_width=True)
                st.dataframe(df_rank, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"❌ Error procesando historial: {e}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.info("💡 Exportá el historial desde MT5: Account History → click derecho → Save as Report (HTML) o Save as Detailed Report (CSV)")
        st.markdown("""
        **Cómo exportar desde MT5:**
        1. `View → Terminal → Account History`
        2. Seleccioná el período completo (click derecho → All History)
        3. Click derecho → **Save as Detailed Report** → guardá como HTML
        4. Subí ese archivo aquí
        """)
