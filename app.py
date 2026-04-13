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
</style>
""", unsafe_allow_html=True)


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

def tendencia_lineal(serie):
    if len(serie) < 2: return 0.0
    x = np.arange(len(serie), dtype=float)
    prom = np.mean(serie)
    if prom == 0: return 0.0
    return float(np.polyfit(x, serie, 1)[0]) / prom

def factor_tendencia(tend):
    if tend >  0.05: return 1.3
    if tend >  0.01: return 1.1
    if tend > -0.01: return 1.0
    if tend > -0.05: return 0.85
    return 0.7

def calcular_score(pct_geo, viv_lente, viv_A, tend_v, tend_t, w1, w2, w3):
    c_geo  = pct_geo / 100
    c_viv  = (viv_lente / viv_A) if viv_A > 0 else c_geo
    c_tend = (abs(tend_v) + abs(tend_t)) / 2
    ft = factor_tendencia((tend_v + tend_t) / 2)
    return min((w1*c_geo + w2*c_viv + w3*c_tend) * ft, 1.0)

def nivel_canib(score):
    if score < 0.15: return "Bajo",  "#4ade80", "nivel-bajo"
    if score < 0.35: return "Medio", "#fbbf24", "nivel-medio"
    return "Alto", "#f87171", "nivel-alto"

def fmt_n(n):  return f"{n:,.0f}".replace(",", ".")
def fmt_p(p):  return f"{p:.1f}%"
def fmt_s(s):  return f"${s:,.0f}".replace(",", ".")

def nombre_tienda(row):
    for c in ["nombre", "id_tienda", "tienda", "name"]:
        if c in row.index and pd.notna(row[c]):
            return str(row[c])
    return f"Tienda #{row.name}"

def detectar_series(df, keywords):
    return sorted([c for c in df.columns if any(k in c.lower() for k in keywords)])

def serie_tienda(row, cols):
    vals = [pd.to_numeric(row.get(c), errors="coerce") for c in cols]
    return [v for v in vals if pd.notna(v)]


# ─────────────────────────────────────────────
# ESTADO DE SESIÓN
# ─────────────────────────────────────────────
defaults = {
    "df": None, "vcols": [], "tcols": [],
    "lat_b": 4.6357799, "lon_b": -74.0751250,
    "nombre_b": "Punto nuevo", "radio": 300,
    "tiendas_afectadas": None,
    "viv_inputs": {},
    "reporte_listo": False,
    "w1": 0.45, "w2": 0.35, "w3": 0.20,
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
    uploaded = st.file_uploader("Excel o CSV", type=["xlsx","xls","csv"])

    if uploaded:
        try:
            df_raw = (pd.read_excel(uploaded)
                      if uploaded.name.endswith(("xlsx","xls"))
                      else pd.read_csv(uploaded))
            df_raw.columns = [c.strip().lower().replace(" ","_") for c in df_raw.columns]
            for col in ["latitud","longitud"]:
                if col not in df_raw.columns:
                    st.error(f"Falta columna: {col}"); st.stop()
            df_raw["latitud"]  = pd.to_numeric(df_raw["latitud"],  errors="coerce")
            df_raw["longitud"] = pd.to_numeric(df_raw["longitud"], errors="coerce")
            df_raw = df_raw.dropna(subset=["latitud","longitud"]).reset_index(drop=True)

            vcols = detectar_series(df_raw, ["venta","sale","ingreso"])
            tcols = detectar_series(df_raw, ["trafico","tráfico","traffic","visita"])

            if (st.session_state.df is None or
                    len(df_raw) != len(st.session_state.df)):
                st.session_state.df    = df_raw
                st.session_state.vcols = vcols
                st.session_state.tcols = tcols
                st.session_state.tiendas_afectadas = None
                st.session_state.reporte_listo     = False
                st.session_state.viv_inputs        = {}

            st.success(f"✓ {len(df_raw)} tiendas cargadas")
            if vcols: st.caption(f"Ventas: {', '.join(vcols)}")
            if tcols: st.caption(f"Tráfico: {', '.join(tcols)}")
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
    with st.expander("Pesos del score"):
        w1 = st.slider("Peso geométrico",  0.0, 1.0, st.session_state.w1, 0.05)
        w2 = st.slider("Peso viviendas",   0.0, 1.0, st.session_state.w2, 0.05)
        w3 = st.slider("Peso tendencia",   0.0, 1.0, st.session_state.w3, 0.05)
        st.session_state.w1 = w1
        st.session_state.w2 = w2
        st.session_state.w3 = w3
        if abs(w1+w2+w3-1.0) > 0.01:
            st.warning(f"Suman {w1+w2+w3:.2f} — deben sumar 1.0")

    st.markdown("---")
    st.markdown("""
    <div style='font-size:11px;color:#5a5a6a;line-height:1.8'>
    🟢 <b style='color:#7a7a8a'>Bajo</b> &nbsp; score &lt; 0.15<br>
    🟡 <b style='color:#7a7a8a'>Medio</b> &nbsp; 0.15 – 0.35<br>
    🔴 <b style='color:#7a7a8a'>Alto</b> &nbsp; score &gt; 0.35
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
st.markdown("## Análisis de Canibalización")

