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
.score-bar-wrap { background: #2a2d3a; border-radius: 6px; height: 8px; margin: 8px 0; overflow: hidden; position:relative; }
.score-bar { height: 8px; border-radius: 6px; }
.me-bar-wrap { background: #2a2d3a; border-radius: 6px; height: 12px; margin: 6px 0; overflow: hidden; position:relative; }
.me-bar { height: 12px; border-radius: 6px; }
.tag-pill {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600; margin: 2px 3px;
}
.riesgo-card {
    border-radius: 12px; padding: 18px 22px; margin: 8px 0;
    border: 1.5px solid;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# LÓGICA DE NEGOCIO
# ─────────────────────────────────────────────

def nivel_me(pct_me):
    """
    El ME es el árbitro del riesgo.
    pct_me = ventas_actuales / ME × 100
    < 83%  → Alto   (tienda vulnerable, cualquier impacto la hunde más)
    83-100 → Medio  (cerca del límite, sin margen de absorción)
    > 100  → Bajo   (tienda sana, puede absorber impacto)
    """
    if pct_me < 83:   return "Alto",  "#f87171", "nivel-alto"
    if pct_me < 100:  return "Medio", "#fbbf24", "nivel-medio"
    return "Bajo", "#4ade80", "nivel-bajo"

def calcular_impacto(ventas_um, trafico_um, contribucion_um, vt, et,
                     pct_geo, viv_lente):
    """
    Cuantifica cuánto se llevaría el punto B de cada variable.
    Usa el overlap geométrico como base de distribución proporcional,
    refinado por viviendas en lente si están disponibles.
    """
    # Factor de distribución de demanda en la lente
    # Si tenemos viviendas reales → las usamos para refinar
    # Si no → usamos solo el overlap geométrico
    if vt > 0 and viv_lente > 0:
        # Ponderación: 60% geométrico + 40% densidad de viviendas
        factor_viv = min(viv_lente / vt, 1.0)
        factor_dist = 0.60 * (pct_geo/100) + 0.40 * factor_viv
    else:
        factor_dist = pct_geo / 100

    factor_dist = min(factor_dist, 1.0)

    return {
        "ventas_canib":      round(ventas_um      * factor_dist, 0),
        "trafico_canib":     round(trafico_um      * factor_dist, 0),
        "contribucion_canib":round(contribucion_um * factor_dist, 0),
        "pct_canib_ventas":  round(factor_dist * 100, 2),
        "factor_dist":       round(factor_dist, 4),
    }

def proyectar_me_post(ventas_um, ventas_canib, me):
    """
    Proyecta las ventas de la tienda A después de la canibalización
    y recalcula su posición respecto al ME.
    """
    ventas_post = ventas_um - ventas_canib
    pct_me_actual = (ventas_um  / me * 100) if me > 0 else 0
    pct_me_post   = (ventas_post / me * 100) if me > 0 else 0
    return {
        "ventas_post":   round(ventas_post, 0),
        "pct_me_actual": round(pct_me_actual, 1),
        "pct_me_post":   round(pct_me_post, 1),
        "delta_me":      round(pct_me_post - pct_me_actual, 1),
    }


# ─────────────────────────────────────────────
# FUNCIONES GEOMÉTRICAS Y UTILITARIAS
# ─────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
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

def fmt_n(n):  return f"{n:,.0f}".replace(",",".")
def fmt_p(p):  return f"{p:.1f}%"
def fmt_s(s):  return f"${s:,.0f}".replace(",",".")

def nombre_tienda(row):
    for c in ["NAME","NOMBRE","name","nombre","ID_TIENDA","id_tienda","CR","cr"]:
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip():
            return str(row[c])
    return f"Tienda #{row.name}"


# ─────────────────────────────────────────────
# ESTADO DE SESIÓN
# ─────────────────────────────────────────────
for k, v in {
    "df": None, "lat_b": 4.6357799, "lon_b": -74.0751250,
    "nombre_b": "Punto nuevo", "radio": 300,
    "tiendas_afectadas": None, "viv_inputs": {}, "reporte_listo": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📍 Canibalización")
    st.markdown("---")
    st.markdown("**Cargar base de tiendas**")

    github_url = st.text_input(
        "URL raw GitHub",
        placeholder="https://raw.githubusercontent.com/.../archivo.xlsx"
    )
    if github_url and st.button("📥 Cargar desde GitHub"):
        try:
            import requests
            resp = requests.get(github_url)
            resp.raise_for_status()
            df_raw = pd.read_excel(BytesIO(resp.content))
            df_raw.columns = [c.strip().upper() for c in df_raw.columns]
            df_raw["LATITUD"]  = pd.to_numeric(df_raw.get("LATITUD",  pd.Series(dtype=float)), errors="coerce")
            df_raw["LONGITUD"] = pd.to_numeric(df_raw.get("LONGITUD", pd.Series(dtype=float)), errors="coerce")
            if "ESTADO" in df_raw.columns:
                df_raw = df_raw[df_raw["ESTADO"].astype(str).str.upper() == "ABIERTA"]
            df_raw = df_raw.dropna(subset=["LATITUD","LONGITUD"]).reset_index(drop=True)
            st.session_state.df = df_raw
            st.session_state.tiendas_afectadas = None
            st.session_state.reporte_listo = False
            st.session_state.viv_inputs = {}
            st.success(f"✓ {len(df_raw)} tiendas cargadas")
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("**— o sube archivo —**")
    uploaded = st.file_uploader("Excel (.xlsx)", type=["xlsx","xls"])
    if uploaded:
        try:
            df_raw = pd.read_excel(uploaded)
            df_raw.columns = [c.strip().upper() for c in df_raw.columns]
            df_raw["LATITUD"]  = pd.to_numeric(df_raw.get("LATITUD",  pd.Series(dtype=float)), errors="coerce")
            df_raw["LONGITUD"] = pd.to_numeric(df_raw.get("LONGITUD", pd.Series(dtype=float)), errors="coerce")
            if "ESTADO" in df_raw.columns:
                df_raw = df_raw[df_raw["ESTADO"].astype(str).str.upper() == "ABIERTA"]
            df_raw = df_raw.dropna(subset=["LATITUD","LONGITUD"]).reset_index(drop=True)
            if st.session_state.df is None or len(df_raw) != len(st.session_state.df):
                st.session_state.df = df_raw
                st.session_state.tiendas_afectadas = None
                st.session_state.reporte_listo = False
                st.session_state.viv_inputs = {}
            st.success(f"✓ {len(df_raw)} tiendas activas")
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("---")
    radio = st.slider("Radio de influencia (m)", 100, 1000, st.session_state.radio, 50)
    if radio != st.session_state.radio:
        st.session_state.radio = radio
        st.session_state.tiendas_afectadas = None
        st.session_state.reporte_listo = False

    st.markdown("---")
    st.markdown("""
    <div style='font-size:11px;color:#5a5a6a;line-height:2.2'>
    <b style='color:#9a9aaa;font-size:12px'>Niveles de riesgo (ME)</b><br>
    🔴 <b style='color:#f87171'>Alto</b> &nbsp; ventas &lt; 83% del ME<br>
    🟡 <b style='color:#fbbf24'>Medio</b> &nbsp; 83% – 100% del ME<br>
    🟢 <b style='color:#4ade80'>Bajo</b> &nbsp; ventas &gt; 100% del ME<br><br>
    <b style='color:#9a9aaa;font-size:12px'>Canibalización</b><br>
    Proyecta cuánto bajarían las ventas<br>
    y dónde quedaría la tienda vs el ME<br>
    después de abrir el punto B.
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
st.markdown("## Análisis de Canibalización")

df = st.session_state.df
r  = st.session_state.radio
ta = st.session_state.tiendas_afectadas

p1 = "step-done"    if df is not None else "step-active"
p2 = "step-done"    if ta is not None else ("step-active" if df is not None else "step-inactive")
p3 = "step-done"    if st.session_state.reporte_listo else ("step-active" if ta is not None else "step-inactive")
st.markdown(f"""
<span class='step-pill {p1}'>1 Cargar BD</span>
<span class='step-pill {p2}'>2 Tiendas en radio</span>
<span class='step-pill {p3}'>3 Viviendas → Reporte</span>
""", unsafe_allow_html=True)
st.markdown("---")


# ── SIN BD ────────────────────────────────────
if df is None:
    st.markdown("""
    <div class='info-box'>
    <b>Sube tu base de tiendas o conéctala desde GitHub.</b><br><br>
    Columnas mínimas: <code>LATITUD</code>, <code>LONGITUD</code><br>
    Para el análisis completo: <code>ME</code>, <code>VENTAS OUM</code>, <code>TRAFICO UM</code>,
    <code>CONTRIBUCION UM</code>, <code>VT</code>, <code>ET</code>, <code>SEG26</code>, <code>TIE26</code>, <code>GENERADOR</code><br>
    Solo se cargan tiendas con <code>ESTADO = ABIERTA</code>
    </div>""", unsafe_allow_html=True)

    # Plantilla
    tmpl = pd.DataFrame({
        "NOMBRE":          ["Centro","Norte","Sur"],
        "ESTADO":          ["ABIERTA","ABIERTA","ABIERTA"],
        "LATITUD":         [4.6383475, 4.6450000, 4.6300000],
        "LONGITUD":        [-74.0787174,-74.0820000,-74.0750000],
        "ME":              [8500000, 7200000, 9100000],
        "VENTAS OUM":      [9200000, 5800000, 10500000],
        "TRAFICO UM":      [4200, 2800, 5100],
        "CONTRIBUCION UM": [320000, -150000, 480000],
        "VT":              [1200, 650, 1800],
        "ET":              [420, 280, 610],
        "SEG26":           ["HOGAR","RECESO","BASE"],
        "TIE26":           ["TMCB","EXP 2025","TMCB"],
        "GENERADOR":       ["ALTA DENSIDAD","COMERCIO/SERVICIO","ALTA DENSIDAD"],
    })
    buf = BytesIO(); tmpl.to_excel(buf, index=False)
    st.download_button("⬇ Descargar plantilla Excel", buf.getvalue(),
                       "plantilla_tiendas.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.stop()


# ── PUNTO B ───────────────────────────────────
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
            pct = pct_overlap(d, r)
            filas.append({
                "_idx":           idx,
                "tienda":         nombre_tienda(row),
                "latitud_A":      float(row["LATITUD"]),
                "longitud_A":     float(row["LONGITUD"]),
                "distancia_m":    round(d, 1),
                "pct_overlap":    round(pct, 2),
                "area_lente_m2":  round(area_lente(d, r), 1),
                "cuerda_m":       round(chord_length(d, r), 1),
                "me":             safe_num(row.get("ME", 0)),
                "ventas_um":      safe_num(row.get("VENTAS OUM", 0)),
                "trafico_um":     safe_num(row.get("TRAFICO UM", 0)),
                "contribucion_um":safe_num(row.get("CONTRIBUCION UM", 0)),
                "vt":             safe_num(row.get("VT", 0)),
                "et":             safe_num(row.get("ET", 0)),
                "seg26":          str(row.get("SEG26", "BASE")),
                "tie26":          str(row.get("TIE26", "TMCB")),
                "generador":      str(row.get("GENERADOR", "—")),
                "viv_lente":      0,
            })

    st.session_state.tiendas_afectadas = pd.DataFrame(filas) if filas else pd.DataFrame()
    st.rerun()

ta = st.session_state.tiendas_afectadas

if ta is None:
    st.info("Ingresa las coordenadas del punto B y pulsa **Identificar tiendas en radio**.")
    st.stop()

if ta.empty:
    st.success(f"✅ Sin canibalización — ninguna tienda dentro del radio de **{r} m**.")
    st.stop()


# ── MAPA ─────────────────────────────────────
lat_b_ = st.session_state.lat_b
lon_b_ = st.session_state.lon_b
COLORES = ["#f87171","#fbbf24","#fb923c","#e879f9","#a78bfa","#34d399","#60a5fa"]

st.markdown(f"<div class='section-header'>{len(ta)} tienda(s) dentro del radio de {r} m</div>",
            unsafe_allow_html=True)

todas_lats = list(df["LATITUD"].dropna()) + [lat_b_]
todas_lons = list(df["LONGITUD"].dropna()) + [lon_b_]
centro = [np.mean(todas_lats), np.mean(todas_lons)]

m = folium.Map(location=centro, zoom_start=15, tiles="CartoDB dark_matter")

def icono_tienda(color, label=""):
    svg = f"""<div style="position:relative;text-align:center">
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
      {'<div style="background:rgba(0,0,0,0.8);color:white;font-size:9px;padding:1px 5px;border-radius:3px;white-space:nowrap;margin-top:2px;font-family:monospace">' + label + '</div>' if label else ''}
    </div>"""
    return folium.DivIcon(html=svg, icon_size=(28,46), icon_anchor=(14,46))

def icono_gris():
    svg = """<div style="background:#4a4a5a;border:1.5px solid #888;border-radius:4px 4px 0 0;
      width:18px;height:14px;display:flex;align-items:center;justify-content:center">
      <svg xmlns='http://www.w3.org/2000/svg' width='9' height='9' viewBox='0 0 24 24'
           fill='none' stroke='#aaa' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'>
        <path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/>
        <polyline points='9 22 9 12 15 12 15 22'/>
      </svg></div>
    <div style="width:0;height:0;border-left:4px solid transparent;
      border-right:4px solid transparent;border-top:5px solid #4a4a5a;margin:0 auto"></div>"""
    return folium.DivIcon(html=svg, icon_size=(18,22), icon_anchor=(9,22))

def icono_punto_b(nombre=""):
    svg = f"""<div style="position:relative;text-align:center">
      <div style="background:#22c55e;border:2.5px solid white;border-radius:50% 50% 50% 0;
        width:32px;height:32px;transform:rotate(-45deg);display:flex;align-items:center;
        justify-content:center;box-shadow:0 3px 8px rgba(0,0,0,0.5)">
        <div style="transform:rotate(45deg)">
          <svg xmlns='http://www.w3.org/2000/svg' width='15' height='15' viewBox='0 0 24 24'
               fill='none' stroke='white' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>
            <circle cx='12' cy='12' r='3'/>
            <path d='M12 2v3M12 19v3M2 12h3M19 12h3'/>
          </svg>
        </div>
      </div>
      {'<div style="background:rgba(34,197,94,0.9);color:white;font-size:9px;padding:1px 6px;border-radius:3px;white-space:nowrap;margin-top:4px;font-family:monospace;font-weight:600">' + nombre[:20] + '</div>' if nombre else ''}
    </div>"""
    return folium.DivIcon(html=svg, icon_size=(32,52), icon_anchor=(16,52))

afect_idx = set(ta["_idx"].tolist())
for _, row in df.iterrows():
    if row.name not in afect_idx:
        folium.Marker(
            location=[row["LATITUD"], row["LONGITUD"]],
            icon=icono_gris(),
            tooltip=folium.Tooltip(f"<b>{nombre_tienda(row)}</b><br>Fuera del radio",
                                   style="font-family:monospace;font-size:12px")
        ).add_to(m)

for i, (_, trow) in enumerate(ta.iterrows()):
    col = COLORES[i % len(COLORES)]
    # Calcular % ME actual para mostrar en tooltip
    pct_me_a = (trow["ventas_um"] / trow["me"] * 100) if trow["me"] > 0 else 0
    nv_me, _, _ = nivel_me(pct_me_a)

    folium.Circle(
        location=[trow["latitud_A"], trow["longitud_A"]],
        radius=r, color=col, weight=1.5,
        fill=True, fill_color=col, fill_opacity=0.12,
    ).add_to(m)
    folium.PolyLine(
        [[trow["latitud_A"], trow["longitud_A"]], [lat_b_, lon_b_]],
        color=col, weight=2, dash_array="8 4",
        tooltip=folium.Tooltip(f"d = <b>{trow['distancia_m']:.0f} m</b>",
                               style="font-family:monospace;font-size:12px")
    ).add_to(m)
    folium.Marker(
        location=[trow["latitud_A"], trow["longitud_A"]],
        icon=icono_tienda(col, trow["tienda"][:12]),
        tooltip=folium.Tooltip(
            f"<b>{trow['tienda']}</b><br>"
            f"Overlap: {trow['pct_overlap']:.1f}% | d: {trow['distancia_m']:.0f} m<br>"
            f"Ventas/ME: {pct_me_a:.1f}% → Riesgo {nv_me}<br>"
            f"SEG: {trow['seg26']} | TIE: {trow['tie26']}",
            style="font-family:monospace;font-size:12px")
    ).add_to(m)

folium.Circle(location=[lat_b_, lon_b_], radius=r,
              color="#22c55e", weight=2, fill=True,
              fill_color="#22c55e", fill_opacity=0.08, dash_array="6 3").add_to(m)
folium.Marker(
    location=[lat_b_, lon_b_],
    icon=icono_punto_b(st.session_state.nombre_b),
    tooltip=folium.Tooltip(
        f"<b>{st.session_state.nombre_b}</b><br>Radio: {r} m | Tiendas en radio: {len(ta)}",
        style="font-family:monospace;font-size:12px")
).add_to(m)

leyenda_html = """<div style="position:fixed;bottom:20px;right:10px;z-index:1000;
  background:rgba(15,17,23,0.92);border:1px solid #2a2d3a;border-radius:8px;
  padding:10px 14px;font-family:monospace;font-size:11px;color:#c8c6bf">
  <div style="font-weight:600;margin-bottom:6px;color:#e8e6df">Leyenda</div>
  <div style="display:flex;align-items:center;gap:8px;margin:3px 0">
    <div style="background:#22c55e;width:12px;height:12px;border-radius:50%"></div>Punto potencial B
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin:3px 0">
    <div style="background:#f87171;width:12px;height:12px;border-radius:3px"></div>Tienda afectada
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin:3px 0">
    <div style="background:#4a4a5a;width:12px;height:12px;border-radius:3px"></div>Sin afectación
  </div>
</div>"""
m.get_root().html.add_child(folium.Element(leyenda_html))
st_folium(m, width="100%", height=480, returned_objects=[], key="mapa_canib")


# ── PASO 3: Viviendas en la lente ─────────────
st.markdown("<div class='section-header'>Registrar viviendas en la lente (ArcGIS / DANE 2018)</div>",
            unsafe_allow_html=True)
st.markdown("""
<div class='info-box'>
Ingresa las viviendas contadas visualmente en ArcGIS dentro de la lente de cada tienda.
Si dejas 0, el impacto se calcula solo con el overlap geométrico.
</div>""", unsafe_allow_html=True)

with st.form("form_viviendas"):
    viv_vals = {}
    for i, (_, trow) in enumerate(ta.iterrows()):
        col = COLORES[i % len(COLORES)]
        pct_me_a = (trow["ventas_um"] / trow["me"] * 100) if trow["me"] > 0 else 0
        nv_txt, nv_col, _ = nivel_me(pct_me_a)
        seg_c = {"HOGAR":"#60a5fa","RECESO":"#fbbf24","BASE":"#a78bfa"}.get(trow["seg26"],"#888")
        tie_c = {"TMCB":"#4ade80","EXP 2024":"#fbbf24","EXP 2025":"#fb923c","EXP 2026":"#f87171"}.get(trow["tie26"],"#888")

        st.markdown(f"""
        <div style='background:#1a1d27;border:1px solid {col}33;border-left:3px solid {col};
             border-radius:10px;padding:12px 16px;margin:8px 0'>
          <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px'>
            <span style='font-size:13px;font-weight:600;color:{col}'>{trow["tienda"]}</span>
            <span style='font-size:12px;font-weight:600;color:{nv_col}'>Riesgo actual: {nv_txt} ({pct_me_a:.1f}% ME)</span>
          </div>
          <div style='margin-bottom:6px'>
            <span class='tag-pill' style='background:{seg_c}22;color:{seg_c};border:1px solid {seg_c}44'>{trow["seg26"]}</span>
            <span class='tag-pill' style='background:{tie_c}22;color:{tie_c};border:1px solid {tie_c}44'>{trow["tie26"]}</span>
            <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>{trow["generador"]}</span>
          </div>
          <div style='font-size:11px;color:#7a7a8a;line-height:2'>
            Overlap: <b style='color:#e8e6df'>{fmt_p(trow["pct_overlap"])}</b> &nbsp;|&nbsp;
            d = {fmt_n(trow["distancia_m"])} m &nbsp;|&nbsp;
            Lente: {fmt_n(trow["area_lente_m2"])} m² &nbsp;|&nbsp;
            VT: {fmt_n(trow["vt"])} viv<br>
            Ventas UM: <b style='color:#e8e6df'>{fmt_s(trow["ventas_um"])}</b> &nbsp;|&nbsp;
            ME: {fmt_s(trow["me"])} &nbsp;|&nbsp;
            Contribución: <span style='color:{"#4ade80" if trow["contribucion_um"]>=0 else "#f87171"}'>{fmt_s(trow["contribucion_um"])}</span>
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
        st.session_state.tiendas_afectadas.loc[
            st.session_state.tiendas_afectadas["_idx"] == idx_t, "viv_lente"
        ] = viv
    st.session_state.reporte_listo = True
    st.rerun()

if not st.session_state.reporte_listo:
    st.stop()


# ── REPORTE FINAL ──────────────────────────────
ta = st.session_state.tiendas_afectadas

registros = []
for _, row in ta.iterrows():
    # 1. Nivel de riesgo ACTUAL (solo ME, antes de canibalización)
    pct_me_actual = (row["ventas_um"] / row["me"] * 100) if row["me"] > 0 else 0
    nv_txt, nv_col, nv_cls = nivel_me(pct_me_actual)

    # 2. Cuantificar impacto de la canibalización
    imp = calcular_impacto(
        ventas_um      = row["ventas_um"],
        trafico_um     = row["trafico_um"],
        contribucion_um= row["contribucion_um"],
        vt             = row["vt"],
        et             = row["et"],
        pct_geo        = row["pct_overlap"],
        viv_lente      = row["viv_lente"],
    )

    # 3. Proyectar posición post-canibalización vs ME
    proy = proyectar_me_post(row["ventas_um"], imp["ventas_canib"], row["me"])

    # 4. Nivel de riesgo POST (después del impacto)
    nv_post_txt, nv_post_col, nv_post_cls = nivel_me(proy["pct_me_post"])

    registros.append({
        **row.to_dict(),
        # Riesgo actual
        "pct_me_actual":  proy["pct_me_actual"],
        "nivel_actual":   nv_txt,
        "nivel_color":    nv_col,
        "nivel_cls":      nv_cls,
        # Impacto canibalización
        "ventas_canib":      imp["ventas_canib"],
        "trafico_canib":     imp["trafico_canib"],
        "contribucion_canib":imp["contribucion_canib"],
        "pct_canib_ventas":  imp["pct_canib_ventas"],
        "factor_dist":       imp["factor_dist"],
        # Proyección post
        "ventas_post":    proy["ventas_post"],
        "pct_me_post":    proy["pct_me_post"],
        "delta_me":       proy["delta_me"],
        "nivel_post":     nv_post_txt,
        "nivel_post_col": nv_post_col,
        "nivel_post_cls": nv_post_cls,
        # Empeora de nivel?
        "empeora": nv_txt != nv_post_txt and (
            (nv_txt == "Bajo"  and nv_post_txt in ["Medio","Alto"]) or
            (nv_txt == "Medio" and nv_post_txt == "Alto")
        ),
    })

# Ordenar: primero los que empeoran de nivel, luego por delta_me descendente
registros.sort(key=lambda x: (not x["empeora"], x["delta_me"]))

total_vc = sum(reg["ventas_canib"]  for reg in registros)
total_tc = sum(reg["trafico_canib"] for reg in registros)
n_a = sum(1 for reg in registros if reg["nivel_actual"]=="Alto")
n_m = sum(1 for reg in registros if reg["nivel_actual"]=="Medio")
n_b = sum(1 for reg in registros if reg["nivel_actual"]=="Bajo")
n_empeoran = sum(1 for reg in registros if reg["empeora"])

st.markdown("---")
st.markdown(f"## Reporte — {st.session_state.nombre_b}")

# ── Resumen global ─────────────────────────────
st.markdown("<div class='section-header'>Resumen global</div>", unsafe_allow_html=True)
c1,c2,c3,c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Tiendas afectadas</div>
    <div class='metric-value'>{len(registros)}</div>
    <div class='metric-sub'>🔴 {n_a} alto &nbsp;🟡 {n_m} medio &nbsp;🟢 {n_b} bajo (hoy)</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class='metric-card' style='border-color:#f87171{44}'>
    <div class='metric-label'>Empeoran de nivel</div>
    <div class='metric-value' style='color:{"#f87171" if n_empeoran>0 else "#4ade80"}'>{n_empeoran}</div>
    <div class='metric-sub'>tiendas que bajan de categoría de riesgo post-apertura</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Ventas totales canibalizadas</div>
    <div class='metric-value' style='font-size:18px'>{fmt_s(total_vc)}</div>
    <div class='metric-sub'>estimado mensual combinado</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Tráfico total canibalizado</div>
    <div class='metric-value' style='font-size:18px'>{fmt_n(total_tc)}</div>
    <div class='metric-sub'>visitas/mes estimadas</div>
    </div>""", unsafe_allow_html=True)


# ── Detalle por tienda ─────────────────────────
st.markdown("<div class='section-header'>Detalle por tienda</div>", unsafe_allow_html=True)

for reg in registros:
    col_ac  = reg["nivel_color"]
    col_po  = reg["nivel_post_col"]
    seg_c   = {"HOGAR":"#60a5fa","RECESO":"#fbbf24","BASE":"#a78bfa"}.get(reg["seg26"],"#888")
    tie_c   = {"TMCB":"#4ade80","EXP 2024":"#fbbf24","EXP 2025":"#fb923c","EXP 2026":"#f87171"}.get(reg["tie26"],"#888")
    expanded = reg["empeora"] or reg["nivel_actual"] == "Alto"

    # Título del expander con flecha si empeora
    arrow = " ⚠ empeora de nivel" if reg["empeora"] else ""
    with st.expander(
        f"{reg['tienda']}  ·  Hoy: {reg['nivel_actual']} ({reg['pct_me_actual']:.1f}% ME)  →  Post: {reg['nivel_post']} ({reg['pct_me_post']:.1f}% ME){arrow}",
        expanded=expanded
    ):
        # Tags contexto
        st.markdown(f"""<div style='margin-bottom:10px'>
          <span class='tag-pill' style='background:{seg_c}22;color:{seg_c};border:1px solid {seg_c}44'>{reg["seg26"]}</span>
          <span class='tag-pill' style='background:{tie_c}22;color:{tie_c};border:1px solid {tie_c}44'>{reg["tie26"]}</span>
          <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>{reg["generador"]}</span>
          <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>overlap {fmt_p(reg["pct_overlap"])}</span>
          <span class='tag-pill' style='background:#ffffff11;color:#aaa;border:1px solid #333'>d = {fmt_n(reg["distancia_m"])} m</span>
        </div>""", unsafe_allow_html=True)

        # ── Tarjeta ME: antes vs después ──────
        bw_ac = min(int(reg["pct_me_actual"]/150*100),100)
        bw_po = min(int(reg["pct_me_post"] /150*100),100)
        # Marcadores en la barra: 83% y 100%
        marca83  = int(83/150*100)
        marca100 = int(100/150*100)

        st.markdown(f"""
        <div style='background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;padding:16px 20px;margin:8px 0'>
          <div style='font-size:11px;color:#7a7a8a;text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px'>
            Posición vs Modelo Económico (ME = {fmt_s(reg["me"])})
          </div>
          <div style='display:grid;grid-template-columns:1fr 1fr;gap:16px'>

            <div>
              <div style='font-size:11px;color:#7a7a8a;margin-bottom:4px'>ANTES (actual)</div>
              <div style='font-size:20px;font-weight:600;color:{col_ac}'>{reg["pct_me_actual"]:.1f}%</div>
              <div style='font-size:12px;color:#7a7a8a;margin-bottom:6px'>{fmt_s(reg["ventas_um"])} / {fmt_s(reg["me"])}</div>
              <div style='position:relative;background:#2a2d3a;border-radius:6px;height:10px;overflow:visible'>
                <div style='height:10px;border-radius:6px;width:{bw_ac}%;background:{col_ac}'></div>
                <div style='position:absolute;top:-4px;left:{marca83}%;width:1.5px;height:18px;background:#fbbf24;opacity:.8'></div>
                <div style='position:absolute;top:-4px;left:{marca100}%;width:1.5px;height:18px;background:#4ade80;opacity:.8'></div>
              </div>
              <div style='font-size:10px;color:#7a7a8a;margin-top:3px'>Riesgo: <b style='color:{col_ac}'>{reg["nivel_actual"]}</b></div>
            </div>

            <div>
              <div style='font-size:11px;color:#7a7a8a;margin-bottom:4px'>DESPUÉS (post-apertura B)</div>
              <div style='font-size:20px;font-weight:600;color:{col_po}'>{reg["pct_me_post"]:.1f}%</div>
              <div style='font-size:12px;color:#7a7a8a;margin-bottom:6px'>{fmt_s(reg["ventas_post"])} / {fmt_s(reg["me"])}
                &nbsp;<span style='color:{"#f87171"}'>{fmt_p(reg["delta_me"])} ME</span>
              </div>
              <div style='position:relative;background:#2a2d3a;border-radius:6px;height:10px;overflow:visible'>
                <div style='height:10px;border-radius:6px;width:{bw_po}%;background:{col_po}'></div>
                <div style='position:absolute;top:-4px;left:{marca83}%;width:1.5px;height:18px;background:#fbbf24;opacity:.8'></div>
                <div style='position:absolute;top:-4px;left:{marca100}%;width:1.5px;height:18px;background:#4ade80;opacity:.8'></div>
              </div>
              <div style='font-size:10px;color:#7a7a8a;margin-top:3px'>Riesgo: <b style='color:{col_po}'>{reg["nivel_post"]}</b>
                {"&nbsp;⚠ empeora" if reg["empeora"] else ""}
              </div>
            </div>

          </div>
          <div style='font-size:10px;color:#5a5a6a;margin-top:8px'>
            ▏ 83% — umbral medio &nbsp;&nbsp; ▏ 100% — umbral bajo
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Métricas de impacto ───────────────
        cc1,cc2,cc3,cc4 = st.columns(4)
        with cc1:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Ventas canibalizadas</div>
            <div class='metric-value nivel-alto' style='font-size:17px'>{fmt_s(reg["ventas_canib"])}</div>
            <div class='metric-sub'>{fmt_p(reg["pct_canib_ventas"])} de las ventas de la tienda</div>
            </div>""", unsafe_allow_html=True)
        with cc2:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Tráfico canibalizado</div>
            <div class='metric-value nivel-alto' style='font-size:17px'>{fmt_n(reg["trafico_canib"])}</div>
            <div class='metric-sub'>visitas/mes | base: {fmt_n(reg["trafico_um"])}</div>
            </div>""", unsafe_allow_html=True)
        with cc3:
            c_post = reg["contribucion_um"] - reg["contribucion_canib"]
            c_col  = "#4ade80" if c_post > 0 else "#f87171"
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Contribución post</div>
            <div class='metric-value' style='font-size:17px;color:{c_col}'>{fmt_s(c_post)}</div>
            <div class='metric-sub'>actual: {fmt_s(reg["contribucion_um"])} | canib: -{fmt_s(reg["contribucion_canib"])}</div>
            </div>""", unsafe_allow_html=True)
        with cc4:
            vl = int(reg["viv_lente"])
            vt = reg["vt"]
            pv = (vl/vt*100) if vt > 0 and vl > 0 else 0
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Viviendas en lente</div>
            <div class='metric-value' style='font-size:17px'>{fmt_n(vl)}</div>
            <div class='metric-sub'>{fmt_p(pv)} de VT ({fmt_n(vt)})</div>
            </div>""", unsafe_allow_html=True)


# ── Tabla resumen ──────────────────────────────
st.markdown("<div class='section-header'>Tabla resumen</div>", unsafe_allow_html=True)
df_tabla = pd.DataFrame([{
    "Tienda":          reg["tienda"],
    "SEG26":           reg["seg26"],
    "TIE26":           reg["tie26"],
    "Overlap (%)":     reg["pct_overlap"],
    "Viv. lente":      int(reg["viv_lente"]),
    "Ventas UM":       fmt_s(reg["ventas_um"]),
    "ME":              fmt_s(reg["me"]),
    "% ME actual":     f"{reg['pct_me_actual']:.1f}%",
    "Nivel actual":    reg["nivel_actual"],
    "Ventas canib.":   fmt_s(reg["ventas_canib"]),
    "% canib.":        fmt_p(reg["pct_canib_ventas"]),
    "Ventas post":     fmt_s(reg["ventas_post"]),
    "% ME post":       f"{reg['pct_me_post']:.1f}%",
    "Nivel post":      reg["nivel_post"],
    "Δ ME":            f"{reg['delta_me']:.1f}%",
    "Empeora":         "⚠ Sí" if reg["empeora"] else "No",
} for reg in registros])
st.dataframe(df_tabla, use_container_width=True, hide_index=True)


# ── Exportar ───────────────────────────────────
st.markdown("<div class='section-header'>Exportar</div>", unsafe_allow_html=True)
df_exp = pd.DataFrame([{
    "punto_b":           st.session_state.nombre_b,
    "lat_b":             st.session_state.lat_b,
    "lon_b":             st.session_state.lon_b,
    "radio_m":           r,
    "tienda":            reg["tienda"],
    "seg26":             reg["seg26"],
    "tie26":             reg["tie26"],
    "generador":         reg["generador"],
    "distancia_m":       reg["distancia_m"],
    "pct_overlap":       reg["pct_overlap"],
    "area_lente_m2":     reg["area_lente_m2"],
    "cuerda_m":          reg["cuerda_m"],
    "vt":                reg["vt"],
    "et":                reg["et"],
    "viv_lente":         int(reg["viv_lente"]),
    "me":                reg["me"],
    "ventas_um":         reg["ventas_um"],
    "pct_me_actual":     reg["pct_me_actual"],
    "nivel_actual":      reg["nivel_actual"],
    "ventas_canib":      reg["ventas_canib"],
    "pct_canib_ventas":  reg["pct_canib_ventas"],
    "ventas_post":       reg["ventas_post"],
    "pct_me_post":       reg["pct_me_post"],
    "delta_me_pct":      reg["delta_me"],
    "nivel_post":        reg["nivel_post"],
    "empeora_nivel":     reg["empeora"],
    "trafico_um":        reg["trafico_um"],
    "trafico_canib":     reg["trafico_canib"],
    "contribucion_um":   reg["contribucion_um"],
    "contribucion_canib":reg["contribucion_canib"],
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
