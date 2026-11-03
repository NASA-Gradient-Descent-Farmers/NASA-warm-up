# FarmAdapt: diagnóstico y recuperación mínima de Texcoco

Esta iteración se limita al primer hito. Se leyeron completos
`FARMADAPT_CODEX_CONTEXT.md` y `CODEX_START_PROMPT.md` antes de editar código.
Base: `daniel-mvp`, commit `db88c92`; trabajo local en `feature/farmadapt-bootstrap`.
Los dos documentos de contexto ya estaban sin seguimiento y no se modificaron.

## Fallos comprobados

1. **Datos locales excluidos de Git.** La regla `data/` de `.gitignore` también
   excluía `web/public/data/`. Ninguno de los JSON consumidos por la web estaba
   en `git ls-files`, aunque cuatro sí existían localmente.
2. **Error de carga pese a que Vite arranca.** No existe `reference_sites.json`.
   Vite responde a esa ruta con HTTP 200 y `text/html` (el documento de entrada
   de la SPA). `getJson()` comprobaba solo `response.ok` y luego ejecutaba
   `response.json()`: la conversión fallaba y `Promise.all()` rechazaba toda la
   carga inicial. El parámetro `optional` solo manejaba estados HTTP fallidos.
   Se reprodujo el rechazo con el cargador original extraído de Git y la respuesta
   HTML de un archivo ausente, además de comprobar la ruta HTTP real.
3. **Perfiles sin manejo de errores.** `select()` esperaba `loadProfile()` sin
   `try/catch`; una falla dejaba el mensaje de carga sin explicación.
4. **Entorno de ejecución.** El primer `npm run dev` dentro del sandbox terminó
   con `ERROR: SecItemCopyMatching failed -50` y código 139. Fuera del sandbox,
   Vite 7.3.7 arrancó en `127.0.0.1:5173`. La variable heredada
   `NODE_USE_SYSTEM_CA=1` también causó el error al instalar dependencias en el
   sandbox; con `NODE_USE_SYSTEM_CA=0` la instalación aislada pudo continuar.
   Esto es una limitación observada del entorno de la sesión, no evidencia de que
   el usuario tenga el mismo fallo. No se cambió la configuración del proyecto ni
   se desactivó la validación TLS.
5. **Dependencias locales.** El build sobre el `node_modules` preexistente quedó
   bloqueado y se interrumpió; `ls -lO` mostraba archivos de TypeScript con la
   marca `dataless`. En una carpeta temporal con dependencias instaladas desde
   cero, build y pruebas terminaron normalmente. Se reinstalaron también las
   dependencias locales desde el mismo lockfile, sin actualizar versiones.

## Qué hace cada cambio

- **`.gitignore`:** permite únicamente los dos catálogos, el índice y el perfil
  existente de Texcoco. Las descargas raw siguen excluidas. No se regeneraron ni
  alteraron cifras del perfil o de los catálogos.
- **`web/src/data.ts`:** `fetch()` obtiene el recurso; primero se comprueba el
  estado HTTP y después el tipo de contenido. Un recurso opcional ausente
  (404 o HTML del fallback de Vite) devuelve `null`. `loadStatic()` lo convierte
  en una lista vacía de referencias o celdas. Los errores 500 y el JSON malformado
  siguen siendo errores visibles. Un catálogo obligatorio ausente nunca se sustituye
  por datos inventados. `loadProfile()` rechaza perfiles sin años meteorológicos
  o con clima marcado como ausente para evitar cálculos vacíos.
- **`web/src/App.tsx`:** `select()` limpia el perfil anterior mientras carga el
  nuevo, captura la falla y muestra el recurso problemático. El botón de Texcoco
  llama a la misma función usada por el mapa; no añade otro motor. Si falta el
  índice o la biblioteca de referencias, la pantalla lo informa. Un aviso explica
  que los resultados mezclan datos históricos con supuestos de borrador.
