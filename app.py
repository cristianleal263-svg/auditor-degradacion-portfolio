import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import re
import math
import urllib.request
import urllib.parse
import json
from datetime import datetime

# ─────────────────────────────────────────────
# SUPABASE — capa de persistencia
# ─────────────────────────────────────────────
SUPABASE_URL = "https://iikykbyrospnzrsqcjfp.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlpa3lrYnlyb3Nwbnpyc3FjamZwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA4NDU2MjgsImV4cCI6MjA5NjQyMTYyOH0.xDCw6xC-xo2Tm4B7H6au0lcyrtK6MIklJ35s1zhgMlE"

HEADERS_SB = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal"
}

def sb_insert(tabla: str, datos: dict) -> bool:
    """Inserta un registro en Supabase via REST. Retorna True si OK."""
    try:
        url  = f"{SUPABASE_URL}/rest/v1/{tabla}"
        body = json.dumps(datos).encode()
        req  = urllib.request.Request(url, data=body, headers=HEADERS_SB, method="POST")
        urllib.request.urlopen(req, timeout=4)
        return True
    except Exception:
        return False

def sb_upsert(tabla: str, datos: dict) -> bool:
    """Upsert (insert o update) por primary key."""
    try:
        headers = {**HEADERS_SB, "Prefer": "resolution=merge-duplicates"}
        url  = f"{SUPABASE_URL}/rest/v1/{tabla}"
        body = json.dumps(datos).encode()
        req  = urllib.request.Request(url, data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=4)
        return True
    except Exception:
        return False

