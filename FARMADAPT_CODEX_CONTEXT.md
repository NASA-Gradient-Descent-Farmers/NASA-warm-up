# FarmAdapt — Contexto y especificación de traspaso para Codex

**Fecha de corte:** 2 de noviembre de 2026  
**Proyecto:** NASA Space Apps Challenge 2026 — *Adapting Farms with NASA Data*  
**Repositorio:** https://github.com/NASA-Gradient-Descent-Farmers/NASA-warm-up  
**Rama de interés:** `daniel-mvp`  
**Estado:** propuesta de producto acordada; implementación previa reportada por Claude, pero frontend no reproducido por el usuario.

> **Instrucción importante para Codex:** Este documento recoge las decisiones del usuario y los hechos **reportados** en la conversación y en informes de Claude. **No asumas que las características reportadas existen, funcionan o son correctas en el repositorio actual. Compruébalas en el código y con pruebas.** No hagas cambios masivos ni reemplaces el trabajo existente sin antes auditarlo.

## 1. Objetivo y visión

Crear **FarmAdapt**, una plataforma global e inclusiva de apoyo a decisiones agrícolas que ayude a distintos tipos de agricultores a elegir:

1. Qué sembrar en el próximo ciclo.
2. Rotaciones de cultivos de 3–5 años.
3. Estrategias alternativas bajo cambios climáticos y económicos.

Debe utilizar datos de NASA, suelo, historia agrícola, necesidades del agricultor y modelos agronómicos para **comparar opciones, riesgos, limitaciones y compromisos**, no para sustituir la decisión humana. Se busca sustento científico, trazabilidad y explicaciones accesibles mediante **Gemini**.

### Usuarios objetivo

- Agricultores con experiencia, conocedores de su tierra, que necesitan adaptarse a variabilidad climática y eventos extremos.
- Agricultores de bajos recursos o pocos conocimientos técnicos, que necesitan orientación comprensible y capacidades de inferencia de datos a partir de ubicación.
- Ambos acceden al **mismo motor científico** con interfaces de complejidad distinta.

### Modos

- **Básico:** ubicación, cultivos recientes, principales prioridades y preguntas cotidianas; inferir lo posible de fuentes geoespaciales, explicando faltantes.
- **Avanzado:** parcela/polígono, análisis de suelo, riego, presupuesto, maquinaria, labores, rendimientos históricos, precios y supuestos parametrizables.
- La conversación con Gemini facilita entradas, conceptos técnicos y explicaciones, pero **no crea hechos ni sustituye al motor agronómico**.

### Funciones agrícolas deseadas

- Rotación de cultivos; cultivos de cobertura (*cover crops*); leguminosas; manejo de residuos; periodos de descanso del suelo (*fallow*).
- Historial agrícola tanto **declarado por agricultor** como **inferido tentativamente** con satélites y confirmado/corregido por usuario. NDVI por sí solo no identifica especies ni demuestra barbecho.
- Considerar las consecuencias entre ciclos: agua, nitrógeno, cobertura/residuos, plagas por sucesión de familias, etc., con simplificaciones explícitas.

## 2. Objetivos de optimización

El agricultor asigna **pesos que suman 100** a cinco objetivos:

1. Rentabilidad esperada (maximizar).
2. Riesgo de pérdidas económicas (minimizar).
3. Uso eficiente del agua (maximizar eficiencia o minimizar consumo; precisar definición).
4. Salud del suelo (maximizar indicadores/estimaciones justificables, no confundir proxy con salud real).
5. Resiliencia ante cambios climáticos (maximizar robustez ante escenarios adversos).

Distinguir **restricciones duras** (presupuesto, agua disponible, infraestructura, superficie, cultivos obligatorios/prohibidos, calendario) de **preferencias** ponderables. Propuesta: filtrar alternativas factibles, obtener frontera de Pareto de objetivos definidos de manera consistente y luego ordenarlas con una utilidad ponderada normalizada. Validar escalas y comportamiento de pesos. Evitar doble conteo entre objetivos altamente correlacionados.

La rentabilidad debe considerar costos, rendimientos y precios con procedencia regional, fechas e incertidumbre; **NO** presentar precios/costos genéricos como predicción confiable. Priorizar análisis de sensibilidad con intervalos o escenarios cuando faltan datos.

## 3. Arquitectura conceptual acordada

```text
NASA + SoilGrids + Historical Weather + datos locales
                    |
                    v
              FarmProfile
                    |
                    v
       Crop / Soil Parameters
                    |
                    v
      Agronomic Model (WOFOST / DSSAT
          o motor simplificado validado)
                    |
                    v
           Candidate Rotations
                    |
                    v
         Multi-objective Optimization
                    |
                    v
         Recommendations + Risks
                    |
                    v
              Gemini explainer
```