df    = st.session_state.df
vcols = st.session_state.vcols
tcols = st.session_state.tcols
r     = st.session_state.radio
ta    = st.session_state.tiendas_afectadas

# Pills de progreso
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
    <b>Sube tu base de tiendas desde el panel lateral para comenzar.</b><br><br>
    Columnas mínimas requeridas: <code>latitud</code>, <code>longitud</code><br>
    Ventas: columnas con "venta" → <code>venta_m1 … venta_m6</code><br>
    Tráfico: columnas con "trafico" → <code>trafico_m1 … trafico_m6</code><br>
    Opcionales: <code>nombre</code> / <code>id_tienda</code>, <code>viviendas_radio</code>
    </div>""", unsafe_allow_html=True)

    tmpl = pd.DataFrame({
        "id_tienda": ["T001","T002","T003"],
        "nombre":    ["Centro","Norte","Sur"],
        "latitud":   [4.6383475, 4.6450000, 4.6300000],
        "longitud":  [-74.0787174,-74.0820000,-74.0750000],
        "venta_m1":  [12500000,9800000,15200000],
        "venta_m2":  [11800000,10200000,14800000],
        "venta_m3":  [13100000,9500000,15600000],
        "venta_m4":  [12900000,10800000,15100000],
        "venta_m5":  [13400000,11200000,15900000],
        "venta_m6":  [14000000,11500000,16200000],
        "trafico_m1":[4200,3100,5800],
        "trafico_m2":[4000,3300,5600],
        "trafico_m3":[4500,3000,6100],
        "trafico_m4":[4300,3500,5900],
        "trafico_m5":[4600,3700,6300],
        "trafico_m6":[4900,3800,6500],
        "viviendas_radio":[1200,850,2100],
    })
    buf = BytesIO(); tmpl.to_excel(buf, index=False)
    st.download_button("⬇ Descargar plantilla Excel", buf.getvalue(),
                       "plantilla_tiendas.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
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
        d = haversine(row["latitud"], row["longitud"], lat_b, lon_b)
        if d < 2 * r:
            pct = pct_overlap(d, r)
            al  = area_lente(d, r)
            ch  = chord_length(d, r)
            vs  = serie_tienda(row, vcols)
            ts  = serie_tienda(row, tcols)
            vp  = float(np.mean(vs)) if vs else 0.0
            tp  = float(np.mean(ts)) if ts else 0.0
            tv  = tendencia_lineal(vs) if len(vs) >= 2 else 0.0
            tt  = tendencia_lineal(ts) if len(ts) >= 2 else 0.0
            viv_A = float(pd.to_numeric(row.get("viviendas_radio", 0), errors="coerce") or 0)
            filas.append({
                "_idx":          idx,
                "tienda":        nombre_tienda(row),
                "latitud_A":     float(row["latitud"]),
                "longitud_A":    float(row["longitud"]),
                "distancia_m":   round(d, 1),
                "pct_overlap":   round(pct, 2),
                "area_lente_m2": round(al, 1),
                "cuerda_m":      round(ch, 1),
                "venta_prom":    round(vp, 0),
                "trafico_prom":  round(tp, 0),
                "tend_ventas":   round(tv, 4),
                "tend_trafico":  round(tt, 4),
                "viv_A":         int(viv_A),
                "viv_lente":     0,
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

m = folium.Map(
    location=[(df["latitud"].mean()+lat_b_)/2, (df["longitud"].mean()+lon_b_)/2],
    zoom_start=15, tiles="CartoDB dark_matter"
)

# Tiendas NO afectadas (gris)
afect_idx = set(ta["_idx"].tolist())
for _, row in df.iterrows():
    if row.name not in afect_idx:
        folium.CircleMarker(
            location=[row["latitud"], row["longitud"]],
            radius=4, color="#3a3a4a", fill=True,
            fill_color="#3a3a4a", fill_opacity=0.6,
            tooltip=nombre_tienda(row)
        ).add_to(m)

# Tiendas afectadas con su radio y línea a B
for i, (_, trow) in enumerate(ta.iterrows()):
    col = COLORES[i % len(COLORES)]
    folium.Circle(
        location=[trow["latitud_A"], trow["longitud_A"]],
        radius=r, color=col, fill=True, fill_color=col, fill_opacity=0.10,
        tooltip=f"{trow['tienda']} — overlap {trow['pct_overlap']:.1f}%"
    ).add_to(m)
    folium.CircleMarker(
        location=[trow["latitud_A"], trow["longitud_A"]],
        radius=7, color=col, fill=True, fill_color=col,
        tooltip=trow["tienda"]
    ).add_to(m)
    folium.PolyLine(
        [[trow["latitud_A"], trow["longitud_A"]], [lat_b_, lon_b_]],
        color=col, weight=1.5, dash_array="6",
        tooltip=f"d = {trow['distancia_m']:.0f} m"
    ).add_to(m)

# Punto B
folium.Circle(
    location=[lat_b_, lon_b_], radius=r,
    color="#22c55e", fill=True, fill_color="#22c55e", fill_opacity=0.10,
    tooltip=f"Punto B: {st.session_state.nombre_b}"
).add_to(m)
folium.CircleMarker(
    location=[lat_b_, lon_b_], radius=9,
    color="#22c55e", fill=True, fill_color="#22c55e",
    tooltip=f"B: {st.session_state.nombre_b}"
).add_to(m)

st_folium(m, width=None, height=440, returned_objects=[])


# ── PASO 3: Viviendas por tienda ─────────────
st.markdown("<div class='section-header'>Registrar viviendas en la lente (ArcGIS / DANE 2018)</div>",
            unsafe_allow_html=True)
st.markdown("""
<div class='info-box'>
Para cada tienda afectada ingresa las viviendas que contaste en ArcGIS 
dentro de la lente de intersección. Si dejas 0, el score usa solo geometría y tendencia.
</div>""", unsafe_allow_html=True)

with st.form("form_viviendas"):
    viv_vals = {}
    for i, (_, trow) in enumerate(ta.iterrows()):
        col = COLORES[i % len(COLORES)]
        st.markdown(f"""
        <div style='background:#1a1d27;border:1px solid {col}33;border-left:3px solid {col};
             border-radius:10px;padding:12px 16px;margin:8px 0'>
          <div style='font-size:13px;font-weight:600;color:{col};margin-bottom:3px'>{trow["tienda"]}</div>
          <div style='font-size:11px;color:#7a7a8a'>
            d = {fmt_n(trow["distancia_m"])} m &nbsp;|&nbsp;
            Overlap: {fmt_p(trow["pct_overlap"])} &nbsp;|&nbsp;
            Cuerda: {fmt_n(trow["cuerda_m"])} m &nbsp;|&nbsp;
            Lente: {fmt_n(trow["area_lente_m2"])} m²
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
ta = st.session_state.tiendas_afectadas
w1 = st.session_state.w1
w2 = st.session_state.w2
w3 = st.session_state.w3