def sb_select(tabla: str, filtros: str = "", limite: int = 1000) -> list:
    """Lee registros de Supabase. filtros ej: 'account=eq.DarwinexZero_1'"""
    try:
        params = f"?limit={limite}&order=ts.desc"
        if filtros:
            params += f"&{filtros}"
        url = f"{SUPABASE_URL}/rest/v1/{tabla}{params}"
        req = urllib.request.Request(url, headers={**HEADERS_SB, "Prefer": "return=representation"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return []

def sb_delete_old_snapshots(cuenta: str, keep: int = 2000):
    """Borra snapshots viejos para no llenar la DB gratuita."""
    try:
        url = (f"{SUPABASE_URL}/rest/v1/snapshots"
               f"?account=eq.{urllib.parse.quote(cuenta)}"
               f"&id=lt.(select id from snapshots where account=eq.{urllib.parse.quote(cuenta)}"
               f" order by ts desc limit 1 offset {keep})")
        req = urllib.request.Request(url, headers=HEADERS_SB, method="DELETE")
        urllib.request.urlopen(req, timeout=4)
    except Exception:
        pass

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
if 'cuentas' not in st.session_state:
    # dict: account_name → {snapshots:[], trades:[], posiciones:{}, tipo:""}
    st.session_state['cuentas'] = {}
if 'sqx_benchmarks' not in st.session_state:
    # dict: "magic|account" → {pf, wr, expectancy, avg_win, avg_loss, trades, net_profit, nombre}
    st.session_state['sqx_benchmarks'] = {}
if 'magic_nombres' not in st.session_state:
    # dict: magic_str → nombre_ea (auto-construido desde comentarios MT5 + editable)
    st.session_state['magic_nombres'] = {}
if 'dz_config' not in st.session_state:
    st.session_state['dz_config'] = {
        "capital_inicial": 100000.0,
        "dd_max_pct":      10.0,
        "dd_diario_pct":   5.0,
        "alerta_margen":   3000.0,
    }
if 'telegram_config' not in st.session_state:
    st.session_state['telegram_config'] = {"token": "", "chat_id": "", "activo": False}
if 'alertas_enviadas' not in st.session_state:
    st.session_state['alertas_enviadas'] = set()
if 'sb_cargado' not in st.session_state:
    st.session_state['sb_cargado'] = False

# ── Recuperar datos de Supabase al arrancar ──────────────────────
if not st.session_state['sb_cargado']:
    try:
        # Trades cerrados → reconstruir registro_operaciones_en_vivo y cuentas
        trades_db = sb_select("trades", limite=5000)
        for t in trades_db:
            reg = {
                "Fecha":      t.get("ts",""),
                "Magic":      str(t.get("magic","0")),
                "Simbolo":    t.get("symbol",""),
                "Tipo":       "CLOSE",
                "Direccion":  t.get("direction",""),
                "Lots":       t.get("lots",0),
                "Precio":     t.get("precio",0),
                "Beneficio":  t.get("profit",0),
                "Commission": t.get("commission",0),
                "Swap":       t.get("swap",0),
                "ProfitNeto": t.get("profit_neto",0),
                "Equity":     t.get("equity",0),
                "Balance":    t.get("equity",0),
                "Account":    t.get("account","default"),
                "AccType":    t.get("acc_type",""),
                "Ticket":     str(t.get("ticket","")),
            }
            acc = reg["Account"]
            if acc not in st.session_state['cuentas']:
                st.session_state['cuentas'][acc] = {"tipo": reg["AccType"], "snapshots":[], "trades":[], "posiciones":{}}
            tickets_ex = [r.get("Ticket","") for r in st.session_state['registro_operaciones_en_vivo']]
            if reg["Ticket"] not in tickets_ex:
                st.session_state['registro_operaciones_en_vivo'].append(reg)
                st.session_state['cuentas'][acc]["trades"].append(reg)

        # Snapshots recientes → últimos 500 por cuenta
        snaps_db = sb_select("snapshots", limite=500)
        for s in snaps_db:
            acc = s.get("account","default")
            snap = {
                "Fecha":      s.get("ts",""),
                "Equity":     s.get("equity",0),
                "Balance":    s.get("balance",0),
                "Margin":     s.get("margin",0),
                "FreeMargin": s.get("free_margin",0),
                "ProfitFlot": s.get("profit_flot",0),
                "DD_Equity":  s.get("dd_equity",0),
                "DD_Balance": s.get("dd_balance",0),
            }
            if acc not in st.session_state['cuentas']:
                st.session_state['cuentas'][acc] = {"tipo": s.get("acc_type",""), "snapshots":[], "trades":[], "posiciones":{}}
            st.session_state['cuentas'][acc]["snapshots"].append(snap)
            st.session_state['snapshots'].append(snap)

        # Posiciones abiertas
        pos_db = sb_select("posiciones", limite=200)
        for p in pos_db:
            ticket = str(p.get("ticket",""))
            pos = {
                "Fecha":     p.get("ts",""),
                "Magic":     str(p.get("magic","0")),
                "Simbolo":   p.get("symbol",""),
                "Direccion": p.get("direction",""),
                "Lots":      p.get("lots",0),
                "PriceOpen": p.get("price_open",0),
                "PriceCur":  p.get("price_cur",0),
                "Profit":    p.get("profit",0),
                "Swap":      p.get("swap",0),
                "SL":        p.get("sl",0),
                "TP":        p.get("tp",0),
                "Account":   p.get("account",""),
            }
            st.session_state['posiciones_abiertas'][ticket] = pos

        st.session_state['sb_cargado'] = True
    except Exception:
        pass  # Si Supabase falla, la app sigue funcionando con session_state

# ─────────────────────────────────────────────
# WEBHOOK RECEPTOR
# ─────────────────────────────────────────────
query_params = st.query_params
if "action" in query_params and query_params["action"] == "webhook_mt5":
    try:
        tipo       = str(query_params.get("type", "LIVE"))
        ts         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        acc_name   = str(query_params.get("account", "default"))
        acc_type   = str(query_params.get("acc_type", "DESCONOCIDO"))

        # Inicializar estructura de cuenta si es nueva
        cuentas = st.session_state['cuentas']
        if acc_name not in cuentas:
            cuentas[acc_name] = {
                "tipo": acc_type,
                "snapshots": [],
                "trades": [],
                "posiciones": {}
            }
        cuenta = cuentas[acc_name]

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
            # Registro general (compatibilidad Tab2) + multi-cuenta
            reg = {"Fecha": ts, "Magic": "0", "Simbolo": "ACCOUNT",
                   "Tipo": "SNAPSHOT", "Beneficio": snap["ProfitFlot"], "Equity": snap["Equity"],
                   "Balance": snap["Balance"], "Commission": 0, "Swap": 0,
                   "ProfitNeto": snap["ProfitFlot"], "Account": acc_name}
            st.session_state['registro_operaciones_en_vivo'].append(reg)
            if not cuenta["snapshots"] or cuenta["snapshots"][-1]["Equity"] != snap["Equity"]:
                cuenta["snapshots"].append(snap)
                # ── Persistir snapshot en Supabase ──
                sb_insert("snapshots", {
                    "account":     acc_name,
                    "acc_type":    acc_type,
                    "equity":      snap["Equity"],
                    "balance":     snap["Balance"],
                    "margin":      snap["Margin"],
                    "free_margin": snap["FreeMargin"],
                    "profit_flot": snap["ProfitFlot"],
                    "dd_equity":   snap["DD_Equity"],
                    "dd_balance":  snap["DD_Balance"],
                })
            verificar_alertas_dd(cuenta["snapshots"], acc_name)

        elif tipo == "POSITION_OPEN":
            ticket = str(query_params.get("ticket", "0"))
            pos_data = {
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
                "Account":    acc_name,
            }
            st.session_state['posiciones_abiertas'][ticket] = pos_data
            cuenta["posiciones"][ticket] = pos_data
            # ── Persistir posición en Supabase ──
            sb_upsert("posiciones", {
                "ticket":     ticket,
                "account":    acc_name,
                "magic":      pos_data["Magic"],
                "symbol":     pos_data["Simbolo"],
                "direction":  pos_data["Direccion"],
                "lots":       pos_data["Lots"],
                "price_open": pos_data["PriceOpen"],
                "price_cur":  pos_data["PriceCur"],
                "profit":     pos_data["Profit"],
                "swap":       pos_data["Swap"],
                "sl":         pos_data["SL"],
                "tp":         pos_data["TP"],
                "equity":     float(query_params.get("equity", 0)),
            })

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
                "Balance":     float(query_params.get("equity", 0)),
                "Account":     acc_name,
                "AccType":     acc_type,
            }
            registros = st.session_state['registro_operaciones_en_vivo']
            tickets_existentes = [r.get("Ticket","") for r in registros]
            if ticket not in tickets_existentes:
                nuevo_trade["Ticket"] = ticket
                registros.append(nuevo_trade)
                cuenta["trades"].append(nuevo_trade)
                # ── Persistir en Supabase ──
                sb_upsert("trades", {
                    "ticket":      ticket,
                    "account":     acc_name,
                    "acc_type":    acc_type,
                    "magic":       nuevo_trade["Magic"],
                    "symbol":      nuevo_trade["Simbolo"],
                    "direction":   nuevo_trade["Direccion"],
                    "lots":        nuevo_trade["Lots"],
                    "precio":      nuevo_trade["Precio"],
                    "profit":      nuevo_trade["Beneficio"],
                    "commission":  nuevo_trade["Commission"],
                    "swap":        nuevo_trade["Swap"],
                    "profit_neto": profit_neto,
                    "equity":      nuevo_trade["Equity"],
                    "close_time":  int(query_params.get("close_time", 0)),
                })
            # Borrar de posiciones en Supabase
            try:
                url_del = f"{SUPABASE_URL}/rest/v1/posiciones?ticket=eq.{ticket}"
                req_del = urllib.request.Request(url_del, headers=HEADERS_SB, method="DELETE")
                urllib.request.urlopen(req_del, timeout=3)
            except Exception:
                pass
            st.session_state['posiciones_abiertas'].pop(ticket, None)
            cuenta["posiciones"].pop(ticket, None)
            cuenta["tipo"] = acc_type

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
# TELEGRAM
# ─────────────────────────────────────────────
def enviar_telegram(mensaje: str) -> bool:
    cfg = st.session_state.get('telegram_config', {})
    token   = cfg.get("token", "")
    chat_id = cfg.get("chat_id", "")
    if not token or not chat_id:
        return False
    try:
        import urllib.request, urllib.parse
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}).encode()
        req  = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False

