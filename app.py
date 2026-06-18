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
    st.session_state['cuentas'] = {}
if 'sqx_benchmarks' not in st.session_state:
    st.session_state['sqx_benchmarks'] = {}
if 'magic_nombres' not in st.session_state:
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
        # Trades cerrados
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

        # Snapshots recientes
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
        pass

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

        cuentas = st.session_state['cuentas']
        if acc_name not in cuentas:
            cuentas[acc_name] = {
                "tipo": acc_type, "snapshots": [], "trades": [], "posiciones": {}
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
            reg = {"Fecha": ts, "Magic": "0", "Simbolo": "ACCOUNT",
                   "Tipo": "SNAPSHOT", "Beneficio": snap["ProfitFlot"], "Equity": snap["Equity"],
                   "Balance": snap["Balance"], "Commission": 0, "Swap": 0,
                   "ProfitNeto": snap["ProfitFlot"], "Account": acc_name}
            st.session_state['registro_operaciones_en_vivo'].append(reg)
            if not cuenta["snapshots"] or cuenta["snapshots"][-1]["Equity"] != snap["Equity"]:
                cuenta["snapshots"].append(snap)
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
            sb_upsert("posiciones", {
                "ticket":     ticket, "account":    acc_name, "magic":      pos_data["Magic"],
                "symbol":     pos_data["Simbolo"], "direction":  pos_data["Direccion"], "lots":       pos_data["Lots"],
                "price_open": pos_data["PriceOpen"], "price_cur":   pos_data["PriceCur"], "profit":     pos_data["Profit"],
                "swap":       pos_data["Swap"], "sl":         pos_data["SL"], "tp":         pos_data["TP"],
                "equity":     float(query_params.get("equity", 0)),
            })

        elif tipo == "CLOSE":
            ticket = str(query_params.get("ticket", "0"))
            profit_neto = float(query_params.get("profit_net", float(query_params.get("profit", 0))))
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
                sb_upsert("trades", {
                    "ticket":      ticket, "account":     acc_name, "acc_type":    acc_type,
                    "magic":       nuevo_trade["Magic"], "symbol":      nuevo_trade["Simbolo"], "direction":   nuevo_trade["Direccion"],
                    "lots":        nuevo_trade["Lots"], "precio":      nuevo_trade["Precio"], "profit":      nuevo_trade["Beneficio"],
                    "commission":  nuevo_trade["Commission"], "swap":        nuevo_trade["Swap"], "profit_neto": profit_neto,
                    "equity":      nuevo_trade["Equity"], "close_time":  int(query_params.get("close_time", 0)),
                })
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
    except Exception:
        pass

# ─────────────────────────────────────────────
# FUNCIONES AUXILIARES — TAB 1 Y MAPEO MT5
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

def mapear_comentarios_mt5(df):
    """Mapea cierres por SL/TP heredando el comentario original del deal de entrada."""
    df.columns = df.columns.str.strip().str.lower()
    col_position = next((c for c in df.columns if 'position' in c or 'posicion' in c or 'ticket' in c), None)
    col_comment = next((c for c in df.columns if 'comment' in c or 'comentario' in c), None)
    col_symbol = next((c for c in df.columns if 'symbol' in c or 'símbolo' in c or 'asset' in c), None)

    if not col_position or not col_comment:
        return df

    df[col_comment] = df[col_comment].astype(str).str.strip()
    es_entrada_ea = (
        (~df[col_comment].str.contains(r'^\[sl|^\[tp', case=False, na=False)) & 
        (df[col_comment] != '') & (df[col_comment] != 'nan')
    )
    mapa_posiciones = df[es_entrada_ea].set_index(col_position)[col_comment].to_dict()

    def asignar_comentario(row):
        pos_id = row[col_position]
        comm_actual = str(row[col_comment]).strip()
        if pos_id in mapa_posiciones:
            return mapa_posiciones[pos_id]
        if re.match(r'^\[sl|^\[tp', comm_actual, re.IGNORECASE):
            simbolo = str(row[col_symbol]).upper() if col_symbol else "UNKNOWN"
            return f"EA_AutoAsignado_{simbolo}"
        if comm_actual == '' or comm_actual == 'nan':
            simbolo = str(row[col_symbol]).upper() if col_symbol else "GENERIC"
            return f"Manual_{simbolo}"
        return comm_actual

    df['ea_limpio'] = df.apply(asignar_comentario, axis=1)
    return df

# ─────────────────────────────────────────────
# FUNCIONES MÉTRICAS — TAB 2
# ─────────────────────────────────────────────
def calcular_sharpe(serie_retornos, periodos_anuales=252):
    if len(serie_retornos) < 2:
        return 0.0
    media = serie_retornos.mean()
    std   = serie_retornos.std()
    if std == 0:
        return 0.0
    return round((media / std) * math.sqrt(periodos_anuales), 2)

def calcular_metricas_portfolio(df_trades):
    if df_trades.empty:
        return {}
    beneficios = df_trades['Beneficio']
    ganancias  = beneficios[beneficios > 0]
    perdidas   = beneficios[beneficios < 0]

    gross_profit = ganancias.sum() if not ganancias.empty else 0
    gross_loss   = abs(perdidas.sum()) if not perdidas.empty else 0
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf')

    total_trades = len(beneficios[beneficios != 0])
    win_rate = round(len(ganancias) / total_trades * 100, 1) if total_trades > 0 else 0
    avg_win  = round(ganancias.mean(), 2) if not ganancias.empty else 0
    avg_loss = round(perdidas.mean(), 2) if not perdidas.empty else 0
    expectancy = round((win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss), 2)

    retornos = beneficios[beneficios != 0]
    sharpe = calcular_sharpe(retornos, periodos_anuales=len(retornos))

    equity_serie = df_trades['Equity']
    if not equity_serie.empty:
        peak = equity_serie.cummax()
        dd_serie = (equity_serie - peak) / peak * 100
        max_dd = round(dd_serie.min(), 2)
    else:
        max_dd = 0.0

    recovery = round(beneficios.sum() / abs(max_dd) * 100, 2) if max_dd != 0 else 0
    return {
        "profit_factor": pf, "win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss,
        "expectancy": expectancy, "sharpe": sharpe, "max_dd_pct": max_dd, "recovery_factor": recovery,
        "total_trades": total_trades, "net_profit": round(beneficios.sum(), 2)
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
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}).encode()
        req  = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False

