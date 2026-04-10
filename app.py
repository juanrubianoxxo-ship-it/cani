import streamlit as st
import pandas as pd
import numpy as np
import math
import folium
from streamlit_folium import st_folium
from io import BytesIO
import json

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Análisis de Canibalización",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# ESTILOS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.stApp { background: #0f1117; color: #e8e6df; }

section[data-testid="stSidebar"] {
    background: #161820;
    border-right: 1px solid #2a2d3a;
}
section[data-testid="stSidebar"] * { color: #c8c6bf !important; }

.metric-card {
    background: #1a1d27;
    border: 1px solid #2a2d3a;
    border-radius: 10px;
    padding: 16px 20px;
    margin: 6px 0;
}
.metric-label { font-size: 11px; color: #7a7a8a; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 4px; }
.metric-value { font-size: 24px; font-weight: 600; font-family: 'DM Mono', monospace; }
.metric-sub { font-size: 11px; color: #7a7a8a; margin-top: 2px; }

.nivel-bajo { color: #4ade80; }
.nivel-medio { color: #fbbf24; }
.nivel-alto { color: #f87171; }

.section-header {
    font-size: 11px; font-weight: 600; color: #5a5a6a;
    text-transform: uppercase; letter-spacing: .1em;
    margin: 24px 0 12px; padding-bottom: 8px;
    border-bottom: 1px solid #2a2d3a;
}

.info-box {
    background: #1a1d27;
    border: 1px solid #2a2d3a;
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 13px;
    color: #9a9aaa;
    line-height: 1.7;
    margin: 8px 0;
}
.info-box b { color: #e8e6df; }

.score-bar-wrap { background: #2a2d3a; border-radius: 6px; height: 8px; margin: 6px 0; overflow: hidden; }
.score-bar { height: 8px; border-radius: 6px; transition: width .5s; }

.tienda-tag {
    display: inline-block;
    background: #1e3a5f;
    color: #60a5fa;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 11px;
    font-family: 'DM Mono', monospace;
}

.stDataFrame { background: #1a1d27 !important; }
div[data-testid="stExpander"] { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 10px; }

hr { border-color: #2a2d3a; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# FUNCIONES CORE
# ─────────────────────────────────────────────

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
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
    """Devuelve pendiente normalizada sobre el promedio"""
    if len(serie) < 2: return 0
    x = np.arange(len(serie))
    prom = np.mean(serie)
    if prom == 0: return 0
    slope = np.polyfit(x, serie, 1)[0]
    return slope / prom  # pendiente relativa mensual

def factor_tendencia(tend):
    """Factor multiplicador según tendencia de la tienda"""
    if tend > 0.05:   return 1.3   # creciendo fuerte → más riesgo
    if tend > 0.01:   return 1.1   # creciendo leve
    if tend > -0.01:  return 1.0   # estable
    if tend > -0.05:  return 0.85  # cayendo leve
    return 0.7                      # cayendo fuerte

def calcular_score(pct_geo, viviendas_lente, viviendas_A, tend_ventas, tend_trafico):
    w1, w2, w3 = 0.45, 0.35, 0.20
    comp_geo   = pct_geo / 100
    comp_viv   = (viviendas_lente / viviendas_A) if viviendas_A > 0 else comp_geo
    comp_tend  = (abs(tend_ventas) + abs(tend_trafico)) / 2
    ft = factor_tendencia((tend_ventas + tend_trafico) / 2)
    score = (w1*comp_geo + w2*comp_viv + w3*comp_tend) * ft
    return min(score, 1.0)

def nivel_canib(score):
    if score < 0.15: return "Bajo",  "#4ade80", "nivel-bajo"
    if score < 0.35: return "Medio", "#fbbf24", "nivel-medio"
    return "Alto", "#f87171", "nivel-alto"

def tienda_mas_cercana(lat_b, lon_b, df):
    df = df.copy()
    df["_dist"] = df.apply(
        lambda r: haversine(r["latitud"], r["longitud"], lat_b, lon_b), axis=1
    )
    idx = df["_dist"].idxmin()
    return df.loc[idx], df["_dist"].min()

def cols_numericas_ventas(df):
    """Detecta columnas de ventas mensuales (v1..v6 o similares)"""
    return [c for c in df.columns if any(k in c.lower() for k in ["venta","sale","ingreso","v_"])]

def cols_numericas_trafico(df):
    return [c for c in df.columns if any(k in c.lower() for k in ["trafico","tráfico","traffic","t_","visita"])]

def crear_mapa(tienda_A, punto_B, radio, d_real):
    lat_c = (tienda_A["latitud"] + punto_B["lat"]) / 2
    lon_c = (tienda_A["longitud"] + punto_B["lon"]) / 2
    m = folium.Map(location=[lat_c, lon_c], zoom_start=15,
                   tiles="CartoDB dark_matter")

    # Círculo tienda A
    folium.Circle(
        location=[tienda_A["latitud"], tienda_A["longitud"]],
        radius=radio, color="#3b82f6", fill=True,
        fill_color="#3b82f6", fill_opacity=0.12,
        tooltip=f"Tienda A: {tienda_A.get('nombre', tienda_A.get('id_tienda','A'))}"
    ).add_to(m)
    folium.CircleMarker(
        location=[tienda_A["latitud"], tienda_A["longitud"]],
        radius=7, color="#3b82f6", fill=True, fill_color="#3b82f6",
        tooltip=f"Tienda A — {tienda_A.get('nombre', tienda_A.get('id_tienda','A'))}"
    ).add_to(m)

    # Círculo punto B
    folium.Circle(
        location=[punto_B["lat"], punto_B["lon"]],
        radius=radio, color="#22c55e", fill=True,
        fill_color="#22c55e", fill_opacity=0.12,
        tooltip="Punto potencial B", dash_array="8"
    ).add_to(m)
    folium.CircleMarker(
        location=[punto_B["lat"], punto_B["lon"]],
        radius=7, color="#22c55e", fill=True, fill_color="#22c55e",
        tooltip="Punto potencial B"
    ).add_to(m)

    # Línea distancia
    folium.PolyLine(
        [[tienda_A["latitud"], tienda_A["longitud"]],
         [punto_B["lat"], punto_B["lon"]]],
        color="#fbbf24", weight=1.5, dash_array="6",
        tooltip=f"Distancia: {d_real:.0f} m"
    ).add_to(m)

    return m

def fmt_n(n):
    return f"{n:,.0f}".replace(",", ".")

def fmt_pct(p):
    return f"{p:.1f}%"


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📍 Análisis de Canibalización")
    st.markdown("---")

    st.markdown("**1. Cargar base de tiendas**")
    uploaded = st.file_uploader(
        "Sube tu archivo (.xlsx o .csv)",
        type=["xlsx","csv"],
        help="Debe tener columnas: latitud, longitud y datos de ventas/tráfico"
    )

    st.markdown("---")
    st.markdown("**2. Radio de influencia**")
    radio = st.slider("Radio (metros)", 100, 1000, 300, 50)

    st.markdown("---")
    st.markdown("**3. Pesos del score**")
    with st.expander("Ajustar pesos"):
        w_geo = st.slider("Peso geométrico", 0.0, 1.0, 0.45, 0.05)
        w_viv = st.slider("Peso viviendas", 0.0, 1.0, 0.35, 0.05)
        w_tend = st.slider("Peso tendencia", 0.0, 1.0, 0.20, 0.05)
        total_w = w_geo + w_viv + w_tend
        if abs(total_w - 1.0) > 0.01:
            st.warning(f"Los pesos suman {total_w:.2f} — deben sumar 1.0")

    st.markdown("---")
    st.markdown("""
    <div style='font-size:11px;color:#5a5a6a;line-height:1.6'>
    <b style='color:#7a7a8a'>Niveles de canibalización</b><br>
    🟢 Bajo &nbsp; score &lt; 0.15<br>
    🟡 Medio &nbsp; 0.15 – 0.35<br>
    🔴 Alto &nbsp; score &gt; 0.35
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
st.markdown("## Análisis de Canibalización de Tiendas")
st.markdown("<div class='section-header'>Modelo geométrico + demanda</div>", unsafe_allow_html=True)

if uploaded is None:
    st.markdown("""
    <div class='info-box'>
    <b>¿Cómo usar esta app?</b><br><br>
    1. Sube tu base de datos de tiendas operando desde el panel lateral.<br>
    2. Ingresa las coordenadas del punto potencial B.<br>
    3. Completa los datos del punto (viviendas en la lente).<br>
    4. La app calcula automáticamente la distancia, el overlap geométrico y el score de canibalización.<br><br>
    <b>Formato esperado del archivo:</b><br>
    Columnas mínimas: <code>latitud</code>, <code>longitud</code><br>
    Columnas de ventas: <code>venta_m1</code> a <code>venta_m6</code> (o similar)<br>
    Columnas de tráfico: <code>trafico_m1</code> a <code>trafico_m6</code> (o similar)<br>
    Columna opcional: <code>viviendas_radio</code>, <code>nombre</code> o <code>id_tienda</code>
    </div>
    """, unsafe_allow_html=True)

    # Template descargable
    st.markdown("<div class='section-header'>Plantilla de ejemplo</div>", unsafe_allow_html=True)
    template = pd.DataFrame({
        "id_tienda":    ["T001", "T002", "T003"],
        "nombre":       ["Tienda Centro", "Tienda Norte", "Tienda Sur"],
        "latitud":      [4.6383475, 4.6450000, 4.6300000],
        "longitud":     [-74.0787174, -74.0820000, -74.0750000],
        "venta_m1":     [12500000, 9800000, 15200000],
        "venta_m2":     [11800000, 10200000, 14800000],
        "venta_m3":     [13100000, 9500000, 15600000],
        "venta_m4":     [12900000, 10800000, 15100000],
        "venta_m5":     [13400000, 11200000, 15900000],
        "venta_m6":     [14000000, 11500000, 16200000],
        "trafico_m1":   [4200, 3100, 5800],
        "trafico_m2":   [4000, 3300, 5600],
        "trafico_m3":   [4500, 3000, 6100],
        "trafico_m4":   [4300, 3500, 5900],
        "trafico_m5":   [4600, 3700, 6300],
        "trafico_m6":   [4900, 3800, 6500],
        "viviendas_radio": [1200, 850, 2100],
    })
    buf = BytesIO()
    template.to_excel(buf, index=False)
    st.download_button("⬇ Descargar plantilla Excel", buf.getvalue(),
                       "plantilla_tiendas.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.stop()


# ─────────────────────────────────────────────
# CARGAR BD
# ─────────────────────────────────────────────
try:
    if uploaded.name.endswith(".csv"):
        df = pd.read_csv(uploaded)
    else:
        df = pd.read_excel(uploaded)
except Exception as e:
    st.error(f"Error leyendo el archivo: {e}")
    st.stop()

# Normalizar nombres de columnas
df.columns = [c.strip().lower().replace(" ","_") for c in df.columns]

# Validar columnas mínimas
if "latitud" not in df.columns or "longitud" not in df.columns:
    st.error("El archivo debe tener columnas **latitud** y **longitud**.")
    st.stop()

df["latitud"]  = pd.to_numeric(df["latitud"],  errors="coerce")
df["longitud"] = pd.to_numeric(df["longitud"], errors="coerce")
df = df.dropna(subset=["latitud","longitud"])

# Detectar columnas de ventas y tráfico
vcols = sorted([c for c in df.columns if any(k in c for k in ["venta","sale","ingreso"])])
tcols = sorted([c for c in df.columns if any(k in c for k in ["trafico","tráfico","traffic","visita"])])

st.success(f"✓ {len(df)} tiendas cargadas — {len(vcols)} columnas de ventas — {len(tcols)} columnas de tráfico")

with st.expander("Vista previa de la base de datos"):
    st.dataframe(df, use_container_width=True, height=220)


# ─────────────────────────────────────────────
# FORMULARIO PUNTO B
# ─────────────────────────────────────────────
st.markdown("<div class='section-header'>Punto potencial B</div>", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    lat_b = st.number_input("Latitud punto B", value=4.6357799, format="%.7f")
    lon_b = st.number_input("Longitud punto B", value=-74.0751250, format="%.7f")
with col2:
    viv_lente = st.number_input(
        "Viviendas contadas en la lente (ArcGIS)",
        min_value=0, value=0, step=10,
        help="Cuenta visual en ArcGIS cruzando el polígono lente con capa DANE 2018"
    )
    nombre_punto = st.text_input("Nombre / referencia del punto", value="Punto potencial nuevo")

analizar = st.button("▶ Calcular canibalización", type="primary", use_container_width=True)

if not analizar:
    st.stop()


# ─────────────────────────────────────────────
# CÁLCULOS
# ─────────────────────────────────────────────
punto_B = {"lat": lat_b, "lon": lon_b, "nombre": nombre_punto}
tienda_A, d_real = tienda_mas_cercana(lat_b, lon_b, df)

# Geometría
pct_geo   = pct_overlap(d_real, radio)
a_lente   = area_lente(d_real, radio)
a_circulo = math.pi * radio * radio
cuerda    = chord_length(d_real, radio)

# Ventas y tráfico
ventas_serie   = [tienda_A[c] for c in vcols if pd.notna(tienda_A.get(c))] if vcols else []
trafico_serie  = [tienda_A[c] for c in tcols if pd.notna(tienda_A.get(c))] if tcols else []

venta_prom  = np.mean(ventas_serie)  if ventas_serie  else 0
trafico_prom = np.mean(trafico_serie) if trafico_serie else 0
venta_ult   = ventas_serie[-1]  if ventas_serie  else 0
trafico_ult = trafico_serie[-1] if trafico_serie else 0

tend_ventas  = tendencia_lineal(ventas_serie)  if len(ventas_serie) >= 2  else 0
tend_trafico = tendencia_lineal(trafico_serie) if len(trafico_serie) >= 2 else 0

# Viviendas
viv_A   = tienda_A.get("viviendas_radio", 0)
viv_est = viv_A * (pct_geo/100) if viv_A > 0 else None  # estimado proporcional si no se ingresó

viv_usar = viv_lente if viv_lente > 0 else (viv_est if viv_est else 0)
viv_A_usar = viv_A if viv_A > 0 else (viv_usar / (pct_geo/100) if pct_geo > 0 else 1)

# Score
score = calcular_score(pct_geo, viv_usar, viv_A_usar, tend_ventas, tend_trafico)
nivel_txt, nivel_color, nivel_cls = nivel_canib(score)

# Proyecciones de impacto
ventas_riesgo  = venta_prom  * (pct_geo/100)
trafico_riesgo = trafico_prom * (pct_geo/100)
ft = factor_tendencia((tend_ventas + tend_trafico) / 2)

nombre_A = tienda_A.get("nombre", tienda_A.get("id_tienda", f"Tienda #{tienda_A.name}"))


# ─────────────────────────────────────────────
# RESULTADOS
# ─────────────────────────────────────────────
st.markdown("---")
st.markdown(f"### Resultados — {nombre_punto}")
st.markdown(f"Tienda más cercana: <span class='tienda-tag'>{nombre_A}</span>", unsafe_allow_html=True)

# Score principal
score_pct = score * 100
bar_color = nivel_color
st.markdown(f"""
<div class='metric-card' style='border-color:{nivel_color}33'>
  <div class='metric-label'>Score de canibalización</div>
  <div class='metric-value {nivel_cls}'>{score:.3f} &nbsp;—&nbsp; {nivel_txt}</div>
  <div class='score-bar-wrap'>
    <div class='score-bar' style='width:{min(score_pct/0.5*100,100):.0f}%;background:{nivel_color}'></div>
  </div>
  <div class='metric-sub'>0 = sin riesgo &nbsp;|&nbsp; 0.35+ = alto riesgo</div>
</div>
""", unsafe_allow_html=True)

st.markdown("<div class='section-header'>Geometría</div>", unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Distancia A → B</div>
    <div class='metric-value'>{fmt_n(d_real)} m</div>
    <div class='metric-sub'>radio = {radio} m</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Overlap geométrico</div>
    <div class='metric-value'>{fmt_pct(pct_geo)}</div>
    <div class='metric-sub'>del radio de A</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Área lente</div>
    <div class='metric-value'>{fmt_n(a_lente)} m²</div>
    <div class='metric-sub'>de {fmt_n(a_circulo)} m² totales</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Cuerda</div>
    <div class='metric-value'>{fmt_n(cuerda)} m</div>
    <div class='metric-sub'>ancho de la lente</div>
    </div>""", unsafe_allow_html=True)


st.markdown("<div class='section-header'>Impacto proyectado en tienda A</div>", unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Venta promedio 6m</div>
    <div class='metric-value' style='font-size:18px'>${fmt_n(venta_prom)}</div>
    <div class='metric-sub'>tendencia: {tend_ventas*100:+.1f}%/mes</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Ventas en riesgo</div>
    <div class='metric-value {nivel_cls}' style='font-size:18px'>${fmt_n(ventas_riesgo)}</div>
    <div class='metric-sub'>estimado mensual</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Tráfico promedio 6m</div>
    <div class='metric-value' style='font-size:18px'>{fmt_n(trafico_prom)}</div>
    <div class='metric-sub'>tendencia: {tend_trafico*100:+.1f}%/mes</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""<div class='metric-card'>
    <div class='metric-label'>Tráfico en riesgo</div>
    <div class='metric-value {nivel_cls}' style='font-size:18px'>{fmt_n(trafico_riesgo)}</div>
    <div class='metric-sub'>visitas/mes estimadas</div>
    </div>""", unsafe_allow_html=True)

if viv_usar > 0:
    st.markdown("<div class='section-header'>Demanda residencial</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>Viviendas en la lente</div>
        <div class='metric-value'>{fmt_n(viv_usar)}</div>
        <div class='metric-sub'>{'conteo manual ArcGIS' if viv_lente > 0 else 'estimado proporcional'}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        pct_viv = (viv_usar / viv_A_usar * 100) if viv_A_usar > 0 else 0
        st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>% viviendas de A en riesgo</div>
        <div class='metric-value {nivel_cls}'>{fmt_pct(pct_viv)}</div>
        <div class='metric-sub'>de {fmt_n(viv_A_usar)} viviendas totales en radio A</div>
        </div>""", unsafe_allow_html=True)

# Nota tendencia
if ft != 1.0:
    if ft > 1.0:
        st.warning(f"⚠ Tienda A está en tendencia creciente ({tend_ventas*100:+.1f}%/mes en ventas). El factor de riesgo es mayor: ×{ft}")
    else:
        st.info(f"ℹ Tienda A muestra tendencia decreciente ({tend_ventas*100:+.1f}%/mes en ventas). Factor de riesgo ajustado: ×{ft}")


# ─────────────────────────────────────────────
# MAPA
# ─────────────────────────────────────────────
st.markdown("<div class='section-header'>Mapa</div>", unsafe_allow_html=True)
mapa = crear_mapa(tienda_A, punto_B, radio, d_real)
st_folium(mapa, width=None, height=420, returned_objects=[])


# ─────────────────────────────────────────────
# DESGLOSE DEL SCORE
# ─────────────────────────────────────────────
with st.expander("Desglose del score"):
    comp_geo  = pct_geo / 100
    comp_viv  = (viv_usar / viv_A_usar) if viv_A_usar > 0 else comp_geo
    comp_tend = (abs(tend_ventas) + abs(tend_trafico)) / 2

    data_score = pd.DataFrame({
        "Componente": ["Overlap geométrico", "Viviendas en lente", "Tendencia operativa"],
        "Peso":       [0.45, 0.35, 0.20],
        "Valor":      [comp_geo, comp_viv, comp_tend],
        "Aporte":     [0.45*comp_geo, 0.35*comp_viv, 0.20*comp_tend],
    })
    data_score["Valor (%)"]  = data_score["Valor"].map(lambda x: f"{x*100:.1f}%")
    data_score["Aporte"]     = data_score["Aporte"].map(lambda x: f"{x:.4f}")
    st.dataframe(data_score[["Componente","Peso","Valor (%)","Aporte"]], use_container_width=True)
    st.markdown(f"**Factor tendencia:** ×{ft} &nbsp;|&nbsp; **Score final:** {score:.4f}")


# ─────────────────────────────────────────────
# EXPORTAR RESULTADO
# ─────────────────────────────────────────────
st.markdown("<div class='section-header'>Exportar resultado</div>", unsafe_allow_html=True)

resultado = {
    "punto_nombre": nombre_punto,
    "lat_b": lat_b, "lon_b": lon_b,
    "tienda_A": nombre_A,
    "distancia_m": round(d_real, 1),
    "radio_m": radio,
    "pct_overlap": round(pct_geo, 2),
    "area_lente_m2": round(a_lente, 1),
    "cuerda_m": round(cuerda, 1),
    "viviendas_lente": int(viv_usar),
    "ventas_prom_6m": round(venta_prom, 0),
    "ventas_en_riesgo": round(ventas_riesgo, 0),
    "trafico_prom_6m": round(trafico_prom, 0),
    "trafico_en_riesgo": round(trafico_riesgo, 0),
    "tendencia_ventas_pct": round(tend_ventas*100, 2),
    "tendencia_trafico_pct": round(tend_trafico*100, 2),
    "factor_tendencia": ft,
    "score": round(score, 4),
    "nivel": nivel_txt,
}

df_res = pd.DataFrame([resultado])
buf = BytesIO()
df_res.to_excel(buf, index=False)
st.download_button(
    "⬇ Descargar resultado en Excel",
    buf.getvalue(),
    f"canibalizacion_{nombre_punto.replace(' ','_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