registros = []
for _, row in ta.iterrows():
    viv_A_calc = (row["viv_A"] if row["viv_A"] > 0
                  else (row["viv_lente"] / (row["pct_overlap"]/100)
                        if row["pct_overlap"] > 0 else 1.0))
    sc = calcular_score(row["pct_overlap"], row["viv_lente"], viv_A_calc,
                        row["tend_ventas"], row["tend_trafico"], w1, w2, w3)
    nv_txt, nv_col, nv_cls = nivel_canib(sc)
    ft = factor_tendencia((row["tend_ventas"]+row["tend_trafico"])/2)
    registros.append({
        **row.to_dict(),
        "score":          round(sc, 4),
        "nivel":          nv_txt,
        "nivel_color":    nv_col,
        "nivel_cls":      nv_cls,
        "ventas_riesgo":  round(row["venta_prom"]  * row["pct_overlap"]/100, 0),
        "trafico_riesgo": round(row["trafico_prom"] * row["pct_overlap"]/100, 0),
        "ft":             ft,
    })

registros.sort(key=lambda x: x["score"], reverse=True)

# Resumen global
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
    sc0 = registros[0]["score"] if registros else 0
    nv0_txt, nv0_col, nv0_cls = nivel_canib(sc0)
    st.markdown(f"""<div class='metric-card' style='border-color:{nv0_col}44'>
    <div class='metric-label'>Mayor riesgo</div>
    <div class='metric-value {nv0_cls}'>{sc0:.3f} — {nv0_txt}</div>
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

# Detalle por tienda
st.markdown("<div class='section-header'>Detalle por tienda</div>", unsafe_allow_html=True)

for reg in registros:
    col = reg["nivel_color"]
    bar_w = min(int(reg["score"]/0.5*100), 100)
    expanded = reg["nivel"] == "Alto"

    with st.expander(
        f"{reg['tienda']}  ·  Score {reg['score']:.3f}  ·  {reg['nivel']}",
        expanded=expanded
    ):
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            st.markdown(f"""<div class='metric-card' style='border-color:{col}44'>
            <div class='metric-label'>Score canibalización</div>
            <div class='metric-value {reg["nivel_cls"]}'>{reg["score"]:.3f}</div>
            <div class='score-bar-wrap'><div class='score-bar' style='width:{bar_w}%;background:{col}'></div></div>
            <div class='metric-sub'>{reg["nivel"]} &nbsp;|&nbsp; factor tend. ×{reg["ft"]}</div>
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
            va = int(reg["viv_A"])
            pv = (vl/va*100) if va > 0 and vl > 0 else 0
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Viviendas en lente</div>
            <div class='metric-value'>{fmt_n(vl)}</div>
            <div class='metric-sub'>{fmt_p(pv)} del radio de A</div>
            </div>""", unsafe_allow_html=True)

        cc4,cc5,cc6,cc7 = st.columns(4)
        with cc4:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Venta prom. 6m</div>
            <div class='metric-value' style='font-size:17px'>{fmt_s(reg["venta_prom"])}</div>
            <div class='metric-sub'>tendencia {reg["tend_ventas"]*100:+.1f}%/mes</div>
            </div>""", unsafe_allow_html=True)
        with cc5:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Ventas en riesgo</div>
            <div class='metric-value {reg["nivel_cls"]}' style='font-size:17px'>{fmt_s(reg["ventas_riesgo"])}</div>
            <div class='metric-sub'>estimado/mes</div>
            </div>""", unsafe_allow_html=True)
        with cc6:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Tráfico prom. 6m</div>
            <div class='metric-value' style='font-size:17px'>{fmt_n(reg["trafico_prom"])}</div>
            <div class='metric-sub'>tendencia {reg["tend_trafico"]*100:+.1f}%/mes</div>
            </div>""", unsafe_allow_html=True)
        with cc7:
            st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Tráfico en riesgo</div>
            <div class='metric-value {reg["nivel_cls"]}' style='font-size:17px'>{fmt_n(reg["trafico_riesgo"])}</div>
            <div class='metric-sub'>visitas/mes</div>
            </div>""", unsafe_allow_html=True)

# Tabla resumen
st.markdown("<div class='section-header'>Tabla resumen</div>", unsafe_allow_html=True)
df_tabla = pd.DataFrame([{
    "Tienda":           reg["tienda"],
    "Distancia (m)":    reg["distancia_m"],
    "Overlap (%)":      reg["pct_overlap"],
    "Viviendas lente":  int(reg["viv_lente"]),
    "Venta prom/mes":   fmt_s(reg["venta_prom"]),
    "Ventas riesgo":    fmt_s(reg["ventas_riesgo"]),
    "Tráfico prom":     fmt_n(reg["trafico_prom"]),
    "Tráfico riesgo":   fmt_n(reg["trafico_riesgo"]),
    "Tend. ventas":     f"{reg['tend_ventas']*100:+.1f}%",
    "Score":            reg["score"],
    "Nivel":            reg["nivel"],
} for reg in registros])
st.dataframe(df_tabla, use_container_width=True, hide_index=True)

# Exportar
st.markdown("<div class='section-header'>Exportar</div>", unsafe_allow_html=True)
df_exp = pd.DataFrame([{
    "punto_b":           st.session_state.nombre_b,
    "lat_b":             st.session_state.lat_b,
    "lon_b":             st.session_state.lon_b,
    "radio_m":           r,
    "tienda_afectada":   reg["tienda"],
    "distancia_m":       reg["distancia_m"],
    "pct_overlap":       reg["pct_overlap"],
    "area_lente_m2":     reg["area_lente_m2"],
    "cuerda_m":          reg["cuerda_m"],
    "viviendas_lente":   int(reg["viv_lente"]),
    "venta_prom_6m":     reg["venta_prom"],
    "ventas_en_riesgo":  reg["ventas_riesgo"],
    "trafico_prom_6m":   reg["trafico_prom"],
    "trafico_en_riesgo": reg["trafico_riesgo"],
    "tend_ventas_pct":   round(reg["tend_ventas"]*100, 2),
    "tend_trafico_pct":  round(reg["tend_trafico"]*100, 2),
    "factor_tendencia":  reg["ft"],
    "score":             reg["score"],
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