Diseño de ingeniería recomendado:

- **Capa A: ingestión y normalización** de datos; cache, cobertura, procedencia y calidad.
- **Capa B: `SiteProfile` ambiental reutilizable** por ubicación/parcela + **`FarmProfile`** personalizado con historial, recursos y preferencias.
- **Capa C: modelos agronómicos y escenarios**, idealmente interfaces intercambiables (`AgronomicModel`) y resultados precalculados si la simulación tarda.
- **Capa D: generación de rotaciones, restricciones, multiobjetivo, sensibilidad y riesgo**.
- **Capa E: evidencia por recomendación, Gemini como intérprete y UI básica/avanzada**.

El mismo motor debe servir tanto a modo demo precomputado como a ubicaciones nuevas. No es requisito que todo el procesamiento global funcione en tiempo real desde el primer MVP.

### Esquema conceptual

```text
FarmProfile
├── location: coordinates, field_boundary?, area_ha?
├── environment: climate, rainfall_extremes, soil, vegetation, water
├── climate_scenarios: historical_variability, future_projections
├── crop_history: farmer_reported, satellite_inferred?, verified_history
├── farm_resources: irrigation, budget, labor, equipment
├── farmer_preferences: objective_weights[5], hard_constraints
└── data_quality: provenance, resolutions, coverage, uncertainty, availability
```

Distinguir explícitamente **riesgo climático**, **riesgo económico**, **incertidumbre del modelo**, **calidad de datos** y **confianza**. No denominar probabilidad de éxito a un score heurístico de confianza no calibrado.

## 4. Fuentes de datos solicitadas

| Fuente | Papel propuesto | Precauciones |
|---|---|---|
| NASA POWER | Clima histórico: T, precipitación, radiación, humedad, variables meteorológicas | Resolución regional; no representa necesariamente microclima de la parcela. |
| GPM IMERG | Precipitación y episodios extremos | Resolución y sesgo; gestionar agregación espacial/temporal. |
| MODIS NDVI | Estacionalidad, índices de vegetación y proxy de cobertura | NDVI bajo no prueba suelo desnudo ni qué cultivo hubo. |
| MODIS ET, LST | Evapotranspiración y temperatura de superficie | Diferenciar ET observada/modelada de ET0 y LST de temperatura del aire. |
| SRTM | Elevación, pendiente, correcciones topográficas | Corrección por lapse rate es aproximación, no garantía local. |
| SMAP | Humedad del suelo | Escala gruesa; no atribuir precisión de parcela. |
| GRACE-FO | Tendencia regional de almacenamiento de agua | Muy gruesa; contexto regional, no agua disponible en un lote. |
| SoilGrids (ISRIC, no NASA) | Textura, SOC, pH, N y otras variables de suelo | Predicciones modeladas, incertidumbre y profundidad. |
| NASA NEX-GDDP-CMIP6 | Escenarios futuros de clima | Proyecciones climatológicas, **no** pronóstico para siembra inmediata. |
| FAOSTAT / MapSPAM / SIAP u otras fuentes | Contexto regional de cultivos, superficie, rendimiento y economía | Evaluar comparabilidad, cobertura y licencias. |

El usuario pidió explícitamente añadir **GPM, MODIS para NDVI/ET/LST, SRTM, GRACE-FO, SoilGrids y NEX-GDDP-CMIP6**. La integración puede hacerse por etapas. No asumir que hay APIs estables o acceso libre sin comprobarlo.

## 5. Regiones de validación y demo

La solución aspira a ser global, pero el demo inicial se precalculará en aproximadamente cuatro sistemas agrícolas distintos:

- **Texcoco, México:** punto de partida por código y perfil previo; maíz, frijol, otros cultivos locales.
- **Iowa, EE. UU.:** maíz/soya, rotación y cover crops.
- **Punjab, India:** arroz/trigo y disponibilidad de agua.
- **África oriental:** pequeño agricultor; **ubicación específica pendiente de definir** (no presentar como piloto ya implementado).

El PDF inicial de Claude menciona tres pilotos (Texcoco, Iowa, Punjab); la cuarta región africana fue una **decisión posterior** del usuario. Evitar descargas masivas en demostración: caches y resultados precomputados con posibilidad de cambiar pesos y comparar alternativas interactivamente. Para sitios fuera del demo, fallbacks honestos con disponibilidad y cálculos asíncronos solo si la arquitectura lo habilita (no bloquear UI).

## 6. Trabajo previo reportado de Claude (`daniel-mvp`)

**Fuente:** PDF aportado por el usuario: *Reporte de Actualizaciones en la Rama daniel-mvp*, 2 noviembre 2026, 5 páginas. **No verificado directamente en este archivo de traspaso.**