def verificar_alertas_dd(snapshots: list, cuenta: str):
    """Envía alerta Telegram si DD supera umbrales — una sola vez por evento."""
    if not snapshots: return
    cfg = st.session_state.get('telegram_config', {})
    if not cfg.get("activo"): return
    ultimo = snapshots[-1]
    dd = ultimo.get("DD_Equity", 0)
    alertas = st.session_state['alertas_enviadas']
    for umbral, emoji in [(5.0, "🚨"), (3.0, "⚠️")]:
        clave = f"{cuenta}_dd{umbral}"
        if dd >= umbral and clave not in alertas:
            msg = (f"{emoji} *ALERTA DD — {cuenta}*\n"
                   f"DD actual: `{dd:.2f}%`\n"
                   f"Equity: `${ultimo.get('Equity',0):,.2f}`\n"
                   f"Balance: `${ultimo.get('Balance',0):,.2f}`")
            if enviar_telegram(msg):
                alertas.add(clave)
        elif dd < umbral * 0.5:  # Reset alerta cuando se recupera
            alertas.discard(clave)

# ─────────────────────────────────────────────
# COMPARADOR SQX — funciones auxiliares
# ─────────────────────────────────────────────
def parsear_sqx_html(contenido_bytes) -> dict:
    """Extrae métricas clave de un reporte HTML de SQX / Quant Analyzer."""
    try:
        tablas = pd.read_html(io.BytesIO(contenido_bytes))
    except Exception:
        return {}
    profits = []
    for t in tablas:
        t.columns = t.columns.astype(str).str.lower().str.strip()
        for col in t.columns:
            if any(k in col for k in ['profit','p/l','ganancia','beneficio']):
                vals = pd.to_numeric(
                    t[col].astype(str).str.replace(r'[^\d\.\-]','',regex=True),
                    errors='coerce').dropna()
                if len(vals) > 5:
                    profits.extend(vals.tolist())
                    break
    if not profits:
        return {}
    s = pd.Series(profits)
    g = s[s > 0]; l = s[s < 0]
    pf  = round(g.sum()/abs(l.sum()), 2) if abs(l.sum()) > 0 else float('inf')
    wr  = round(len(g)/len(s)*100, 1)
    exp = round((wr/100 * g.mean() if not g.empty else 0) +
                ((1-wr/100) * l.mean() if not l.empty else 0), 2)
    return {
        "pf":        pf,
        "wr":        wr,
        "expectancy": exp,
        "avg_win":   round(g.mean(), 2) if not g.empty else 0,
        "avg_loss":  round(l.mean(), 2) if not l.empty else 0,
        "trades":    len(s),
        "net_profit": round(s.sum(), 2),
    }

def delta_semaforo(live_val, sqx_val, mayor_es_mejor=True):
    """Retorna (delta_str, color_emoji) comparando live vs SQX."""
    if sqx_val == 0:
        return "N/A", "⚪"
    ratio = live_val / sqx_val if sqx_val != 0 else 1
    delta = live_val - sqx_val
    delta_str = f"{delta:+.2f} ({ratio*100:.0f}% del backtest)"
    if mayor_es_mejor:
        emoji = "🟢" if ratio >= 0.85 else "🟡" if ratio >= 0.65 else "🔴"
    else:
        emoji = "🟢" if ratio <= 1.15 else "🟡" if ratio <= 1.35 else "🔴"
    return delta_str, emoji

