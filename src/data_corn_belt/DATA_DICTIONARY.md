# Diccionario de datos — Corn Belt (Ames, Iowa)

Este documento describe los CSV de esta carpeta: qué representa cada uno,
qué significa cada columna y cómo interpretar sus fechas y resolución espacial.

## Sitio de referencia y formato

- **Punto consultado:** Ames, Iowa, `lat=42.03`, `lon=-93.47` (longitud oeste negativa).
- **Periodo común de análisis:** del **2015-03-31 al 2025-12-31**. SMAP SPL4SMGP v008 no tiene cobertura anterior al 31 de marzo de 2015.
- **Formato:** CSV delimitado por comas, con encabezado y decimales con punto.
- **Datos temporales:** cada fila corresponde a una fecha o intervalo en el punto de grilla.
- **Datos estáticos:** una fila resume propiedades del suelo en la celda asignada al punto.
- `lat`/`lon` indican el punto consultado. `grid_lat`/`grid_lon`, cuando existen, indican el centro de la celda utilizada.

### Tamaño actual de los archivos

Tamaños observados en disco; pueden cambiar si se regeneran los CSV o se modifica su formato.

| Archivo | Tamaño exacto | Aproximado |
|---|---:|---:|
| `power_ames_2005_2025.csv` | 377,657 bytes | 377.7 kB |
| `smap_ames_2024.csv` | 159,876 bytes | 159.9 kB |
| `gldas_soils_ames.csv` | 206 bytes | 0.2 kB |
| `igbp_soils_ames.csv` | 295 bytes | 0.3 kB |
| `power_ames_2015_2025.csv` | 193,387 bytes | 193.4 kB |
| `smap_ames_2015_2025.csv` | 1,715,137 bytes | 1,715.1 kB |
| `corn_belt_daily_2015_2025.csv` | 1,234,168 bytes | 1,234.2 kB |

## 1. NASA POWER — clima diario

Archivo: [`power_ames_2005_2025.csv`](power_ames_2005_2025.csv)

NASA POWER proporciona variables meteorológicas y de superficie. Este archivo usa la
comunidad agroclimatológica (`AG`) y tiempo **UTC**. Contiene **7,670 filas**, del
**2005-01-01 al 2025-12-31**, una fila por día.

Para el periodo común con SMAP se creó [`power_ames_2015_2025.csv`](power_ames_2015_2025.csv),
una selección sin cambios de variables entre **2015-03-31 y 2025-12-31** (3,929 días).
El archivo de 2005–2025 se conserva como fuente original.

| Columna | Unidad | Qué representa |
|---|---|---|
| `date` | fecha (`YYYY-MM-DD`) | Día al que corresponden los valores, en UTC. |
| `T2M` | °C | Temperatura media diaria del aire a 2 m. |
| `T2M_MAX` | °C | Temperatura máxima diaria del aire a 2 m. |
| `T2M_MIN` | °C | Temperatura mínima diaria del aire a 2 m. |
| `PRECTOTCORR` | mm/día | Precipitación total diaria corregida. |
| `RH2M` | % | Humedad relativa a 2 m. |
| `WS2M` | m/s | Velocidad del viento a 2 m. |
| `ALLSKY_SFC_SW_DWN` | MJ/m²/día | Radiación solar de onda corta descendente que llega a la superficie, bajo condiciones de cielo reales. |

**Granularidad espacial:** punto de grilla POWER. La resolución nativa es aproximadamente
0.5° × 0.625° para meteorología y 1° para radiación solar (decenas de kilómetros); no
es una estación meteorológica local.

## 2. NASA SMAP L4 — humedad del suelo y temperatura superficial

Archivo para el periodo completo: [`smap_ames_2015_2025.csv`](smap_ames_2015_2025.csv)

Producto **SPL4SMGP v008**. El archivo histórico de 2015–2025 tiene **31,432 filas**,
con **8 observaciones por día** (una cada 3 horas), desde el 2015-03-31 hasta el
2025-12-31. Los timestamps están en UTC y marcan el centro de cada ventana (por
ejemplo, `01:30` representa `00:00–03:00 UTC`). Los valores corresponden a la celda SMAP
de aproximadamente 9 km más cercana, cuyo centro es `42.043°N, 93.501°W`.

El archivo anterior [`smap_ames_2024.csv`](smap_ames_2024.csv) se conserva como extracto
de un solo año; es un subconjunto de la serie histórica.

| Columna | Unidad | Qué representa |
|---|---|---|
| `datetime` | fecha y hora UTC | Centro temporal de la ventana de 3 horas. |
| `sm_surface` | m³/m³ | Humedad volumétrica superficial, aproximadamente 0–5 cm. |
| `sm_rootzone` | m³/m³ | Humedad volumétrica estimada para la zona radicular, aproximadamente 0–100 cm. Es modelada, no medida directamente por el satélite a esa profundidad. |
| `sm_profile` | m³/m³ | Humedad volumétrica integrada desde la superficie hasta el lecho rocoso según el producto. |
| `surface_temp` | K | Temperatura media de la superficie terrestre. Para convertir a °C: `K - 273.15`. |