def verificar_alertas_dd(snapshots: list, cuenta: str):
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
        elif dd < umbral * 0.5:
            alertas.discard(clave)

# ─────────────────────────────────────────────
# COMPARADOR SQX — funciones auxiliares
# ─────────────────────────────────────────────
def parsear_sqx_html(contenido_bytes) -> dict:
    try:
        tablas = pd.read_html(io.BytesIO(contenido_bytes))
    except Exception:
        return {}
    profits = []
    for t in tablas:
        t.columns = t.columns.astype(str).str.lower().str.strip()
        for col in t.columns:
            if any(k in col for k in ['profit','p/l','ganancia','beneficio']):
                vals = pd.to_numeric(t[col].astype(str).str.replace(r'[^\d\.\-]','',regex=True), errors='coerce').dropna()
                if len(vals) > 5:
                    profits.extend(vals.tolist())
                    break
    if not profits:
        return {}
    s = pd.Series(profits)
    g = s[s > 0]; l = s[s < 0]
    pf  = round(g.sum()/abs(l.sum()), 2) if abs(l.sum()) > 0 else float('inf')
    wr  = round(len(g)/len(s)*100, 1)
    exp = round((wr/100 * g.mean() if not g.empty else 0) + ((1-wr/100) * l.mean() if not l.empty else 0), 2)
    return {
        "pf": pf, "wr": wr, "expectancy": exp, "avg_win": round(g.mean(), 2) if not g.empty else 0,
        "avg_loss": round(l.mean(), 2) if not l.empty else 0, "trades": len(s), "net_profit": round(s.sum(), 2),
    }

def delta_semaforo(live_val, sqx_val, mayor_es_mejor=True):
    if sqx_val == 0:
        return "N/A", "⚪"
    ratio = live_val / sqx_val
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
            k4.metric("Meses con Alerta (>${:.0f})".format(umbral_alerta), str(len(df_final[abs(df_final['Desviacion']) > umbral_alerta])))

            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_final['Periodo'], y=df_final['Teorico'],  name='Teórico (QA)',   marker_color='#1f77b4'))
            fig.add_trace(go.Bar(x=df_final['Periodo'], y=df_final['Real'],     name='Real (Broker)',   marker_color='#2ca02c'))
            fig.add_trace(go.Scatter(x=df_final['Periodo'], y=df_final['Desviacion'], name='Desviación Neta', line=dict(color='#d62728', width=3, dash='dot'), mode='lines+markers'))
            fig.add_hline(y=umbral_alerta,  line_dash="dash", line_color="orange", annotation_text=f"+${umbral_alerta}")
            fig.add_hline(y=-umbral_alerta, line_dash="dash", line_color="orange", annotation_text=f"-${umbral_alerta}")
            fig.update_layout(barmode='group', template="plotly_dark", xaxis_title="Mes", yaxis_title="Balance ($)", height=420, margin=dict(t=20))
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

    cfg1, cfg2, cfg3 = st.columns([2, 1, 1])
    with cfg1:
        url_actual = st.text_input("URL de tu app (para el webhook en MT5)", value="https://TU-APP.streamlit.app")
        st.code(f"{url_actual}/?action=webhook_mt5&magic=22001&symbol=XAUUSD&type=CLOSE&profit=12.50&equity=10250.00", language="text")
    with cfg2:
        capital_input = st.number_input("Capital Inicial ($)", min_value=1000.0, value=st.session_state['capital_inicial'], step=500.0, format="%.2f")