# ─────────────────────────────────────────────
# LAYOUT PRINCIPAL
# ─────────────────────────────────────────────
st.title("🦁 Centro de Control de Portfolio — Darwinex Zero")
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📉 Comparador de Degradación (QA vs Real)",
    "⚡ Monitor de EAs en Tiempo Real",
    "📊 Análisis Histórico por EA",
    "🌐 Multi-Cuenta",
    "🔬 SQX vs Live + Alertas"
])

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
    _registros = st.session_state['registro_operaciones_en_vivo']
    if not _registros:
        st.info("⏳ Esperando datos desde MT5... El EA enviará métricas cada 10 segundos vía OnTimer().")
    if _registros:
        # ── DataFrame principal ──────────────────────
        df_vivo = pd.DataFrame(_registros)
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
    st.subheader("🔬 Análisis Cuantitativo por EA — Reporte MT5 (Deals)")
    st.caption("Exportá desde MT5 → History → Report → Open XML. La app detecta la sección **Deals** y clasifica cada operación por EA usando el campo Comment.")

    archivo_hist = st.file_uploader(
        "Subir reporte MT5 (xlsx con sección Deals)",
        type=["xlsx","xls"], key="hist_ea"
    )

    if archivo_hist:
        try:
            contenido = archivo_hist.read()

            # ── Detectar fila header de Deals ──────────────────────────
            df_raw = pd.read_excel(io.BytesIO(contenido), header=None)
            deals_row = None
            for i, row in df_raw.iterrows():
                vals = [str(v).strip().lower() for v in row.tolist()]
                if 'deal' in vals and 'symbol' in vals and 'profit' in vals and 'comment' in vals:
                    deals_row = i
                    break

            if deals_row is None:
                st.error("❌ No se encontró la sección Deals. Asegurate de exportar con Report → Open XML.")
                st.stop()

            # ── Leer sección Deals ──────────────────────────────────────
            df_deals = pd.read_excel(io.BytesIO(contenido), header=deals_row)
            df_deals = df_deals[pd.to_numeric(df_deals['Deal'], errors='coerce').notna()].copy()
            df_deals['Profit']     = pd.to_numeric(df_deals['Profit'],     errors='coerce').fillna(0)
            df_deals['Commission'] = pd.to_numeric(df_deals['Commission'], errors='coerce').fillna(0)
            df_deals['Swap']       = pd.to_numeric(df_deals['Swap'],       errors='coerce').fillna(0)
            df_deals['Time']       = pd.to_datetime(df_deals['Time'],      errors='coerce')
            df_deals['ProfitNeto'] = df_deals['Profit'] + df_deals['Commission'] + df_deals['Swap']
            df_deals['Mes']        = df_deals['Time'].dt.to_period('M').astype(str)

            # Solo cierres con profit
            df_close = df_deals[
                (df_deals['Direction'] == 'out') & (df_deals['Profit'] != 0)
            ].copy()

            if df_close.empty:
                st.warning("Sin trades cerrados encontrados en la sección Deals.")
                st.stop()

            # ── Extraer nombre EA desde Comment ────────────────────────
            def extraer_ea(row):
                c = str(row.get('Comment', '')).strip()
                sym = str(row.get('Symbol', '')).strip()
                if not c or c in ['nan','First deposit','balance'] or c.startswith('['):
                    return f"Manual_{sym}" if sym else "Sin_EA"
                # Quitar sufijos numéricos _XX_YYY al final
                c = re.sub(r'_\d+_\d+$', '', c)
                c = re.sub(r'_\d+$', '', c)
                return c.strip('_').strip()

            df_close['EA'] = df_close.apply(extraer_ea, axis=1)

            eas_detectados = [e for e in sorted(df_close['EA'].unique()) if e != 'Sin_EA']
            meses = sorted(df_close['Mes'].unique())

            st.success(f"✅ {len(df_close)} trades cerrados | {len(eas_detectados)} EAs identificados | {len(meses)} meses")

            # ── MÉTRICAS GLOBALES ───────────────────────────────────────
            st.write("---")
            st.subheader("📊 Performance Global del Portfolio")
            g_all = df_close[df_close['Profit']>0]; l_all = df_close[df_close['Profit']<0]
            pf_all = round(g_all['Profit'].sum()/abs(l_all['Profit'].sum()),2) if abs(l_all['Profit'].sum())>0 else 999
            wr_all = round(len(g_all)/len(df_close)*100,1)
            net_all = df_close['ProfitNeto'].sum()
            comm_all = df_close['Commission'].sum()
            exp_all = round((wr_all/100*g_all['Profit'].mean() if not g_all.empty else 0) +
                           ((1-wr_all/100)*l_all['Profit'].mean() if not l_all.empty else 0), 2)

            c1,c2,c3,c4,c5,c6 = st.columns(6)
            c1.metric("Net Profit",    f"${net_all:,.2f}")
            c2.metric("Profit Factor", f"{pf_all:.2f}", help="≥1.5 excelente | ≥1.2 aceptable")
            c3.metric("Win Rate",      f"{wr_all:.1f}%")
            c4.metric("Expectancy",    f"${exp_all:.2f}")
            c5.metric("Total Trades",  str(len(df_close)))
            c6.metric("Comisiones",    f"${comm_all:,.2f}")

            # ── RANKING DE EAs ─────────────────────────────────────────
            st.write("---")
            st.subheader("🏆 Ranking de EAs por Performance")

            rows_rank = []
            for ea in sorted(df_close['EA'].unique()):
                d = df_close[df_close['EA']==ea]
                g = d[d['Profit']>0]; l = d[d['Profit']<0]
                pf  = round(g['Profit'].sum()/abs(l['Profit'].sum()),2) if abs(l['Profit'].sum())>0 else 999
                wr  = round(len(g)/len(d)*100,1) if len(d)>0 else 0
                net = round(d['ProfitNeto'].sum(),2)
                avg_w = round(g['Profit'].mean(),2) if not g.empty else 0
                avg_l = round(l['Profit'].mean(),2) if not l.empty else 0
                exp = round((wr/100*avg_w)+((1-wr/100)*avg_l),2)
                comm_ea = round(d['Commission'].sum(),2)
                # DD máximo de la equity de este EA
                eq_ea = d.sort_values('Time')['ProfitNeto'].cumsum()
                peak_ea = eq_ea.cummax()
                max_dd = round((eq_ea - peak_ea).min(), 2)
                # Semáforo
                sem = "🟢" if pf>=1.5 and wr>=55 else "🟡" if pf>=1.2 else "🔴"
                rows_rank.append({
                    "Estado": sem, "EA": ea, "Trades": len(d),
                    "Net Profit": f"${net:,.2f}",
                    "PF": f"{pf:.2f}", "WR%": f"{wr:.1f}%",
                    "Avg Win": f"${avg_w:.2f}", "Avg Loss": f"${avg_l:.2f}",
                    "Expectancy": f"${exp:.2f}",
                    "Max DD": f"${max_dd:,.2f}",
                    "Comisiones": f"${comm_ea:,.2f}",
                })

            df_rank = pd.DataFrame(rows_rank).sort_values("Net Profit", ascending=False)
            st.dataframe(df_rank, use_container_width=True, hide_index=True)

            # Gráfico barras PF por EA
            pf_vals = [float(r["PF"]) for r in rows_rank]
            ea_names = [r["EA"] for r in rows_rank]
            fig_rank = go.Figure(go.Bar(
                x=ea_names, y=pf_vals,
                marker_color=["#2ecc71" if v>=1.5 else "#f39c12" if v>=1.2 else "#e74c3c" for v in pf_vals],
                text=[f"{v:.2f}" for v in pf_vals], textposition='outside'
            ))
            fig_rank.add_hline(y=1.5, line_dash="dash", line_color="#2ecc71", annotation_text="1.5 objetivo")
            fig_rank.add_hline(y=1.2, line_dash="dash", line_color="#f39c12", annotation_text="1.2 mínimo")
            fig_rank.update_layout(template="plotly_dark", height=320,
                                   xaxis_title="EA", yaxis_title="Profit Factor",
                                   margin=dict(t=20,b=20))
            st.plotly_chart(fig_rank, use_container_width=True)

            # ── TABLA MENSUAL POR EA (PIVOT) ────────────────────────────
            st.write("---")
            st.subheader("📅 Profit Mensual por EA — Heatmap")
            pivot = df_close.groupby(['Mes','EA'])['ProfitNeto'].sum().unstack(fill_value=0)

            # Agregar totales
            pivot['TOTAL'] = pivot.sum(axis=1)
            pivot.loc['TOTAL'] = pivot.sum()

            # Colorear con semáforo
            def estilo_pivot(val):
                if isinstance(val, (int,float)):
                    if val > 200:   return 'background-color: #1a4a1a; color: #2ecc71'
                    if val > 0:     return 'background-color: #0d2b0d; color: #88cc88'
                    if val < -200:  return 'background-color: #4a0000; color: #e74c3c'
                    if val < 0:     return 'background-color: #2b0d0d; color: #cc8888'
                return ''

            pivot_fmt = pivot.round(2)
            st.dataframe(
                pivot_fmt.style.applymap(estilo_pivot),
                use_container_width=True
            )

            # ── ANÁLISIS INDIVIDUAL POR EA ──────────────────────────────
            st.write("---")
            st.subheader("🔍 Análisis Individual por EA")

            ea_sel = st.selectbox("Seleccioná un EA",
                                  ["TODOS"] + sorted(df_close['EA'].unique().tolist()),
                                  format_func=lambda x: "📊 Portfolio Completo" if x=="TODOS" else f"🤖 {x}")

            df_ea_sel = df_close if ea_sel=="TODOS" else df_close[df_close['EA']==ea_sel]

            # Equity acumulada
            df_ea_plot = df_ea_sel.sort_values('Time').copy()
            df_ea_plot['EquityAcum'] = df_ea_plot['ProfitNeto'].cumsum()
            peak = df_ea_plot['EquityAcum'].cummax()
            df_ea_plot['DD_pct'] = (df_ea_plot['EquityAcum'] - peak) / peak.replace(0,1) * 100

            fig_ea = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                   row_heights=[0.65,0.35], vertical_spacing=0.06,
                                   subplot_titles=("Equity Acumulada", "Drawdown %"))
            fig_ea.add_trace(go.Scatter(
                x=df_ea_plot['Time'], y=df_ea_plot['EquityAcum'],
                name="Equity", line=dict(color='#00d4ff', width=2),
                fill='tozeroy', fillcolor='rgba(0,212,255,0.08)'
            ), row=1, col=1)
            fig_ea.add_trace(go.Scatter(
                x=df_ea_plot['Time'], y=df_ea_plot['DD_pct'],
                name="DD%", line=dict(color='#e74c3c', width=1.5),
                fill='tozeroy', fillcolor='rgba(231,76,60,0.1)'
            ), row=2, col=1)
            fig_ea.add_hline(y=0,   line_dash="dot", line_color="#444", row=1, col=1)
            fig_ea.add_hline(y=-10, line_dash="dash", line_color="#e74c3c",
                             annotation_text="-10% límite DZ", row=2, col=1)
            fig_ea.update_layout(template="plotly_dark", height=480,
                                 margin=dict(t=30,b=10), showlegend=False)
            st.plotly_chart(fig_ea, use_container_width=True)

            # Distribución de profits
            fig_dist = go.Figure()
            fig_dist.add_trace(go.Histogram(
                x=df_ea_sel['Profit'],
                nbinsx=40,
                marker_color='#00d4ff',
                opacity=0.7,
                name="Distribución de P&L"
            ))
            fig_dist.add_vline(x=0, line_dash="dash", line_color="white")
            fig_dist.add_vline(x=df_ea_sel['Profit'].mean(),
                               line_dash="dot", line_color="#f39c12",
                               annotation_text=f"Media ${df_ea_sel['Profit'].mean():.2f}")
            fig_dist.update_layout(template="plotly_dark", height=280,
                                   xaxis_title="Profit por Trade ($)",
                                   yaxis_title="Frecuencia",
                                   margin=dict(t=20,b=20))
            st.plotly_chart(fig_dist, use_container_width=True)

            # Tabla de trades del EA seleccionado
            with st.expander("📋 Ver todos los trades"):
                cols_show = ['Time','Symbol','Type','Direction','Volume','Price','Commission','Swap','Profit','ProfitNeto','EA','Comment']
                cols_show = [c for c in cols_show if c in df_ea_sel.columns]
                st.dataframe(df_ea_sel[cols_show].sort_values('Time', ascending=False).reset_index(drop=True),
                             use_container_width=True)

        except Exception as e:
            import traceback
            st.error(f"❌ Error: {e}")
            st.code(traceback.format_exc())
    else:
        st.info("💡 Exportá desde MT5 → History → click derecho → **Report → Open XML (MS Office Excel 2007)**")
        st.markdown("""
        **Pasos exactos:**
        1. MT5 → pestaña **History** (abajo)
        2. Click derecho en la tabla
        3. **Report → Open XML (MS Office Excel 2007)**
        4. Guardá el archivo y subilo acá
        """)