**Granularidad temporal:** promedio por ventana de 3 horas, no dato instantáneo.
**Granularidad espacial:** celda EASE-Grid 2.0 de aproximadamente 9 km. SMAP L4 combina
observaciones satelitales con un modelo de superficie terrestre; no es una imagen cruda
ni una medición de campo. Los valores de relleno se convierten a faltantes (`NaN`) al
extraerlos.

## 3. GLDAS — textura y fracciones del suelo

Archivo: [`gldas_soils_ames.csv`](gldas_soils_ames.csv)

Tabla **estática** de una fila. La celda GLDAS de 0.25° más cercana tiene centro
`42.125°N, 93.375°W`. Describe textura y porosidad; no son observaciones repetidas en
el tiempo.

| Columna | Unidad / tipo | Qué representa |
|---|---|---|
| `site` | texto | Identificador del sitio; aquí contiene `42.03,-93.47`. |
| `lat`, `lon` | grados decimales | Coordenadas del punto consultado; longitud oeste negativa. |
| `grid_lat`, `grid_lon` | grados decimales | Centro de la celda GLDAS usada. |
| `texture_class` | código categórico entero | Clase Noah/FAO de textura. El código `6` significa **Loam** (franco). |
| `texture` | categoría | Etiqueta de `texture_class`; en este caso, `Loam`. |
| `sand` | fracción 0–1 | Proporción de arena. |
| `silt` | fracción 0–1 | Proporción de limo. |
| `clay` | fracción 0–1 | Proporción de arcilla. |
| `porosity` | fracción 0–1 | Porosidad estimada del suelo. |

Las fracciones son adimensionales: por ejemplo, `sand=0.40` equivale a 40%. La grilla
es de **0.25°** (aproximadamente 25 km en latitud; el ancho longitudinal depende de la
latitud). Para este punto las fracciones son aproximadamente 40% arena, 36% limo y 24%
arcilla.

## 4. IGBP-DIS / ORNL DAAC — propiedades del suelo

Archivo: [`igbp_soils_ames.csv`](igbp_soils_ames.csv)

Tabla **estática** de una fila extraída de grillas globales IGBP-DIS. Las propiedades
corresponden a la capa de suelo **0–100 cm**. La resolución nativa es 5 minutos de arco
(1/12°, aproximadamente 9 km); se usa la celda que contiene el punto. El producto se
deriva de mapas y perfiles de suelo cuyo periodo de referencia es **1950–1996**. Esto
describe la base de las estimaciones, no una serie anual de observaciones.

| Columna | Unidad | Qué representa |
|---|---|---|
| `site` | texto | Identificador del sitio; aquí contiene `42.03,-93.47`. |
| `lat`, `lon` | grados decimales | Coordenadas del punto consultado; longitud oeste negativa. |
| `field_capacity` | mm de agua en 0–100 cm | Agua retenida a capacidad de campo (aprox. −10 kPa). |
| `wilting_point` | mm de agua en 0–100 cm | Agua remanente en el punto de marchitez (aprox. −1500 kPa). |
| `profile_available_water_capacity` | mm de agua en 0–100 cm | Capacidad de agua disponible; diferencia entre capacidad de campo y punto de marchitez. |
| `bulk_density` | g/cm³ | Densidad aparente del suelo. |
| `soil_carbon_density` | kg/m² | Densidad de carbono del suelo en el perfil 0–100 cm. |
| `total_nitrogen_density` | g/m² | Densidad de nitrógeno total en el perfil 0–100 cm. |
| `thermal_capacity` | MJ/m³/K | Capacidad térmica volumétrica del suelo seco. |

Como referencia, este CSV contiene aproximadamente 419 mm de capacidad de campo,
181.66 mm en el punto de marchitez y 237.34 mm de agua disponible. Son estimaciones de
una grilla global, no un análisis del suelo de una parcela.

## Tabla diaria armonizada para el análisis (2015–2025)

Archivo: [`corn_belt_daily_2015_2025.csv`](corn_belt_daily_2015_2025.csv)

Esta tabla combina los dos productos con frecuencia temporal y adjunta el contexto de
suelo en un eje diario común. Tiene **3,929 filas**, del **2015-03-31 al 2025-12-31**,
en UTC. Cada fila representa un día.

- Columnas NASA POWER mantienen sus nombres (`T2M`, `PRECTOTCORR`, etc.) y valores
  diarios originales, seleccionados de la serie 2005–2025.
- Las cuatro variables SMAP se promedian sobre las ocho ventanas de 3 horas de cada día
  UTC y llevan el prefijo `smap_` (por ejemplo, `smap_sm_rootzone`). La temperatura sigue
  en kelvin.
- `smap_n_obs` indica cuántas observaciones de humedad superficial válidas se usaron ese
  día; en la extracción actual son 8 para cada fecha.
- Las columnas estáticas GLDAS llevan prefijo `gldas_` e incluyen centro de celda,
  textura, fracciones y porosidad. Las IGBP llevan prefijo `igbp_` y contienen las
  propiedades estáticas de la capa 0–100 cm.