- **`web/src/data.test.ts`:** usa los JSON reales del demo para recorrer
  carga → selección → evaluación → explicación sin Firebase. Comprueba cuatro
  tarjetas, objetivos finitos y la ausencia del lente de twins; también reproduce
  respuestas 404, HTML con 200, JSON malformado, error 500 e histórico vacío.

El flujo existente permanece:

```text
data.ts carga catálogos e índice
  → el usuario selecciona Texcoco
  → data.ts carga SiteProfile
  → core.ts calcula tablas y objetivos
  → evaluate.ts ordena opciones y construye tarjetas
  → Results muestra resultados y una explicación determinista o Gemini opcional
```

## Qué implementó realmente el prototipo atribuido a Claude

**Verificado en el árbol y en el diff `21e30ec..db88c92`:** añadió
`src/advisor/` (schema, ingesta, features, generación, referencias y motor),
el notebook de recorrido, siete pruebas Python de features y la web React/Vite.
Los nueve cultivos y reglas existen localmente, pero no estaban versionados.
Existe una lista de 34 lugares en `build_references.py`; eso no significa que
se haya generado la biblioteca: el JSON de salida está ausente.

**Reproducido con el perfil local:** el motor Python evalúa 679 rotaciones y
obtiene 138 filas Pareto. El motor TypeScript evalúa 679 y obtiene **140** con
los controles predeterminados. Por tanto, no se certifica equivalencia entre
motores. Las cifras representan secuencias ordenadas, con posibles rotaciones
cíclicamente equivalentes; no necesariamente 679 planes agronómicamente distintos.

El perfil satisface `SITE_PROFILE_SCHEMA` v0.1. Recalcular sus features usando
únicamente las tres cachés locales (sin llamadas externas, conservando suelo
ausente) reproduce ubicación, climatología mensual, vegetación y suelo.
Hay 16 diferencias de 0.1 mm en lluvia mensual de los años individuales bajo
las bibliotecas Python de esta sesión. Se conservó el archivo original;
la regeneración no se certifica idéntica bit a bit.

## Auditoría inicial frente al trabajo de Isaac

| Aspecto | Motor del advisor | WOFOST del equipo |
|---|---|---|
| Implementación | `core.ts`, `evaluate.ts`, `src/advisor/engine.py` | `src/crop_models/wofost_rotations.py` |
| Tiempo y clima | Sumas/promedios mensuales, búsqueda del mes inicial | Simulación diaria WOFOST 8.1 mediante PCSE |
| Cultivos | Nueve opciones genéricas; parámetros draft | Maíz, cebada y haba con variedades y manejo explícitos |
| Agua entre ciclos | Oferta por cultivo = lluvia + 0.5 × AWC; sin estado hídrico transferido | Transfiere agua al siguiente ciclo |
| Nitrógeno | Oferta heurística y ahorro por leguminosa previa | Fertilización, absorción y N mineral/residuos entre ciclos |
| Evidencia de calibración | Sin calibración local demostrada | Código y reportes de calibración SIAP, holdout y ensayo de fertilización |
| Uso en web actual | Se ejecuta en el navegador | No está conectado a esta web |

La comparación se verificó leyendo código y documentación. **No se ejecutó una
nueva simulación WOFOST ni se reprodujo su calibración** en esta iteración.
`git diff 21e30ec..HEAD -- src/data_ingestion src/crop_models docs/technical_report`
no presenta cambios: el trabajo de Isaac se mantiene intacto.

Pendientes para una auditoría posterior, sin modificarlos ahora:

- Los cinco objetivos actuales son ingreso, cola económica desfavorable, proxy de
  suelo, consumo de agua y erosión. No implementan todavía la definición acordada
  de resiliencia como quinto objetivo; los sliders tampoco exigen sumar 100.
- Las restricciones se comprueban después de Pareto; si no hay opciones factibles,
  `evaluate()` vuelve a todas las opciones. Esto necesita una decisión explícita.
