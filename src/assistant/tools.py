"""The assistant's tools: plain functions shared by the agent loop and the MCP server.

The full comparar_rotaciones result (~25 KB of JSON) is trimmed to what the assistant needs to talk to the
farmer, so each turn costs fewer tokens; every number in it still comes from src.rotations.
"""

import json

from src.rotations import candidates, catalog, places, scoring
from src.rotations.compare import comparar_rotaciones as _comparar

PRIORITY_KEYS = list(scoring.PRIORITIES)
CROP_NAMES = sorted({catalog.name(k) for k in catalog.crops().index} | {"milpa"})


def buscar_lugar(nombre, estado=None):
    """Municipalities or SIAP districts matching a name, to confirm where the farmer is."""
    hits = places.find(nombre, estado)
    rows = hits.drop_duplicates(["state_id", "mun_id"]).head(12)
    return {"encontrados": len(hits.drop_duplicates(["state_id", "mun_id"])),
            "lugares": [{"municipio": r.municipality, "estado": r.state, "distrito_siap": r.ddr_name}
                        for r in rows.itertuples()]}


def _compact(result):
    rotations = []
    for r in result["rotaciones"]:
        card = r["tarjeta"]
        rotations.append({
            "id": r["id"], "nombre": r["nombre"], "secuencia": r["secuencia"],
            "puntaje_con_tus_prioridades": r["puntaje_prioridades"],
            "indicadores": {k: f"{v['texto']} (puntaje {v['puntaje']}, evidencia {v['evidencia']})"
                            if v["puntaje"] is not None else f"{v['texto']} (evidencia {v['evidencia']})"
                            for k, v in r["indicadores"].items()},
            "por_que": card["por_que"], "evidencia": [e["texto"] for e in card["evidencia"]],
            "beneficios": card["beneficios"], "riesgos": card["riesgos"], "vacios": card["vacios"],
            "revisar_con_tecnico": card["revisar_con_tecnico"], "meses_descubiertos": card["meses_descubiertos"],
        })
    costs = result["costos"]
    return {
        "lugar": result["lugar"], "tu_lugar": result["tu_lugar"], "prioridades": result["prioridades"],
        "rotaciones": rotations,
        "costos": {k: costs[k] for k in ("ganancia_calculada", "faltantes", "pregunta_sugerida")},
        "cultivos_de_nicho": result["cultivos_de_nicho"]["cultivos"],
        "unidades": {k: v["unidad"] for k, v in result["rotaciones"][0]["indicadores"].items()},
        "vacios_generales": result["vacios_generales"], "aviso": result["aviso"],
    }


def comparar_rotaciones(lugar, rotacion_actual, estado=None, agua="temporal", prioridades=None, residuo="dejar",
                        tiene_animales=False, mes_siembra=None, pendiente="ligera", propuestas=None, costos=None,
                        rendimiento_propio=None):
    try:
        result = _comparar(lugar, rotacion_actual, estado=estado, agua=agua, prioridades=prioridades or [],
                           residuo=residuo, tiene_animales=bool(tiene_animales), mes_siembra=mes_siembra,
                           pendiente=pendiente, propuestas=propuestas or [], costos=costos,
                           rendimiento_propio=rendimiento_propio)
    except (LookupError, ValueError) as error:          # bad place or crop: tell the model, it asks the farmer
        return {"error": str(error)}
    return _compact(result)


TOOLS = [
    {
        "name": "buscar_lugar",
        "description": ("Busca municipios o distritos SIAP de México por nombre para confirmar dónde está la parcela. "
                        "Úsala cuando el nombre sea ambiguo (p. ej. 'San Juan') o no estés seguro del estado."),
        "input_schema": {"type": "object", "properties": {
            "nombre": {"type": "string", "description": "Nombre del municipio o distrito, como lo dijo el agricultor"},
            "estado": {"type": "string", "description": "Estado, si se conoce"}},
            "required": ["nombre"]},
    },
    {
        "name": "comparar_rotaciones",
        "description": (
            "Compara la rotación actual del agricultor con 3 alternativas usando datos de SIAP (rendimientos, "
            "pérdidas y precios del distrito 2003-2025), clima de NASA POWER, satélites de NASA (MODIS, SMAP) y "
            "coeficientes de FAO/IPCC. Devuelve, para cada rotación, indicadores con puntaje 0-100 y nivel de "
            "evidencia, y una tarjeta: por qué, evidencia, beneficios, riesgos, vacíos de información y qué revisar "
            "con un técnico. Todos los números salen de la herramienta: no inventes otros."),
        "input_schema": {"type": "object", "properties": {
            "lugar": {"type": "string", "description": "Municipio (o distrito SIAP) de la parcela"},
            "estado": {"type": "string", "description": "Estado de México"},
            "rotacion_actual": {"type": "string", "description": (
                "Lo que siembra por año. Años separados por ' - '; '/' separa primavera-verano de otoño-invierno. "
                "Ej.: 'maíz', 'maíz - frijol', 'maíz/garbanzo', 'milpa'. Cultivos posibles: " + ", ".join(CROP_NAMES))},
            "agua": {"type": "string", "enum": ["temporal", "riego"]},
            "prioridades": {"type": "array", "items": {"type": "string", "enum": PRIORITY_KEYS},
                            "description": "Lo que más le importa (1 a 3)"},
            "residuo": {"type": "string", "enum": ["dejar", "pastoreo", "sacar", "quemar"],
                        "description": "Qué hace con el rastrojo"},
            "tiene_animales": {"type": "boolean"},
            "mes_siembra": {"type": "integer", "minimum": 1, "maximum": 12,
                            "description": "Mes en que siembra su cultivo principal, si lo dijo"},
            "pendiente": {"type": "string", "enum": ["plana", "ligera", "fuerte"]},
            "propuestas": {"type": "array", "items": {"type": "string"},
                           "description": "Otras rotaciones que el agricultor quiere comparar, mismo formato"},
            "costos": {"type": "object", "additionalProperties": {"type": "number"},
                       "description": "Costo por hectárea por ciclo (MXN) que dio el agricultor, por cultivo. Ej. {\"maíz\": 9000}"},
            "rendimiento_propio": {"type": "object", "additionalProperties": {"type": "number"},
                                   "description": "Rendimiento de un año normal (t/ha) que dio el agricultor, por cultivo"}},
            "required": ["lugar", "rotacion_actual"]},
    },
]

FUNCTIONS = {"buscar_lugar": buscar_lugar, "comparar_rotaciones": comparar_rotaciones}


def call(name, arguments):
    """Run a tool by name; always returns a JSON string (errors included) for the model."""
    try:
        return json.dumps(FUNCTIONS[name](**arguments), ensure_ascii=False, default=float)
    except Exception as error:          # never crash the conversation on a tool bug
        return json.dumps({"error": f"{type(error).__name__}: {error}"}, ensure_ascii=False)
