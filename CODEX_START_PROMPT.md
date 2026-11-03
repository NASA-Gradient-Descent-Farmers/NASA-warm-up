# Prompt inicial para Codex — FarmAdapt

Estoy trabajando en **FarmAdapt**, una solución para NASA Space Apps Challenge 2026 (*Adapting Farms with NASA Data*). El repositorio es https://github.com/NASA-Gradient-Descent-Farmers/NASA-warm-up y la rama que contiene el MVP anterior es `daniel-mvp`.

**Lee primero `FARMADAPT_CODEX_CONTEXT.md` completo.** Contiene decisiones del producto, objetivos de optimización, arquitectura de datos, fuentes NASA, trabajo previo reportado y la hoja de ruta. Los reportes de Claude incluidos allí son información por verificar, NO garantía de que el código funcione.

Quiero construirlo paso a paso, conservando y mejorando lo que ya existe. **En esta primera iteración, no implementes toda la arquitectura**. Tu tarea es **diagnosticar y recuperar la aplicación web existente**: ejecuté `cd web && npm run dev` y no funcionó. Todavía no sé si el error proviene de Node/npm/Vite, archivos JSON ausentes, configuración o el propio código.

Procede así:

1. Inspecciona el repositorio y la rama real (`git status`, `git branch`, `web/package.json`, lockfile, Vite, `App.tsx`, `data.ts`, `public/data/`, `src/advisor/`, `src/crop_models/`). No modifiques `main` ni sobrescribas trabajo de Isaac.
2. Intenta reproducir instalación, build y servidor de desarrollo con tiempo limitado y diagnostica los errores. Si el entorno impide una prueba, indícalo y presenta los comandos exactos para mi computadora.
3. Comprueba especialmente la hipótesis de **JSON de demo faltantes** (`crops.json`, `rotation_rules.json`, `index.json`, `profiles/...`, `reference_sites.json`). No inventes perfiles agronómicos reales ni escondas datos faltantes.
4. Propón e implementa **la corrección mínima segura** para que un demo de Texcoco cargue desde un clone limpio, idealmente sin requerir Firebase ni credenciales NASA en tiempo real. Incluye un fallback claro cuando falten datos y documentación de bootstrap si debe ejecutarse un script.
5. Ejecuta verificaciones (`npm run build`, pruebas existentes y smoke check del arranque/recursos si es posible); documenta qué pruebas pasaron o quedaron pendientes.
6. Antes de expandir el proyecto, entrega un resumen de los problemas, archivos cambiados, cómo correr la app y una auditoría inicial del motor Claude frente al trabajo WOFOST existente de Isaac.

**Reglas:** haz cambios pequeños, conservadores, trazables y reproducibles. No integres GPM/GRACE-FO/NEX-GDDP-CMIP6 todavía, no reescribas el motor agronómico ni el frontend, no cambies dependencias sin razón, no corras descargas masivas, no agregues secretos. Mantén datos de ejemplo claramente etiquetados y no sobreprometas validez agronómica. Si no tienes permiso para hacer operaciones Git destructivas, detente y pregunta. Responde en español.

**Definición de listo para esta primera iteración:** una instalación limpia puede mostrar la pantalla principal y el perfil/escenario de Texcoco o, si el dato no está disponible, un mensaje claro y una ruta reproducible para generarlo; el README indica comandos; el build pasa; se reportan las limitaciones restantes.