- Los tres lentes no demuestran independencia; NDVI bajo no demuestra suelo
  desnudo ni identifica cultivos. Hay textos de la UI que sobreinterpretan eso.
- El perfil no tiene suelo; el motor utiliza AWC = 120 mm y N = 60 kg/ha como
  supuestos. Las etiquetas de confianza no son probabilidades calibradas.
- `solve_adaptive_dp()` sí contiene inducción de Bellman en Python, con estado
  discreto de cultivo previo y N, pero la transición implementada es determinista;
  usa estadísticas históricas en la recompensa. No es una simulación probabilística
  de estados agua/N ni está conectado al frontend. Suma un crédito de N a dinero
  sin un factor de precio explícito en esa expresión.
- Los defaults y algunas funciones Python/TS difieren; falta una prueba de paridad.
  Antes de integrar WOFOST, conviene acordar unidades, contratos y fixtures comunes.
- Gemini tiene fallback sin credenciales. La existencia y disponibilidad del
  modelo remoto configurado no se verificaron y no son necesarias para el demo.

## Validación

- Entorno Node `v24.11.0`, npm `11.6.1`; sin cambios en `package.json` ni lockfile.
- Instalación aislada: `npm ci --no-audit --no-fund`, caché temporal, **283 paquetes**.
  Se usó `NODE_USE_SYSTEM_CA=0` únicamente para los comandos de verificación de la
  sesión, por el error del llavero descrito arriba.
- `npm run build`: **pasa** en la instalación limpia, con TypeScript y Vite.
  Vite advierte un chunk JS de aproximadamente 908 kB; no bloquea el build.
  No se dividieron bundles porque excedería esta corrección.
- `npm test`: **7 pruebas pasan**; 679 secuencias, 140 filas Pareto, 34 años y
  explicación determinista sin Firebase. Estas pruebas validan ejecución, no
  exactitud agronómica.
- Reproducción separada del cargador original: **1 prueba pasa** al confirmar
  que rechaza el HTML devuelto para la biblioteca opcional ausente. La prueba
  temporal de diagnóstico no se incorpora al proyecto.
- `tests/test_advisor_features.py`: **7 pruebas pasan** con Python 3.11,
  NumPy 2.3.4 y pandas 2.3.1. El intento con el `.venv` preexistente quedó
  bloqueado al importar y se interrumpió; se instaló pytest en una carpeta
  temporal para ejecutar las mismas pruebas, sin modificar ese entorno virtual.
- `npm run dev -- --host 127.0.0.1 --port 5174 --strictPort`: **arranca** en la
  instalación limpia (377 ms). HTTP 200 para `/`, `/src/App.tsx` y los cuatro
  recursos del demo; estos últimos tienen tipo `application/json`.
  `reference_sites.json` sigue devolviendo HTML 200, caso cubierto por el arreglo.
- Tras `npm ci --offline` usando la caché temporal, **también pasan build y las
  siete pruebas web en la carpeta de trabajo original**. Sin modificar la variable
  de certificados, `npm run dev -- --host 127.0.0.1 --strictPort` fuera del sandbox
  arranca allí en **179 ms**, en `http://127.0.0.1:5173/`.
- Validación del perfil contra el schema y comprobación offline de cachés:
  **pasan**, con las diferencias de redondeo ya descritas.
- `git diff --check`: **pasa**. Sin cambios en los archivos de Isaac ni en las
  cifras de los cuatro JSON originales.

No se dispuso de navegador automatizado para comprobar el renderizado visual o
clics reales. La verificación cubre compilación, HTTP y el recorrido del motor.
No se ejecutaron descargas NASA, calibraciones ni el resto de la suite científica
ajena a esta corrección. Los cambios quedan locales, sin commit ni publicación.
Durante el trabajo apareció una modificación ajena en
`Notebooks/master_rotation_advisor_walkthrough.ipynb`; se dejó intacta.
