# Análisis de Canibalización de Tiendas

Aplicación Streamlit para calcular el riesgo de canibalización entre una tienda operando y un punto potencial nuevo, usando geometría de intersección de radios de influencia.

## Instalación

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Formato del archivo de entrada

El archivo Excel o CSV debe tener estas columnas:

| Columna | Requerida | Descripción |
|---|---|---|
| `latitud` | ✅ | Coordenada latitud de la tienda |
| `longitud` | ✅ | Coordenada longitud de la tienda |
| `venta_m1` ... `venta_m6` | Recomendada | Ventas operativas por mes (últimos 6 meses) |
| `trafico_m1` ... `trafico_m6` | Recomendada | Tráfico mensual (últimos 6 meses) |
| `viviendas_radio` | Opcional | Viviendas dentro del radio de influencia |
| `nombre` o `id_tienda` | Opcional | Identificador de la tienda |

## Cómo funciona el score

```
score = 0.45 × (overlap_geométrico)
      + 0.35 × (viviendas_lente / viviendas_A)
      + 0.20 × (tendencia_operativa)
      × factor_tendencia
```

- **Bajo** (score < 0.15): apertura viable
- **Medio** (0.15 – 0.35): analizar con detalle  
- **Alto** (score > 0.35): riesgo real de pérdida

## Fórmula geométrica

```python
# Área de la lente (intersección de dos círculos de radio r)
A_lente = 2r²·arccos(d/2r) − (d/2)·√(4r²−d²)

# % overlap
pct = A_lente / (π·r²) × 100
```

donde `d` = distancia Haversine entre los dos centros.

## Notas

- Las viviendas en la lente se ingresan manualmente (conteo visual en ArcGIS con capa DANE 2018).
- En una versión futura se puede automatizar con `geopandas` + shapefile MGN DANE.
- Los pesos del score son ajustables desde el panel lateral.