- Los valores GLDAS/IGBP se repiten en cada fila únicamente para facilitar el análisis
  integrado. **No** representan nuevas mediciones de suelo cada día.

La columna diaria de lluvia es un total diario; SMAP se agrega con media diaria porque
humedad y temperatura son variables de estado. Para análisis temporal de POWER/SMAP esta
es la tabla recomendada; para EDA separado por fuente, usa los CSV de origen.

## Métricas derivadas en el EDA

Las siguientes series se calculan dentro de
[01_data_eda.ipynb](../../Notebooks/corn_belt/01_data_eda.ipynb)
y **no se guardan como columnas nuevas** en los CSV:

| Métrica | Cálculo y unidad | Interpretación |
|---|---|---|
| Temperatura mensual | Media mensual de *T2M* y *smap_surface_temp*; SMAP se convierte de K a °C restando 273.15. | Comparación entre temperatura del aire de POWER y temperatura de superficie de SMAP; son variables relacionadas, pero no equivalentes. |
| Precipitación mensual | Suma mensual de *PRECTOTCORR* diario; mm/mes. | Acumulado del mes, distinto de la media diaria que puede mostrarse en los resúmenes por mes. |
| Humedad mensual | Media mensual de *smap_sm_surface* y *smap_sm_rootzone*; m³/m³. | Evolución de los estados diarios de humedad agregados desde las ocho observaciones SMAP del día. |
| Climatología por mes calendario | Para cada variable se calcula la media y desviación estándar entre los valores mensuales del mismo mes. | Resume el ciclo estacional y su variación entre años. Marzo de 2015 se excluye porque solo contiene el día 31; ±1 desviación estándar describe dispersión, no un intervalo de confianza. |
| Anomalía mensual de temperatura | A cada valor mensual se le resta la media histórica de su mes calendario; °C. | Permite comparar co-movimiento de temperaturas reduciendo el ciclo estacional promedio. |
| Lluvia antecedente de 7 días | Suma móvil de los siete valores diarios de *PRECTOTCORR*, incluyendo el día de referencia; mm/7 días. | Cuantifica precipitación reciente antes de compararla con humedad SMAP. |
| Anomalías diarias de lluvia y humedad | A la lluvia móvil y a la humedad SMAP diaria se les resta, por separado, su media histórica del mismo mes calendario. | Reduce el ciclo estacional promedio; no elimina tendencias ni autocorrelación. Las anomalías estandarizadas se expresan en desviaciones estándar y se suavizan con una ventana móvil de 30 días para la gráfica. |
| Correlación con desfase | Correlación de Pearson entre anomalía de lluvia de 7 días y anomalía de humedad SMAP, probando desfases de 0 a 30 días. | Un desfase positivo de *k* días compara la ventana de lluvia que termina *k* días antes con la humedad en la fecha observada. El desfase 0 incluye el mismo día. Es una exploración de asociación, no una prueba causal ni una estimación que controle autocorrelación. |

Las propiedades GLDAS e IGBP son estáticas y solo describen contexto del sitio. Aunque se
repitan en las filas diarias de la tabla integrada, no deben tratarse como series
temporales ni como observaciones independientes al calcular correlaciones.

## Cómo leerlos con pandas

Ejecuta desde la raíz del repositorio:

```python
import pandas as pd

power = pd.read_csv(
    "src/data_corn_belt/power_ames_2005_2025.csv", parse_dates=["date"]
)
smap = pd.read_csv(
    "src/data_corn_belt/smap_ames_2015_2025.csv", parse_dates=["datetime"]
)
daily = pd.read_csv(
    "src/data_corn_belt/corn_belt_daily_2015_2025.csv", parse_dates=["date"]
)
gldas = pd.read_csv("src/data_corn_belt/gldas_soils_ames.csv")
igbp = pd.read_csv("src/data_corn_belt/igbp_soils_ames.csv")

print(power.head())  # serie diaria
print(smap.head())   # serie cada 3 horas
print(gldas.iloc[0]) # propiedades estáticas
print(igbp.iloc[0])  # propiedades estáticas
```

Al combinar POWER y SMAP, mantén las fechas en UTC. Si agregas SMAP a datos diarios,
promedia variables de estado como humedad y temperatura. Para acumular tasas o flujos,
primero convierte las unidades según su definición. Estos productos tienen resoluciones
y métodos distintos: coincidir en ubicación no significa que sean datos de parcela ni
que sus definiciones de suelo sean intercambiables.

## Referencias de los productos

- [NASA POWER — API diaria](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [NASA NSIDC — SMAP L4 SPL4SMGP v008](https://nsidc.org/data/spl4smgp/versions/8)
- [NASA GLDAS — datos de suelos](https://ldas.gsfc.nasa.gov/gldas/soils)
- [ORNL DAAC — IGBP-DIS Global Gridded Surfaces of Selected Soil Characteristics](https://doi.org/10.3334/ORNLDAAC/569)