# ══════════════════════════════════════════════
# TAB 3 — ANÁLISIS HISTÓRICO POR EA (Mapeado e Indexado)
# ══════════════════════════════════════════════
with tab3:
    st.subheader("📊 Análisis Cuantitativo por EA — Reporte MT5 (Deals)")
    st.markdown("""
    Exporta desde MT5 $\rightarrow$ Historial $\rightarrow$ Reporte $\rightarrow$ Open XML (Excel). 
    La app detectará automáticamente las posiciones vinculadas y recuperará el nombre del EA original aunque haya cerrado por SL/TP.
    """)
    
    archivo_tab3 = archivo_real if archivo_real else st.file_uploader("Subir reporte MT5 (.csv, .xlsx, .html)", key="uploader_tab3")

    if archivo_tab3:
        try:
            archivo_tab3.seek(0)
            df_raw = leer_archivo_inteligente(archivo_tab3)
            df_procesado = mapear_comentarios_mt5(df_raw)
            col_fecha, col_profit = encontrar_columnas_universal(df_procesado)
            
            df_procesado['Beneficio'] = pd.to_numeric(
                df_procesado[col_profit].astype(str).str.replace(r'[^\d\.\-]', '', regex=True), errors='coerce'
            ).fillna(0)
            
            if 'equity' not in df_procesado.columns:
                df_procesado = df_procesado.sort_values(col_fecha)
                df_procesado['Equity'] = capital_input + df_procesado['Beneficio'].cumsum()

            metricas_globales = calcular_metricas_portfolio(df_procesado)
            
            st.markdown("### 📈 Performance Global del Portfolio")
            g1, g2, g3, g4, g5 = st.columns(5)
            g1.metric("Net Profit", f"${metricas_globales.get('net_profit', 0):,.2f}")
            g2.metric("Profit Factor", f"{metricas_globales.get('profit_factor', 0)}")
            g3.metric("Win Rate", f"{metricas_globales.get('win_rate', 0)}%")
            g4.metric("Expectancy", f"${metricas_globales.get('expectancy', 0)}")
            g5.metric("Total Trades", metricas_globales.get('total_trades', 0))
            
            st.write("---")
            st.markdown("### 🏆 Ranking de EAs por Performance Real")

            ranking_data = []
            for name, group in df_procesado.groupby('ea_limpio'):
                if group['Beneficio'].abs().sum() == 0: 
                    continue
                    
                m = calcular_metricas_portfolio(group)
                pf = m.get('profit_factor', 0)
                status = "🔴" if pf < 1.1 else "🟡" if pf < 1.4 else "🟢"
                
                ranking_data.append({
                    "Estado": status,
                    "EA / Estrategia": name,
                    "Trades": m.get('total_trades', 0),
                    "Net Profit": round(m.get('net_profit', 0), 2),
                    "PF": pf,
                    "WR%": f"{m.get('win_rate', 0)}%",
                    "Avg Win": f"${m.get('avg_win', 0)}",
                    "Avg Loss": f"${m.get('avg_loss', 0)}",
                    "Expectancy": f"${m.get('expectancy', 0)}",
                    "Max DD": f"{m.get('max_dd_pct', 0)}%"
                })
            
            if ranking_data:
                df_ranking = pd.DataFrame(ranking_data).sort_values(by="Net Profit", ascending=False).reset_index(drop=True)
                st.dataframe(df_ranking, use_container_width=True)
            else:
                st.warning("No se pudieron extraer métricas individuales.")
        except Exception as e:
            st.error(f"❌ Error al procesar el ranking de la Tab 3: {e}")
    else:
        st.info("💡 Sube un reporte detallado en la sección estática o aquí para armar el ranking por EA.")

# ══════════════════════════════════════════════
# TAB 4 — MULTI-CUENTA (Estructura de marcador)
# ══════════════════════════════════════════════
with tab4:
    st.subheader("🌐 Gestión de Cuentas Múltiples")
    if st.session_state['cuentas']:
        for acc_id, acc_data in st.session_state['cuentas'].items():
            st.text(f"Cuenta detectada: {acc_id} [{acc_data.get('tipo', 'DESCONOCIDO')}]")
    else:
        st.info("No hay telemetría multi-cuenta registrada todavía.")

# ══════════════════════════════════════════════
# TAB 5 — COMPARADOR CONFIG / TELEGRAM
# ══════════════════════════════════════════════
with tab5:
    st.subheader("🔬 Benchmarks de Quant Analyzer vs Servidor en Vivo")
    st.info("Configura los umbrales de tus estrategias y notificaciones acá.")