Reporta rama `daniel-mvp` creada desde `main` en commit `21e30ec`, sin modificar archivos de Isaac en `src/data_ingestion/`, `src/crop_models/`, `docs/technical_report/`. Según el reporte:

- `src/advisor/schema.py`: `SITE_PROFILE_SCHEMA` v0.1, meses, unidades SI, capas con `ok/fallback/missing`.
- `src/advisor/pull.py`: POWER 1991–2024, SRTM 30 m vía OpenTopoData, MODIS MOD13Q1 NDVI 250 m 2019–2023 vía ORNL DAAC, SoilGrids 250 m; caché y disponibilidad.
- `src/advisor/features.py`: ET0 Hargreaves-Samani, corrección térmica con lapse rate 0.0065 °C/m, heladas, calor, rachas secas, extremo P95, aridez, tendencias, indicador de meses supuestamente desnudos con NDVI <0.25. **Todos son supuestos/implementaciones por auditar**.
- `src/advisor/build_profile.py`: genera perfiles `web/public/data/profiles/`, índice y `data/advisor/availability.csv`.
- `src/advisor/build_references.py`: 34 localidades de referencia para *climate twins*.
- `src/advisor/engine.py`: 679 rotaciones de tres años y 138 no dominadas en Texcoco, simulaciones con 34 años históricos, frontera Pareto, DP estocástica con Bellman. **Reproducir cifras y auditar formulación**.
- `web/public/data/crops.json`: 9 opciones (maize, wheat, sorghum, bean, soybean, faba, alfalfa, cover, fallow) con reglas y economía base.
- `web/public/data/rotation_rules.json`: penalizaciones por familia/plagas y crédito nitrogenado de leguminosas.
- `Notebooks/master_rotation_advisor_walkthrough.ipynb`: ingesta, diagnósticos, simulación, Pareto, DP y Gemini.
- `tests/test_advisor_features.py`: 7 pruebas reportadas exitosas.
- `web/`: React + Vite + TS, `web/src/engine/core.ts`, `evaluate.ts`, componentes de mapa/evidencia/controles/resultados; sensibilidad a lluvia, temperatura y precios; Gemini por Firebase AI Logic, ocho idiomas, fallback determinista; `npm run build` reportado exitoso.
- Informe anterior *Triangulated Rotation Advisor (Oct 30)* explica tres lentes: climate twins, opportunity windows y resource budget. Tratar estos lentes como aproximaciones exploratorias, no evidencia independiente por defecto.

### Hallazgos de conversación anterior sobre GitHub (también se deben corroborar)

El asistente anterior afirmó haber revisado la rama en GitHub y encontró que `web/src/data.ts` intenta cargar `crops.json`, `rotation_rules.json`, `reference_sites.json`, `index.json` y el perfil Texcoco; algunos recursos aparecían 404 en la rama publicada. Si se confirma, explica por qué Vite puede arrancar sin que la aplicación cargue. **No es causa confirmada del fallo local.**

También informó que en `src/crop_models/` (trabajo previo del equipo/Isaac) hay implementaciones WOFOST 8.1 con PCSE para Texcoco, modos potencial/limitado por agua/agua y N, maíz/cebada/haba, calibración/comparación con SIAP, e investigación de NSGA-II/III. **Inspeccionar código y README reales; no confiar en resumen sin comprobar**.

## 7. Problema inmediato reportado por el usuario

El usuario intentó ejecutar:

```bash
cd web && npm run dev
```

**No funcionó**, pero todavía **no proporcionó el mensaje de error ni si Vite alcanzó a arrancar**. Hay que diagnosticarlo reproduciblemente antes de expandir la solución.

### Primer paso técnico pedido a Codex

1. Inspecciona estado de Git, ramas, árbol, `web/package.json`, lockfile, README, `web/src/data.ts`, `web/src/App.tsx`, datos estáticos, `src/advisor`, `src/crop_models`. Determina qué hay realmente (no presupongas archivos del PDF).
2. Reproduce instalación, `npm run build` y `npm run dev` (con límite de tiempo para servidor) en entorno disponible. Captura errores completos. Revisa versiones Node y dependencias, pero **no actualices dependencias a ciegas**.
3. Comprueba rutas HTTP de assets, distinción entre 404 de data y errores de bundling/TS/configuración. Si hacen falta archivos ignorados/no versionados, busca generación confiable, fixtures mínimos explícitos o una guía de bootstrap offline; no inventes datos científicos como reales.
4. Implementa **solo cambios mínimos y seguros** para que un demo en Texcoco funcione en una instalación limpia, con estados claros para fuentes o credenciales faltantes y sin obligar a configurar Firebase/Gemini.
5. Añade pruebas de smoke/reproducibilidad y pasos de arranque en README (instalación, datos, variables de entorno, comando).
6. Antes de tocar el modelo de cultivos, produce una auditoría breve de supuestos y recomendaciones de refactorización, incluidas diferencias entre motor Claude/WOFOST Isaac.
7. Ejecuta pruebas y documenta resultados exactos; señala limitaciones de tu entorno si no puedes reproducir un error.

