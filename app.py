import streamlit as st
import pandas as pd
import numpy as np
import math
import folium
from streamlit_folium import st_folium
from io import BytesIO

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Canibalización de Tiendas",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #0f1117; color: #e8e6df; }
section[data-testid="stSidebar"] { background: #161820; border-right: 1px solid #2a2d3a; }
section[data-testid="stSidebar"] * { color: #c8c6bf !important; }
.metric-card {
    background: #1a1d27; border: 1px solid #2a2d3a;
    border-radius: 10px; padding: 16px 20px; margin: 6px 0;
}
.metric-label { font-size: 11px; color: #7a7a8a; text-transform: uppercase; letter-spacing:.06em; margin-bottom:4px; }
.metric-value { font-size: 22px; font-weight: 600; font-family: 'DM Mono', monospace; }
.metric-sub   { font-size: 11px; color: #7a7a8a; margin-top: 2px; }
.nivel-bajo  { color: #4ade80; }
.nivel-medio { color: #fbbf24; }
.nivel-alto  { color: #f87171; }
.section-header {
    font-size: 11px; font-weight: 600; color: #5a5a6a;
    text-transform: uppercase; letter-spacing:.1em;
    margin: 22px 0 10px; padding-bottom: 8px;
    border-bottom: 1px solid #2a2d3a;
}
.info-box {
    background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 10px;
    padding: 14px 18px; font-size: 13px; color: #9a9aaa; line-height: 1.7; margin: 8px 0;
}
.info-box b { color: #e8e6df; }
.step-pill {
    display: inline-block; padding: 4px 14px; border-radius: 20px;
    font-size: 12px; font-weight: 600; margin-right: 6px;
}
.step-active   { background: #1e3a5f; color: #60a5fa; }
.step-done     { background: #14532d; color: #4ade80; }
.step-inactive { background: #1a1d27; color: #5a5a6a; border: 1px solid #2a2d3a; }
.score-bar-wrap { background: #2a2d3a; border-radius: 6px; height: 6px; margin: 6px 0; overflow: hidden; }
.score-bar { height: 6px; border-radius: 6px; }
.tag-pill {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600; margin: 2px 3px;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# CONSTANTES DE SCORE
# ─────────────────────────────────────────────

# Factor madurez TIE26 — tiendas jóvenes son más vulnerables
FACTOR_MADUREZ = {
    "TMCB":     0.85,   # +18 meses, más resilientes
    "EXP 2024": 1.05,
    "EXP 2025": 1.10,
    "EXP 2026": 1.15,   # muy recientes, máxima vulnerabilidad
    "CERRADA":  0.0,
}

# Factor generador — densidad de hogares + tipo atractor
FACTOR_GENERADOR = {
    "ALTA DENSIDAD":        1.20,   # muchos hogares = disputa directa de clientela
    "BAJA DENSIDAD":        0.85,   # pocos hogares = menos impacto residencial
    "COMERCIO/SERVICIO":    1.00,
    "ADMINISTRATIVO":       1.05,   # depende de empleados, algo vulnerable
    "SALUD":                0.85,   # tráfico cautivo/especializado
    "EDUCACION":            0.85,
    "TRANSPORTE":           0.90,
    "ESTACION DE SERVICIO": 0.80,
    "NICHO":                0.75,
    "INDUSTRIA":            0.80,
}

# Pesos VT / ET por segmento
# RECESO = más empleados, HOGAR = más viviendas, BASE = mix
PESO_VT_SEG = {"RECESO": 0.25, "HOGAR": 0.75, "BASE": 0.50, "CERRADA": 0.50}
PESO_ET_SEG = {"RECESO": 0.75, "HOGAR": 0.25, "BASE": 0.50, "CERRADA": 0.50}

ESCALA_MAX = 25.0   # score final en porcentaje


# ─────────────────────────────────────────────
# FUNCIONES CORE
# ─────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def area_lente(d, r):
    if d >= 2*r: return 0.0
    if d <= 0:   return math.pi * r * r
    return 2*r*r*math.acos(d/(2*r)) - (d/2)*math.sqrt(4*r*r - d*d)

def pct_overlap(d, r):
    return area_lente(d, r) / (math.pi * r * r) * 100

def chord_length(d, r):
    if d >= 2*r: return 0.0
    return 2 * math.sqrt(max(0, r*r - (d/2)**2))

def safe_num(val, default=0.0):
    try:
        v = float(str(val).replace("$","").replace(",","").strip())
        return v if not math.isnan(v) else default
    except:
        return default

def nivel_canib(score_pct):
    """score_pct en escala 0-25"""
    if score_pct < 6:   return "Bajo",  "#4ade80", "nivel-bajo"
    if score_pct < 14:  return "Medio", "#fbbf24", "nivel-medio"
    return "Alto", "#f87171", "nivel-alto"

def calcular_score_nuevo(pct_geo, viv_lente, vt, et, seg26, tie26, generador,
                          ventas_um, me, contribucion_um,
                          w_geo, w_viv, w_emp, w_contrib, w_me):
    """
    Retorna score en escala 0-25%.
    
    Componentes:
      c_geo    = overlap geométrico (0-1)
      c_viv    = viviendas lente / VT ponderado por segmento
      c_emp    = viviendas lente proxy empleados / ET ponderado por segmento
      c_contrib= riesgo financiero por contribución baja o negativa
      c_me     = qué tan cerca está la tienda de su venta mínima (ME)
    
    Multiplicadores:
      factor_madurez   (TIE26)
      factor_generador (GENERADOR)
      factor_segmento  (SEG26 amplifica según perfil de clientela)
    """
    seg  = str(seg26).strip().upper()   if pd.notna(seg26)   else "BASE"
    tie  = str(tie26).strip().upper()   if pd.notna(tie26)   else "TMCB"
    gen  = str(generador).strip().upper() if pd.notna(generador) else "COMERCIO/SERVICIO"

    # ── Componente geométrico ───────────────
    c_geo = pct_geo / 100.0

    # ── Componente viviendas ────────────────
    pw_vt = PESO_VT_SEG.get(seg, 0.50)
    vt_   = max(vt, 1.0)
    c_viv = min((viv_lente / vt_) * pw_vt, 1.0)

    # ── Componente empleados ────────────────
    # Usamos la fracción de overlap como proxy de empleados capturados
    pw_et = PESO_ET_SEG.get(seg, 0.50)
    et_   = max(et, 1.0)
    emp_en_lente = et_ * (pct_geo / 100.0)   # estimado proporcional
    c_emp = min((emp_en_lente / et_) * pw_et, 1.0)

    # ── Componente contribución ─────────────
    # Si contribución < 0 → riesgo máximo; si > ME*0.3 → riesgo bajo
    umbral_contrib = me * 0.15   # mínimo contribución saludable (~15% del ME)
    if contribucion_um <= 0:
        c_contrib = 1.0
    elif contribucion_um >= umbral_contrib:
        c_contrib = max(0.0, 1.0 - (contribucion_um / (umbral_contrib * 4)))
    else:
        c_contrib = 1.0 - (contribucion_um / umbral_contrib) * 0.5

    # ── Componente ME (modelo económico) ───
    # Qué tan cerca está la tienda de su venta mínima
    me_ = max(me, 1.0)
    if ventas_um <= 0:
        c_me = 1.0
    elif ventas_um >= me_:
        # Tienda sana: holgura positiva
        holgura = (ventas_um - me_) / me_
        c_me = max(0.0, 1.0 - holgura)   # más holgura = menos riesgo
    else:
        # Tienda por debajo del ME: ya en zona crítica
        deficit = (me_ - ventas_um) / me_
        c_me = min(1.0, 0.5 + deficit)

    # ── Score ponderado base ────────────────
    total_w = w_geo + w_viv + w_emp + w_contrib + w_me
    if total_w == 0: total_w = 1.0
    score_base = (
        w_geo    * c_geo +
        w_viv    * c_viv +
        w_emp    * c_emp +
        w_contrib* c_contrib +
        w_me     * c_me
    ) / total_w

    # ── Multiplicadores ─────────────────────
    f_mad = FACTOR_MADUREZ.get(tie, 1.0)
    f_gen = FACTOR_GENERADOR.get(gen, 1.0)

    # Factor segmento: HOGAR más expuesto a punto B residencial (conservador)
    f_seg = {"HOGAR": 1.10, "RECESO": 0.95, "BASE": 1.00, "CERRADA": 0.0}.get(seg, 1.0)

    score_final = score_base * f_mad * f_gen * f_seg

    # Llevar a escala 0-25%
    return round(min(score_final, 1.0) * ESCALA_MAX, 2)


def fmt_n(n):  return f"{n:,.0f}".replace(",", ".")
def fmt_p(p):  return f"{p:.1f}%"
def fmt_s(s):  return f"${s:,.0f}".replace(",", ".")
def fmt_score(s): return f"{s:.1f}%"

def nombre_tienda(row):
    for c in ["name", "nombre", "id_tienda", "tienda", "cr"]:
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip() != "":
            return str(row[c])
    return f"Tienda {row.NAME}"


# ─────────────────────────────────────────────
# ESTADO DE SESIÓN
# ─────────────────────────────────────────────
defaults = {
    "df": None,
    "lat_b": 4.6357799, "lon_b": -74.0751250,
    "nombre_b": "Punto nuevo", "radio": 300,
    "tiendas_afectadas": None,
    "viv_inputs": {},
    "reporte_listo": False,
    # Pesos del score
    "w_geo":    0.30,
    "w_viv":    0.20,
    "w_emp":    0.15,
    "w_contrib":0.20,
    "w_me":     0.15,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📍 Canibalización")
    st.markdown("---")
    st.markdown("**Base de tiendas operando**")

    # ── Carga por URL de GitHub ──────────────
    st.markdown("**Cargar desde GitHub (URL raw)**")
    github_url = st.text_input(
        "URL raw del Excel",
        placeholder="https://raw.githubusercontent.com/.../Book.xlsx",
        help="Pega la URL raw de tu archivo en GitHub"
    )
    if github_url and st.button("📥 Cargar desde GitHub"):
        try:
            import requests
            r = requests.get(github_url)
            r.raise_for_status()
            df_raw = pd.read_excel(BytesIO(r.content))
            df_raw.columns = [c.strip() for c in df_raw.columns]
            # Normalizar columnas clave a mayúsculas
            col_map = {c: c.upper() for c in df_raw.columns}
            df_raw.rename(columns=col_map, inplace=True)
            df_raw["LATITUD"]  = pd.to_numeric(df_raw["LATITUD"],  errors="coerce")
            df_raw["LONGITUD"] = pd.to_numeric(df_raw["LONGITUD"], errors="coerce")
            df_raw = df_raw[df_raw["ESTADO"].astype(str).str.upper() == "ABIERTA"]
            df_raw = df_raw.dropna(subset=["LATITUD","LONGITUD"]).reset_index(drop=True)
            st.session_state.df = df_raw
            st.session_state.tiendas_afectadas = None
            st.session_state.reporte_listo = False
            st.session_state.viv_inputs = {}
            st.success(f"✓ {len(df_raw)} tiendas cargadas desde GitHub")
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("**— o sube un archivo —**")
    uploaded = st.file_uploader("Excel", type=["xlsx","xls"])

    if uploaded:
        try:
            df_raw = pd.read_excel(uploaded)
            df_raw.columns = [c.strip() for c in df_raw.columns]
            col_map = {c: c.upper() for c in df_raw.columns}
            df_raw.rename(columns=col_map, inplace=True)
            df_raw["LATITUD"]  = pd.to_numeric(df_raw["LATITUD"],  errors="coerce")
            df_raw["LONGITUD"] = pd.to_numeric(df_raw["LONGITUD"], errors="coerce")
            # Solo tiendas ABIERTAS
            if "ESTADO" in df_raw.columns:
                df_raw = df_raw[df_raw["ESTADO"].astype(str).str.upper() == "ABIERTA"]
            df_raw = df_raw.dropna(subset=["LATITUD","LONGITUD"]).reset_index(drop=True)

            if (st.session_state.df is None or
                    len(df_raw) != len(st.session_state.df)):
                st.session_state.df = df_raw
                st.session_state.tiendas_afectadas = None
                st.session_state.reporte_listo = False
                st.session_state.viv_inputs = {}

            st.success(f"✓ {len(df_raw)} tiendas activas cargadas")
        except Exception as e:
            st.error(f"Error cargando archivo: {e}")

    st.markdown("---")
    st.markdown("**Radio de influencia**")
    radio = st.slider("Metros", 100, 1000, st.session_state.radio, 50)
    if radio != st.session_state.radio:
        st.session_state.radio = radio
        st.session_state.tiendas_afectadas = None
        st.session_state.reporte_listo = False

    st.markdown("---")
    with st.expander("⚙️ Pesos del score"):
        st.caption("Deben sumar 1.0")
        w_geo     = st.slider("Overlap geométrico",  0.0, 1.0, st.session_state.w_geo,     0.05)
        w_viv     = st.slider("Viviendas (VT)",       0.0, 1.0, st.session_state.w_viv,     0.05)
        w_emp     = st.slider("Empleados (ET)",        0.0, 1.0, st.session_state.w_emp,     0.05)
        w_contrib = st.slider("Contribución",          0.0, 1.0, st.session_state.w_contrib, 0.05)
        w_me      = st.slider("Modelo Económico (ME)", 0.0, 1.0, st.session_state.w_me,      0.05)
        st.session_state.w_geo     = w_geo
        st.session_state.w_viv     = w_viv
        st.session_state.w_emp     = w_emp
        st.session_state.w_contrib = w_contrib
        st.session_state.w_me      = w_me
        total_w = w_geo + w_viv + w_emp + w_contrib + w_me
        if abs(total_w - 1.0) > 0.01:
            st.warning(f"Suman {total_w:.2f} — se normalizan automáticamente")
        else:
            st.success(f"✓ Suman {total_w:.2f}")

    st.markdown("---")
    st.markdown("""
    <div style='font-size:11px;color:#5a5a6a;line-height:2'>
    🟢 <b style='color:#7a7a8a'>Bajo</b> &nbsp; score &lt; 6%<br>
    🟡 <b style='color:#7a7a8a'>Medio</b> &nbsp; 6% – 14%<br>
    🔴 <b style='color:#7a7a8a'>Alto</b> &nbsp; score &gt; 14%<br><br>
    <b style='color:#7a7a8a'>Multiplicadores activos:</b><br>
    TIE26 · GENERADOR · SEG26
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
st.markdown("## Análisis de Canibalización")

df  = st.session_state.df
r   = st.session_state.radio
ta  = st.session_state.tiendas_afectadas

p1 = "step-done"    if df is not None else "step-active"
p2 = "step-done"    if ta is not None else ("step-active" if df is not None else "step-inactive")
p3 = "step-done"    if st.session_state.reporte_listo else ("step-active" if ta is not None else "step-inactive")
st.markdown(f"""
<span class='step-pill {p1}'>1 Cargar BD</span>
<span class='step-pill {p2}'>2 Tiendas afectadas</span>
<span class='step-pill {p3}'>3 Viviendas → Reporte</span>
""", unsafe_allow_html=True)
st.markdown("---")


# ── PASO 1: sin BD ───────────────────────────
if df is None:
    st.markdown("""
    <div class='info-box'>
    <b>Sube tu base de tiendas o conéctala desde GitHub.</b><br><br>
    Columnas mínimas requeridas: <code>LATITUD</code>, <code>LONGITUD</code>, <code>ESTADO</code><br>
    Score enriquecido usa: <code>VT</code>, <code>ET</code>, <code>SEG26</code>, <code>TIE26</code>, 
    <code>GENERADOR</code>, <code>ME</code>, <code>CONTRIBUCION UM</code>, <code>VENTAS OUM</code><br>
    Solo se cargan tiendas con <code>ESTADO = ABIERTA</code>
    </div>""", unsafe_allow_html=True)
    st.stop()


# ── PASO 2: Punto B ──────────────────────────
st.markdown("<div class='section-header'>Punto potencial B</div>", unsafe_allow_html=True)

c1, c2, c3 = st.columns([1,1,2])
with c1:
    lat_b = st.number_input("Latitud",  value=st.session_state.lat_b,  format="%.7f")
    lon_b = st.number_input("Longitud", value=st.session_state.lon_b,  format="%.7f")
with c2:
    nombre_b = st.text_input("Nombre del punto", value=st.session_state.nombre_b)
with c3:
    st.markdown("<br>", unsafe_allow_html=True)
    buscar = st.button("🔍  Identificar tiendas en radio", type="primary", use_container_width=True)

if buscar:
    st.session_state.lat_b    = lat_b
    st.session_state.lon_b    = lon_b
    st.session_state.nombre_b = nombre_b
    st.session_state.viv_inputs    = {}
    st.session_state.reporte_listo = False

    filas = []
    for idx, row in df.iterrows():
        d = haversine(row["LATITUD"], row["LONGITUD"], lat_b, lon_b)
        if d < 2 * r:
            pct  = pct_overlap(d, r)
            al   = area_lente(d, r)
            ch   = chord_length(d, r)
            vt_  = safe_num(row.get("VT", 0))
            et_  = safe_num(row.get("ET", 0))
            vum  = safe_num(row.get("VENTAS OUM", 0))
            cum  = safe_num(row.get("CONTRIBUCION UM", 0))
            me_  = safe_num(row.get("ME", 232000))
            tum  = safe_num(row.get("TRAFICO UM", 0))
            tu6m = safe_num(row.get("TRAFICO U6M", 0))
            vu6m = safe_num(row.get("VENTAS OU6M", 0))

            filas.append({
                "_idx":           idx,
                "tienda":         nombre_tienda(row),
                "latitud_A":      float(row["LATITUD"]),
                "longitud_A":     float(row["LONGITUD"]),
                "distancia_m":    round(d, 1),
                "pct_overlap":    round(pct, 2),
                "area_lente_m2":  round(al, 1),
                "cuerda_m":       round(ch, 1),
                "vt":             vt_,
                "et":             et_,
                "seg26":          str(row.get("SEG26", "BASE")),
                "tie26":          str(row.get("TIE26", "TMCB")),
                "generador":      str(row.get("GENERADOR", "COMERCIO/SERVICIO")),
                "ventas_um":      vum,
                "ventas_u6m":     vu6m,
                "contribucion_um":cum,
                "me":             me_,
                "trafico_um":     tum,
                "trafico_u6m":    tu6m,
                "viv_lente":      0,   # se ingresa en paso 3
            })

    st.session_state.tiendas_afectadas = pd.DataFrame(filas) if filas else pd.DataFrame()
    st.rerun()

ta = st.session_state.tiendas_afectadas

if ta is None:
    st.info("Ingresa las coordenadas del punto B y pulsa **Identificar tiendas en radio**.")
    st.stop()

if ta.empty:
    st.success(f"✅ Sin canibalización — ninguna tienda está dentro del radio de **{r} m**.")
    st.stop()


# ── MAPA ─────────────────────────────────────
lat_b_ = st.session_state.lat_b
lon_b_ = st.session_state.lon_b
COLORES = ["#f87171","#fbbf24","#fb923c","#e879f9","#a78bfa","#34d399","#60a5fa"]

st.markdown(f"<div class='section-header'>{len(ta)} tienda(s) dentro del radio de {r} m</div>",
            unsafe_allow_html=True)

todas_lats = list(df["LATITUD"]) + [lat_b_]
todas_lons = list(df["LONGITUD"]) + [lon_b_]
centro = [np.mean(todas_lats), np.mean(todas_lons)]

m = folium.Map(location=centro, zoom_start=15, tiles="CartoDB dark_matter")

def icono_tienda(color, label=""):
    svg = f"""
    <div style="position:relative;text-align:center">
      <div style="background:{color};border:2px solid white;border-radius:6px 6px 0 0;
        width:28px;height:22px;display:flex;align-items:center;justify-content:center;
        box-shadow:0 2px 6px rgba(0,0,0,0.5)">
        <svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24'
             fill='none' stroke='white' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>
          <path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/>
          <polyline points='9 22 9 12 15 12 15 22'/>
        </svg>
      </div>
      <div style="width:0;height:0;border-left:6px solid transparent;
        border-right:6px solid transparent;border-top:7px solid {color};margin:0 auto"></div>
      {'<div style="background:rgba(0,0,0,0.75);color:white;font-size:9px;padding:1px 5px;border-radius:3px;white-space:nowrap;margin-top:2px;font-family:monospace">' + label + '</div>' if label else ''}
    </div>"""
    return folium.DivIcon(html=svg, icon_size=(28, 46), icon_anchor=(14, 46))

def icono_gris():
    svg = """<div style="background:#4a4a5a;border:1.5px solid #888;border-radius:4px 4px 0 0;
      width:18px;height:14px;display:flex;align-items:center;justify-content:center;
      box-shadow:0 1px 4px rgba(0,0,0,0.4)">
      <svg xmlns='http://www.w3.org/2000/svg' width='9' height='9' viewBox='0 0 24 24'
           fill='none' stroke='#aaa' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'>
        <path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/>
        <polyline points='9 22 9 12 15 12 15 22'/>
      </svg>
    </div>
    <div style="width:0;height:0;border-left:4px solid transparent;
      border-right:4px solid transparent;border-top:5px solid #4a4a5a;margin:0 auto"></div>"""
    return folium.DivIcon(html=svg, icon_size=(18, 22), icon_anchor=(9, 22))

def icono_punto_b(nombre=""):
    svg = f"""
    <div style="position:relative;text-align:center">
      <div style="background:#22c55e;border:2.5px solid white;border-radius:50% 50% 50% 0;
        width:32px;height:32px;transform:rotate(-45deg);display:flex;align-items:center;
        justify-content:center;box-shadow:0 3px 8px rgba(0,0,0,0.5)">
        <div style="transform:rotate(45deg);display:flex;align-items:center;justify-content:center">
          <svg xmlns='http://www.w3.org/2000/svg' width='15' height='15' viewBox='0 0 24 24'
               fill='none' stroke='white' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>
            <circle cx='12' cy='12' r='3'/>
            <path d='M12 2v3M12 19v3M2 12h3M19 12h3'/>
          </svg>
        </div>
      </div>
      {'<div style="background:rgba(34,197,94,0.9);color:white;font-size:9px;padding:1px 6px;border-radius:3px;white-space:nowrap;margin-top:4px;font-family:monospace;font-weight:600">' + nombre[:20] + '</div>' if nombre else ''}
    </div>"""
    return folium.DivIcon(html=svg, icon_size=(32, 52), icon_anchor=(16, 52))

afect_idx = set(ta["_idx"].tolist())
for _, row in df.iterrows():
    if row.name not in afect_idx:
        folium.Marker(
            location=[row["LATITUD"], row["LONGITUD"]],
            icon=icono_gris(),
            tooltip=folium.Tooltip(
                f"<b>{nombre_tienda(row)}</b><br>Fuera del radio",
                style="font-family:monospace;font-size:12px")
        ).add_to(m)

for i, (_, trow) in enumerate(ta.iterrows()):
    col = COLORES[i % len(COLORES)]
    folium.Circle(
        location=[trow["latitud_A"], trow["longitud_A"]],
        radius=r, color=col, weight=1.5,
        fill=True, fill_color=col, fill_opacity=0.12,
    ).add_to(m)
    folium.PolyLine(
        [[trow["latitud_A"], trow["longitud_A"]], [lat_b_, lon_b_]],
        color=col, weight=2, dash_array="8 4",
        tooltip=folium.Tooltip(f"Distancia: <b>{trow['distancia_m']:.0f} m</b>",
                               style="font-family:monospace;font-size:12px")
    ).add_to(m)
    folium.Marker(
        location=[trow["latitud_A"], trow["longitud_A"]],
        icon=icono_tienda(col, trow["tienda"][:12]),
        tooltip=folium.Tooltip(
            f"<b>{trow['tienda']}</b><br>"
            f"Distancia: {trow['distancia_m']:.0f} m | Overlap: {trow['pct_overlap']:.1f}%<br>"
            f"SEG: {trow['seg26']} | TIE: {trow['tie26']}<br>"
            f"Generador: {trow['generador']}",
            style="font-family:monospace;font-size:12px")
    ).add_to(m)

folium.Circle(
    location=[lat_b_, lon_b_], radius=r,
    color="#22c55e", weight=2,
    fill=True, fill_color="#22c55e", fill_opacity=0.08, dash_array="6 3"
).add_to(m)
folium.Marker(
    location=[lat_b_, lon_b_],
    icon=icono_punto_b(st.session_state.nombre_b),
    tooltip=folium.Tooltip(
        f"<b>Punto potencial: {st.session_state.nombre_b}</b><br>"
        f"Radio: {r} m | Tiendas en radio: {len(ta)}",
        style="font-family:monospace;font-size:12px")
).add_to(m)

leyenda_html = """
<div style="position:fixed;bottom:20px;right:10px;z-index:1000;
  background:rgba(15,17,23,0.92);border:1px solid #2a2d3a;
  border-radius:8px;padding:10px 14px;font-family:monospace;font-size:11px;color:#c8c6bf">
  <div style="font-weight:600;margin-bottom:6px;color:#e8e6df">Leyenda</div>
  <div style="display:flex;align-items:center;gap:8px;margin:4px 0">
    <div style="background:#22c55e;width:12px;height:12px;border-radius:50%"></div>Punto potencial B
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin:4px 0">
    <div style="background:#f87171;width:12px;height:12px;border-radius:3px"></div>Tienda afectada
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin:4px 0">
    <div style="background:#4a4a5a;width:12px;height:12px;border-radius:3px"></div>Tienda sin afectación
  </div>
</div>"""
m.get_root().html.add_child(folium.Element(leyenda_html))
st_folium(m, width="100%", height=480, returned_objects=[], key="mapa_canib")


# ── PASO 3: Viviendas en la lente ────────────
st.markdown("<div class='section-header'>Registrar viviendas en la lente (ArcGIS / DANE)</div>",
            unsafe_allow_html=True)
st.markdown("""
<div class='info-box'>
Ingresa las viviendas contadas en ArcGIS dentro de la lente de intersección.<br>
El score usa además: <b>VT</b>, <b>ET</b>, <b>SEG26</b>, <b>TIE26</b>, <b>GENERADOR</b>, 
<b>CONTRIBUCIÓN UM</b> y <b>ME</b> de tu base de datos.
</div>""", unsafe_allow_html=True)

with st.form("form_viviendas"):
    viv_vals = {}
    for i, (_, trow) in enumerate(ta.iterrows()):
        col = COLORES[i % len(COLORES)]

        # Tags de contexto
        seg_color = {"HOGAR":"#60a5fa","RECESO":"#fbbf24","BASE":"#a78bfa"}.get(trow["seg26"],"#888")
        tie_color = {"TMCB":"#4ade80","EXP 2024":"#fbbf24","EXP 2025":"#fb923c","EXP 2026":"#f87171"}.get(trow["tie26"],"#888")
        holgura_me = trow["ventas_um"] - trow["me"]
        holgura_txt = f"<span style='color:{'#4ade80' if holgura_me>=0 else '#f87171'}'>{'▲' if holgura_me>=0 else '▼'} {fmt_s(abs(holgura_me))} vs ME</span>"

        st.markdown(f"""
        <div style='background:#1a1d27;border:1px solid {col}33;border-left:3px solid {col};
             border-radius:10px;padding:12px 16px;margin:8px 0'>
          <div style='font-size:13px;font-weight:600;color:{col};margin-bottom:6px'>{trow["tienda"]}</div>
          <div style='margin-bottom:6px'>
            <span class='tag-pill' style='background:{seg_color}22;color:{seg_color};border:1px solid {seg_color}44'>{trow["seg26"]}</span>
            <span class='tag-pill' style='background:{tie_color}22;color:{tie_color};border:1px solid {tie_color}44'>{trow["tie26"]}</span>
            <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>{trow["generador"]}</span>
          </div>
          <div style='font-size:11px;color:#7a7a8a;line-height:2'>
            d = {fmt_n(trow["distancia_m"])} m &nbsp;|&nbsp; Overlap: {fmt_p(trow["pct_overlap"])} &nbsp;|&nbsp; Lente: {fmt_n(trow["area_lente_m2"])} m²<br>
            VT: {fmt_n(trow["vt"])} viv &nbsp;|&nbsp; ET: {fmt_n(trow["et"])} emp &nbsp;|&nbsp;
            Ventas UM: {fmt_s(trow["ventas_um"])} &nbsp;|&nbsp; {holgura_txt}<br>
            Contribución UM: {fmt_s(trow["contribucion_um"])} &nbsp;|&nbsp; ME: {fmt_s(trow["me"])}
          </div>
        </div>""", unsafe_allow_html=True)

        prev = st.session_state.viv_inputs.get(int(trow["_idx"]), 0)
        viv_vals[int(trow["_idx"])] = st.number_input(
            f"Viviendas en lente — {trow['tienda']}",
            min_value=0, value=prev, step=10,
            key=f"viv_{trow['_idx']}"
        )

    submitted = st.form_submit_button("📊  Calcular reporte final", type="primary", use_container_width=True)

if submitted:
    st.session_state.viv_inputs = viv_vals
    for idx_t, viv in viv_vals.items():
        mask = st.session_state.tiendas_afectadas["_idx"] == idx_t
        st.session_state.tiendas_afectadas.loc[mask, "viv_lente"] = viv
    st.session_state.reporte_listo = True
    st.rerun()

if not st.session_state.reporte_listo:
    st.stop()


# ── REPORTE FINAL ────────────────────────────
ta  = st.session_state.tiendas_afectadas
w_geo     = st.session_state.w_geo
w_viv     = st.session_state.w_viv
w_emp     = st.session_state.w_emp
w_contrib = st.session_state.w_contrib
w_me      = st.session_state.w_me

registros = []
for _, row in ta.iterrows():
    sc = calcular_score_nuevo(
        pct_geo        = row["pct_overlap"],
        viv_lente      = row["viv_lente"],
        vt             = row["vt"],
        et             = row["et"],
        seg26          = row["seg26"],
        tie26          = row["tie26"],
        generador      = row["generador"],
        ventas_um      = row["ventas_um"],
        me             = row["me"],
        contribucion_um= row["contribucion_um"],
        w_geo=w_geo, w_viv=w_viv, w_emp=w_emp, w_contrib=w_contrib, w_me=w_me
    )
    nv_txt, nv_col, nv_cls = nivel_canib(sc)
    f_mad = FACTOR_MADUREZ.get(str(row["tie26"]).strip().upper(), 1.0)
    f_gen = FACTOR_GENERADOR.get(str(row["generador"]).strip().upper(), 1.0)

    registros.append({
        **row.to_dict(),
        "score_pct":      sc,
        "nivel":          nv_txt,
        "nivel_color":    nv_col,
        "nivel_cls":      nv_cls,
        "ventas_riesgo":  round(row["ventas_um"]  * row["pct_overlap"] / 100, 0),
        "trafico_riesgo": round(row["trafico_um"] * row["pct_overlap"] / 100, 0),
        "f_madurez":      f_mad,
        "f_generador":    f_gen,
        "holgura_me":     round(row["ventas_um"] - row["me"], 0),
    })

registros.sort(key=lambda x: x["score_pct"], reverse=True)

total_vr = sum(reg["ventas_riesgo"]  for reg in registros)
total_tr = sum(reg["trafico_riesgo"] for reg in registros)
n_a = sum(1 for reg in registros if reg["nivel"]=="Alto")
n_m = sum(1 for reg in registros if reg["nivel"]=="Medio")
n_b = sum(1 for reg in registros if reg["nivel"]=="Bajo")

st.markdown("---")
st.markdown(f"## Reporte — {st.session_state.nombre_b}")
st.markdown("<div class='section-header'>Resumen global</div>", unsafe_allow_html=True)

c1,c2,c3,c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Tiendas afectadas</div>
    <div class='metric-value'>{len(registros)}</div>
    <div class='metric-sub'>🔴 {n_a} alto &nbsp; 🟡 {n_m} medio &nbsp; 🟢 {n_b} bajo</div>
    </div>""", unsafe_allow_html=True)
with c2:
    sc0 = registros[0]["score_pct"] if registros else 0
    nv0_txt, nv0_col, _ = nivel_canib(sc0)
    st.markdown(f"""<div class='metric-card' style='border-color:{nv0_col}44'>
    <div class='metric-label'>Mayor riesgo</div>
    <div class='metric-value' style='color:{nv0_col}'>{fmt_score(sc0)} — {nv0_txt}</div>
    <div class='metric-sub'>{registros[0]["tienda"] if registros else "—"}</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Ventas totales en riesgo</div>
    <div class='metric-value' style='font-size:18px'>{fmt_s(total_vr)}</div>
    <div class='metric-sub'>estimado mensual combinado</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Tráfico total en riesgo</div>
    <div class='metric-value' style='font-size:18px'>{fmt_n(total_tr)}</div>
    <div class='metric-sub'>visitas/mes estimadas</div>
    </div>""", unsafe_allow_html=True)

# ── Detalle por tienda ────────────────────────
st.markdown("<div class='section-header'>Detalle por tienda</div>", unsafe_allow_html=True)

for reg in registros:
    col      = reg["nivel_color"]
    bar_w    = min(int(reg["score_pct"] / ESCALA_MAX * 100), 100)
    expanded = reg["nivel"] == "Alto"

    seg_color = {"HOGAR":"#60a5fa","RECESO":"#fbbf24","BASE":"#a78bfa"}.get(reg["seg26"],"#888")
    tie_color = {"TMCB":"#4ade80","EXP 2024":"#fbbf24","EXP 2025":"#fb923c","EXP 2026":"#f87171"}.get(reg["tie26"],"#888")

    with st.expander(
        f"{reg['tienda']}  ·  {fmt_score(reg['score_pct'])}  ·  {reg['nivel']}",
        expanded=expanded
    ):
        # Tags
        st.markdown(f"""
        <div style='margin-bottom:10px'>
          <span class='tag-pill' style='background:{seg_color}22;color:{seg_color};border:1px solid {seg_color}44'>{reg["seg26"]}</span>
          <span class='tag-pill' style='background:{tie_color}22;color:{tie_color};border:1px solid {tie_color}44'>{reg["tie26"]}</span>
          <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>{reg["generador"]}</span>
          <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>f_madurez ×{reg["f_madurez"]}</span>
          <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>f_generador ×{reg["f_generador"]}</span>
        </div>""", unsafe_allow_html=True)

        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            st.markdown(f"""<div class='metric-card' style='border-color:{col}44'>
            <div class='metric-label'>Score canibalización</div>
            <div class='metric-value {reg["nivel_cls"]}'>{fmt_score(reg["score_pct"])}</div>
            <div class='score-bar-wrap'><div class='score-bar' style='width:{bar_w}%;background:{col}'></div></div>
            <div class='metric-sub'>{reg["nivel"]} &nbsp;|&nbsp; escala 0–25%</div>
            </div>""", unsafe_allow_html=True)
        with cc2:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Overlap geométrico</div>
            <div class='metric-value'>{fmt_p(reg["pct_overlap"])}</div>
            <div class='metric-sub'>
                d = {fmt_n(reg["distancia_m"])} m<br>
                cuerda = {fmt_n(reg["cuerda_m"])} m &nbsp;|&nbsp; lente = {fmt_n(reg["area_lente_m2"])} m²
            </div>
            </div>""", unsafe_allow_html=True)
        with cc3:
            vl = int(reg["viv_lente"])
            vt_ = reg["vt"]
            pv = (vl / vt_ * 100) if vt_ > 0 and vl > 0 else 0
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Viviendas en lente</div>
            <div class='metric-value'>{fmt_n(vl)}</div>
            <div class='metric-sub'>{fmt_p(pv)} de VT ({fmt_n(vt_)}) &nbsp;|&nbsp; ET: {fmt_n(reg["et"])}</div>
            </div>""", unsafe_allow_html=True)

        cc4, cc5, cc6, cc7 = st.columns(4)
        with cc4:
            holgura = reg["holgura_me"]
            h_col = "#4ade80" if holgura >= 0 else "#f87171"
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Ventas UM vs ME</div>
            <div class='metric-value' style='font-size:17px'>{fmt_s(reg["ventas_um"])}</div>
            <div class='metric-sub'>ME: {fmt_s(reg["me"])} &nbsp;
            <span style='color:{h_col}'>{'▲' if holgura>=0 else '▼'} {fmt_s(abs(holgura))}</span></div>
            </div>""", unsafe_allow_html=True)
        with cc5:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Ventas en riesgo</div>
            <div class='metric-value {reg["nivel_cls"]}' style='font-size:17px'>{fmt_s(reg["ventas_riesgo"])}</div>
            <div class='metric-sub'>estimado/mes</div>
            </div>""", unsafe_allow_html=True)
        with cc6:
            c_um = reg["contribucion_um"]
            c_col = "#4ade80" if c_um > 0 else "#f87171"
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Contribución UM</div>
            <div class='metric-value' style='font-size:17px;color:{c_col}'>{fmt_s(c_um)}</div>
            <div class='metric-sub'>{'✓ positiva' if c_um > 0 else '⚠ negativa'}</div>
            </div>""", unsafe_allow_html=True)
        with cc7:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Tráfico en riesgo</div>
            <div class='metric-value {reg["nivel_cls"]}' style='font-size:17px'>{fmt_n(reg["trafico_riesgo"])}</div>
            <div class='metric-sub'>visitas/mes &nbsp;|&nbsp; base: {fmt_n(reg["trafico_um"])}</div>
            </div>""", unsafe_allow_html=True)

# ── Tabla resumen ─────────────────────────────
st.markdown("<div class='section-header'>Tabla resumen</div>", unsafe_allow_html=True)
df_tabla = pd.DataFrame([{
    "Tienda":            reg["tienda"],
    "SEG26":             reg["seg26"],
    "TIE26":             reg["tie26"],
    "Generador":         reg["generador"],
    "Distancia (m)":     reg["distancia_m"],
    "Overlap (%)":       reg["pct_overlap"],
    "VT":                fmt_n(reg["vt"]),
    "ET":                fmt_n(reg["et"]),
    "Viv. lente":        int(reg["viv_lente"]),
    "Ventas UM":         fmt_s(reg["ventas_um"]),
    "ME":                fmt_s(reg["me"]),
    "Holgura ME":        fmt_s(reg["holgura_me"]),
    "Contribución UM":   fmt_s(reg["contribucion_um"]),
    "Ventas riesgo":     fmt_s(reg["ventas_riesgo"]),
    "Tráfico riesgo":    fmt_n(reg["trafico_riesgo"]),
    "f_madurez":         reg["f_madurez"],
    "f_generador":       reg["f_generador"],
    "Score (0–25%)":     fmt_score(reg["score_pct"]),
    "Nivel":             reg["nivel"],
} for reg in registros])
st.dataframe(df_tabla, use_container_width=True, hide_index=True)

# ── Exportar ──────────────────────────────────
st.markdown("<div class='section-header'>Exportar</div>", unsafe_allow_html=True)
df_exp = pd.DataFrame([{
    "punto_b":           st.session_state.nombre_b,
    "lat_b":             st.session_state.lat_b,
    "lon_b":             st.session_state.lon_b,
    "radio_m":           r,
    "tienda_afectada":   reg["tienda"],
    "seg26":             reg["seg26"],
    "tie26":             reg["tie26"],
    "generador":         reg["generador"],
    "distancia_m":       reg["distancia_m"],
    "pct_overlap":       reg["pct_overlap"],
    "area_lente_m2":     reg["area_lente_m2"],
    "cuerda_m":          reg["cuerda_m"],
    "vt":                reg["vt"],
    "et":                reg["et"],
    "viviendas_lente":   int(reg["viv_lente"]),
    "ventas_um":         reg["ventas_um"],
    "modelo_economico":  reg["me"],
    "holgura_me":        reg["holgura_me"],
    "contribucion_um":   reg["contribucion_um"],
    "ventas_en_riesgo":  reg["ventas_riesgo"],
    "trafico_um":        reg["trafico_um"],
    "trafico_en_riesgo": reg["trafico_riesgo"],
    "factor_madurez":    reg["f_madurez"],
    "factor_generador":  reg["f_generador"],
    "score_pct":         reg["score_pct"],
    "nivel":             reg["nivel"],
} for reg in registros])

buf = BytesIO()
df_exp.to_excel(buf, index=False)
st.download_button(
    "⬇ Descargar reporte Excel",
    buf.getvalue(),
    f"canibalizacion_{st.session_state.nombre_b.replace(' ','_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)