with tab4:
    st.subheader("🌐 Dashboard Multi-Cuenta — Todas las Instancias MT5")

    TIPOS_COLOR = {
        "DARWINEX_ZERO": "#00d4ff",
        "PROP_FIRM":     "#f39c12",
        "REAL":          "#2ecc71",
        "DEMO":          "#888888",
        "DESCONOCIDO":   "#aaaaaa",
    }

    cuentas = st.session_state.get('cuentas', {})

    if not cuentas:
        st.info("⏳ Sin datos multi-cuenta. Cada EA debe tener `ACCOUNT_NAME` único configurado en sus inputs.")
        st.markdown("""
        **Configuración en cada instancia MT5:**
        - `ACCOUNT_NAME = "DarwinexZero_1"` → cuenta Darwinex Zero principal
        - `ACCOUNT_NAME = "FTMO_Challenge"` → prop firm challenge
        - `ACCOUNT_NAME = "Real_ICMarkets"` → cuenta real propia
        - `ACCOUNT_TYPE = "DARWINEX_ZERO"` / `"PROP_FIRM"` / `"REAL"` / `"DEMO"`

        Todas envían a la **misma URL** — la app las separa automáticamente.
        """)
    else:
        # ── Resumen de todas las cuentas ─────────────
        st.markdown(f"**{len(cuentas)} cuenta(s) activa(s)**")

        cols_cuentas = st.columns(min(len(cuentas), 4))
        for idx, (nombre, data) in enumerate(cuentas.items()):
            tipo  = data.get("tipo", "DESCONOCIDO")
            color = TIPOS_COLOR.get(tipo, "#aaaaaa")
            snaps = data.get("snapshots", [])
            trades = data.get("trades", [])

            equity_act  = snaps[-1]["Equity"]   if snaps else 0
            balance_act = snaps[-1]["Balance"]  if snaps else 0
            dd_act      = snaps[-1]["DD_Equity"] if snaps else 0
            net_profit  = sum(t["ProfitNeto"] for t in trades)

            with cols_cuentas[idx % 4]:
                st.markdown(f"""
                <div style="border:1px solid {color}; border-radius:8px; padding:12px; margin:4px 0;">
                    <div style="color:{color}; font-weight:700; font-size:14px;">
                        {nombre}
                    </div>
                    <div style="color:#aaa; font-size:11px; margin-bottom:8px;">{tipo}</div>
                    <div style="font-size:18px; font-weight:700;">${equity_act:,.2f}</div>
                    <div style="font-size:12px; color:#aaa;">Balance: ${balance_act:,.2f}</div>
                    <div style="font-size:12px; color:{'#e74c3c' if dd_act>3 else '#2ecc71'};">
                        DD: {dd_act:.2f}%
                    </div>
                    <div style="font-size:12px;">Net P&L trades: ${net_profit:,.2f}</div>
                    <div style="font-size:11px; color:#888;">{len(trades)} trades | {len(snaps)} snapshots</div>
                </div>
                """, unsafe_allow_html=True)

        st.write("---")

        # ── Equity de todas las cuentas en un gráfico ─
        st.subheader("📈 Equity Comparada — Todas las Cuentas")
        fig_multi = go.Figure()
        for nombre, data in cuentas.items():
            snaps = data.get("snapshots", [])
            if not snaps: continue
            tipo  = data.get("tipo", "DESCONOCIDO")
            color = TIPOS_COLOR.get(tipo, "#aaaaaa")
            df_s  = pd.DataFrame(snaps)
            df_s['Fecha'] = pd.to_datetime(df_s['Fecha'])
            fig_multi.add_trace(go.Scatter(
                x=df_s['Fecha'], y=df_s['Equity'],
                name=f"{nombre} ({tipo})",
                line=dict(color=color, width=2),
                mode='lines'
            ))
        fig_multi.update_layout(
            template="plotly_dark", height=380,
            xaxis_title="Tiempo", yaxis_title="Equity ($)",
            margin=dict(t=20, b=20), legend=dict(orientation="h", y=-0.2)
        )
        st.plotly_chart(fig_multi, use_container_width=True)

        # ── DD comparado ─────────────────────────────
        st.subheader("📉 Drawdown Comparado")
        fig_dd = go.Figure()
        for nombre, data in cuentas.items():
            snaps = data.get("snapshots", [])
            if not snaps: continue
            tipo  = data.get("tipo", "DESCONOCIDO")
            color = TIPOS_COLOR.get(tipo, "#aaaaaa")
            df_s  = pd.DataFrame(snaps)
            df_s['Fecha'] = pd.to_datetime(df_s['Fecha'])
            fig_dd.add_trace(go.Scatter(
                x=df_s['Fecha'], y=df_s['DD_Equity'],
                name=nombre, line=dict(color=color, width=1.5),
                fill='tozeroy', fillcolor='rgba(128,128,128,0.05)'
            ))
        fig_dd.add_hline(y=3.0, line_dash="dash", line_color="orange", annotation_text="3% alerta")
        fig_dd.add_hline(y=5.0, line_dash="dash", line_color="red",    annotation_text="5% límite")
        fig_dd.update_layout(template="plotly_dark", height=300,
                             yaxis_title="DD%", margin=dict(t=20,b=20))
        st.plotly_chart(fig_dd, use_container_width=True)

        # ── Tabla resumen ─────────────────────────────
        st.write("---")
        st.subheader("📋 Tabla Resumen")
        resumen_rows = []
        for nombre, data in cuentas.items():
            snaps  = data.get("snapshots", [])
            trades = data.get("trades", [])
            posiciones = data.get("posiciones", {})
            equity_act  = snaps[-1]["Equity"]    if snaps else 0
            balance_act = snaps[-1]["Balance"]   if snaps else 0
            dd_act      = snaps[-1]["DD_Equity"] if snaps else 0
            net_p = sum(t["ProfitNeto"] for t in trades)
            ganancias = [t["ProfitNeto"] for t in trades if t["ProfitNeto"] > 0]
            perdidas  = [t["ProfitNeto"] for t in trades if t["ProfitNeto"] < 0]
            pf_r = round(sum(ganancias)/abs(sum(perdidas)),2) if perdidas else (float('inf') if ganancias else 0)
            wr_r = round(len(ganancias)/len(trades)*100,1) if trades else 0
            resumen_rows.append({
                "Cuenta":        nombre,
                "Tipo":          data.get("tipo","?"),
                "Equity":        f"${equity_act:,.2f}",
                "Balance":       f"${balance_act:,.2f}",
                "DD%":           f"{dd_act:.2f}%",
                "Net P&L":       f"${net_p:,.2f}",
                "PF":            f"{pf_r:.2f}" if pf_r != float('inf') else "∞",
                "WR%":           f"{wr_r:.1f}%",
                "Trades":        len(trades),
                "Pos. Abiertas": len(posiciones),
                "Estado DD":     "🔴" if dd_act>5 else "🟡" if dd_act>3 else "🟢",
            })
        st.dataframe(pd.DataFrame(resumen_rows), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════
# TAB 5 — SQX VS LIVE + ALERTAS TELEGRAM
# ══════════════════════════════════════════════
with tab5:
    st.subheader("🔬 Comparador SQX Backtest vs Ejecución Real")

    col_sqx, col_tg = st.columns([3, 1])

    # ── Panel Telegram ─────────────────────────────────────────────
    with col_tg:
        st.subheader("🔔 Alertas Telegram")
        cfg = st.session_state['telegram_config']
        token_input   = st.text_input("Bot Token", value=cfg["token"], type="password", key="tg_token")
        chat_id_input = st.text_input("Chat ID",   value=cfg["chat_id"], key="tg_chatid")
        activo_input  = st.toggle("Alertas activas", value=cfg["activo"], key="tg_toggle")

        if st.button("💾 Guardar", key="tg_save"):
            st.session_state['telegram_config'] = {
                "token":   token_input,
                "chat_id": chat_id_input,
                "activo":  activo_input
            }
            st.success("✅ Guardado")

        if st.button("🧪 Probar conexión", key="tg_test"):
            ok = enviar_telegram("🦁 *Centro de Control activo*\nConexión Telegram verificada.")
            st.success("✅ Enviado") if ok else st.error("❌ Error — revisá token y chat_id")

        st.write("---")
        st.caption("**Alertas automáticas:**")
        st.caption("⚠️ DD > 3% por cuenta")
        st.caption("🚨 DD > 5% por cuenta")
        st.write("---")
        st.caption("**Cómo obtener Chat ID:**")
        st.caption("1. Mensajeá a tu bot")
        st.caption("2. Abrí: `api.telegram.org/bot<TOKEN>/getUpdates`")
        st.caption("3. Copiá `chat.id`")

    # ── Panel SQX ─────────────────────────────────────────────────
    with col_sqx:
        st.caption("Cargá el reporte HTML de SQX una vez por EA. La comparación se actualiza automáticamente con los trades en vivo.")

        # ── Cargar benchmark ──────────────────────────────────────
        with st.expander("➕ Cargar reporte SQX de un EA",
                         expanded=len(st.session_state['sqx_benchmarks']) == 0):
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                magic_input = st.text_input("Magic Number", placeholder="22001", key="sqx_magic")
            with c2:
                nombre_ea = st.text_input("Nombre EA", placeholder="XAUUSD_M15", key="sqx_nombre")
            with c3:
                archivo_sqx = st.file_uploader("Reporte HTML de SQX / QA",
                                               type=["html","htm","csv","xlsx"], key="sqx_upload")
            if archivo_sqx and magic_input:
                contenido = archivo_sqx.read()
                bm = parsear_sqx_html(contenido)
                if bm:
                    bm["nombre"] = nombre_ea or f"EA_{magic_input}"
                    st.session_state['sqx_benchmarks'][magic_input] = bm
                    st.success(f"✅ EA {magic_input} | PF: {bm['pf']} | WR: {bm['wr']}% | {bm['trades']} trades")
                else:
                    st.error("❌ No se extrajeron métricas. Verificá que el HTML tenga tabla de trades.")

        benchmarks = st.session_state['sqx_benchmarks']

        if not benchmarks:
            st.info("Sin benchmarks. Subí el HTML de SQX para cada EA arriba.")

        st.write("---")

        # Tabla resumen benchmarks
        rows_bm = []
        for mg, bm in benchmarks.items():
            pf_str = f"{bm['pf']:.2f}" if bm['pf'] != float('inf') else "∞"
            rows_bm.append({"Magic": mg, "EA": bm.get("nombre","?"),
                             "PF (SQX)": pf_str, "WR% (SQX)": f"{bm['wr']:.1f}%",
                             "Exp (SQX)": f"${bm['expectancy']:.2f}", "Trades": bm['trades']})
        st.dataframe(pd.DataFrame(rows_bm), use_container_width=True, hide_index=True)
        st.write("---")

        # Trades en vivo
        registros = st.session_state.get('registro_operaciones_en_vivo', [])
        df_all = pd.DataFrame(registros) if registros else pd.DataFrame()
        df_live_trades = pd.DataFrame()
        if not df_all.empty and 'Tipo' in df_all.columns:
            df_live_trades = df_all[df_all['Tipo'] == 'CLOSE'].copy()

        if df_live_trades.empty:
            st.warning("Sin trades en vivo todavía. Aparecerán cuando el mercado opere.")
        else:
            for mg, bm in benchmarks.items():
                nombre = bm.get("nombre", f"EA {mg}")
                df_ea = df_live_trades[df_live_trades['Magic'] == mg] if 'Magic' in df_live_trades.columns else pd.DataFrame()
                n = len(df_ea)

                with st.expander(f"🤖 {nombre}  (Magic {mg}) — {n} trades en vivo", expanded=True):
                    if df_ea.empty:
                        st.info("Sin trades cerrados en vivo para este EA.")
                        continue

                    # Métricas live
                    profits = df_ea['Beneficio'] if 'Beneficio' in df_ea.columns else pd.Series(dtype=float)
                    g = profits[profits > 0]
                    l = profits[profits < 0]
                    pf_l  = round(g.sum()/abs(l.sum()), 2) if abs(l.sum()) > 0 else float('inf')
                    wr_l  = round(len(g)/len(profits)*100, 1) if len(profits) > 0 else 0
                    aw_l  = round(g.mean(), 2) if not g.empty else 0
                    al_l  = round(l.mean(), 2) if not l.empty else 0
                    exp_l = round((wr_l/100*aw_l)+((1-wr_l/100)*al_l), 2)

                    # Grid comparación
                    header = st.columns([2, 1, 1, 2])
                    header[0].markdown("**Métrica**")
                    header[1].markdown("**SQX**")
                    header[2].markdown("**Live**")
                    header[3].markdown("**Delta**")

                    comparaciones = [
                        ("Profit Factor",  pf_l,  bm['pf'],         True),
                        ("Win Rate %",     wr_l,  bm['wr'],         True),
                        ("Expectancy $",   exp_l, bm['expectancy'],  True),
                        ("Avg Win $",      aw_l,  bm['avg_win'],    True),
                        ("Avg Loss $",     al_l,  bm['avg_loss'],   False),
                    ]

                    for label, lv, sv, mayor in comparaciones:
                        row = st.columns([2, 1, 1, 2])
                        row[0].write(label)
                        row[1].write(f"{sv:.2f}" if sv != float('inf') else "∞")
                        row[2].write(f"{lv:.2f}" if lv != float('inf') else "∞")
                        d, sem = delta_semaforo(lv, sv, mayor)
                        row[3].write(f"{sem} {d}")

                    # Gráfico P&L acumulado
                    if 'Fecha' in df_ea.columns:
                        df_plot = df_ea.copy()
                        df_plot['Fecha'] = pd.to_datetime(df_plot['Fecha'])
                        df_plot = df_plot.sort_values('Fecha')
                        fig_ea = go.Figure(go.Scatter(
                            x=df_plot['Fecha'],
                            y=df_plot['Beneficio'].cumsum(),
                            line=dict(color='#00d4ff', width=2),
                            fill='tozeroy', fillcolor='rgba(0,212,255,0.08)'
                        ))
                        fig_ea.add_hline(y=0, line_dash="dot", line_color="#666")
                        fig_ea.update_layout(template="plotly_dark", height=180,
                                             margin=dict(t=5,b=5,l=5,r=5),
                                             showlegend=False, yaxis_title="P&L $")
                        st.plotly_chart(fig_ea, use_container_width=True)

                    if st.button(f"🗑️ Eliminar benchmark EA {mg}", key=f"del_{mg}"):
                        del st.session_state['sqx_benchmarks'][mg]
                        st.rerun()