**No hacer todavía:** añadir todas las fuentes satelitales, reescribir frontend, iniciar integración completa WOFOST/DSSAT, crear una API compleja, alterar archivos de Isaac sin coordinación, realizar merge a `main`, reemplazar números por datos sintéticos presentados como reales, comprometer claves, o hacer llamadas masivas a NASA.

## 8. Progresión posterior, por hitos independientes

- **Hito 1 — Recuperar demo actual:** Texcoco carga y muestra datos y recomendaciones, sin Gemini obligatorio; instalación desde clone nueva reproducible.
- **Hito 2 — Auditoría científica:** ecuaciones, unidades, horizonte, dinámica de nitrógeno/agua, origen de parámetros, datos vs supuestos, comparaciones WOFOST y resultados observados.
- **Hito 3 — `FarmProfile` v2:** esquema versionado, separación de entorno común e información particular del agricultor; disponibilidad/incertidumbre; compatibilidad migratoria.
- **Hito 4 — Datos NASA ampliados:** GPM, MODIS ET/LST, NEX-GDDP-CMIP6, GRACE-FO y SMAP por prioridades, con caches y pruebas de normalización.
- **Hito 5 — Motor agronómico:** API común para proxy rápido y WOFOST de equipo; calibración/validación; manejo de suelo y acciones agrícolas por ciclo.
- **Hito 6 — Optimizador:** objetivos ponderados total 100, restricciones, Pareto, escenarios y métricas de robustez/riesgo interpretables.
- **Hito 7 — Gemini e inclusión:** básico/avanzado, prompts con evidencia estructurada, multilingüe, control de afirmaciones y manejo de incertidumbre.
- **Hito 8 — Cuatro pilotos:** ubicación específica en África oriental, datasets precomputados, pruebas con diversos sistemas y demo consistente.

## 9. Prácticas de implementación y colaboración

- Trabajar en pasos pequeños, con reporte de diagnóstico antes de grandes cambios.
- No borrar trabajo anterior ni reescribirlo sin justificación. Si se modifica la rama, preferir nueva rama `feature/farmadapt-bootstrap` creada desde `daniel-mvp` y conservar la línea base; consultar cuando sea necesario.
- Señalar cada afirmación como **verificado en código**, **reportado en PDF**, **supuesto a validar**, o **decisión del usuario**.
- Cada hito debe entregar algo reproducible, tests, README y definición de “hecho”.
- Preferir configuraciones seguras y sin credenciales obligatorias. No poner keys privadas en frontend.
- Verificar datos, licencias, resoluciones, zonas horarias/calendarios y conversiones de unidades antes de resultados agrícolas.
- Mantener el sistema global por diseño y focalizar validación inicial en cuatro regiones.
- Al terminar el primer hito, explicar al usuario en español qué estaba roto, qué se cambió, cómo ejecutarlo, y cuál será el siguiente hito recomendado.

## 10. Decisiones abiertas (no bloquear primer hito)

- Mensaje real de error del equipo local del usuario.
- Ubicación específica del piloto en África oriental.
- Catálogo y variedades de cultivos por región, calendarios, fuentes de parámetros y precios.
- Extensión de simulación WOFOST vs motor simplificado; selección definitiva de modelos.
- Criterio de evaluación científica y validación con agricultores.
- Estrategia backend/cloud definitiva (Firebase opcional; no imponerla como requisito al inicio).

## 11. Archivos de contexto originales

El usuario compartió dos informes PDF: *Triangulated Rotation Advisor (Oct 30)* y *Reporte de Actualizaciones en la Rama daniel-mvp* (2 noviembre 2026). Este documento sintetiza sus contenidos y la conversación posterior; no reemplaza la inspección del repositorio.

## 12. Criterios de aceptación del PR inicial

- `npm install` / `npm ci` (según lockfile) y `npm run build` funcionan en una instalación limpia bajo versión Node documentada.
- `npm run dev` sirve la app sin fallo fatal por assets faltantes; mapa y pantalla principal muestran estado claro aunque alguna fuente falte.
- Catálogos y al menos un perfil de demo están disponibles o existe un bootstrap reproducible con dependencias explícitas y sin scraping frágil.
- La UI diferencia datos reales, datos no disponibles y datos de ejemplo.
- El modo sin Firebase sigue funcionando.
- Smoke tests/revisión de rutas estáticas y comandos documentados.
- Cambios mínimos; ningún commit sobre `main`; reporte de modificaciones y problemas científicos pendientes.
