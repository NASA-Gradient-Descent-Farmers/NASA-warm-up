"""Spanish explanation cards for each rotation: why it is suggested, the evidence, benefits, risks, gaps and
what to check with a local technician. All text is built from the computed numbers; nothing is generated."""

import numpy as np

from . import catalog
from .indicators import RESIDUE_LABELS

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
CYCLES = {"pv": "primavera-verano", "oi": "otoño-invierno"}

UNITS = {
    "ingreso": "MXN por ha al año (valor de la cosecha, sin costos)",
    "ingreso_p10": "MXN por ha en un año malo (1 de cada 10)",
    "ganancia": "MXN por ha al año que te quedan después de costos",
    "ganancia_p10": "MXN por ha que te quedan en un año malo (1 de cada 10)",
    "prob_perdida": "años de cada 10 en que los costos superan el valor de la cosecha",
    "costo_equilibrio": "lo máximo que puede costarte una ha al año para no perder en un año promedio",
    "costo_equilibrio_8de10": "lo máximo que puede costarte una ha al año para no perder en 8 de cada 10 años",
    "riesgo": "años malos de cada 10 (producción < mitad de lo normal)",
    "agua_temporal": "% del agua que pide el cultivo que cubre la lluvia en un año seco (1 de cada 5)",
    "agua_riego": "mm de riego neto por año en un año típico (sin pérdidas de conducción ni de aplicación)",
    "nitrogeno": "kg de nitrógeno por ha al año (fijación − lo que sale con la cosecha; sin fertilizante)",
    "carbono": "t de carbono que se queda en el suelo por ha al año (residuos y raíces)",
    "erosion": "% de la lluvia erosiva que cae sobre suelo descubierto",
    "plagas": "% de cambios de cultivo que cambian de familia de plantas",
    "forraje": "t de materia seca de forraje por ha al año",
}
EVIDENCE = {"nitrogeno": "baja", "carbono": "baja", "erosion": "media", "plagas": "regla", "forraje": "media",
            "agua": "media"}
SOURCES = {
    "ingreso": "SIAP (rendimiento y precio medio rural del distrito)",
    "ingreso_p10": "SIAP, 2003-2025, a precios recientes",
    "ganancia": "SIAP menos tus costos",
    "ganancia_p10": "SIAP 2003-2025 menos tus costos",
    "prob_perdida": "SIAP 2003-2025 menos tus costos",
    "costo_equilibrio": "SIAP (valor de la cosecha por ha sembrada)",
    "costo_equilibrio_8de10": "SIAP 2003-2025",
    "riesgo": "SIAP, 2003-2025",
    "agua": "FAO-56 (coeficientes de cultivo) con NASA POWER 2001-2025 (ET0 Penman-Monteith; lluvia corregida con CHIRPS)",
    "nitrogeno": "IPCC 2006; Herridge et al. 2008",
    "carbono": "IPCC 2006 (residuos); coeficientes de humificación de Mattila y Rajala (herramienta finlandesa)",
    "erosion": "Índice de Fournier modificado con la lluvia de NASA POWER/CHIRPS y la cobertura del calendario de cultivos",
    "plagas": "Regla agronómica: cambiar de familia interrumpe plagas y enfermedades del suelo",
    "forraje": "IPCC 2006 (residuos) y SIAP (forrajes)",
}

REASONS = {
    "actual": "Es lo que siembras hoy. Sirve de punto de comparación.",
    "leguminosa": ("Alterna {main} con {crop}, una leguminosa. Las leguminosas toman parte de su nitrógeno del aire "
                   "y cortan el ciclo de plagas y enfermedades de los cereales."),
    "milpa": ("Siembra maíz, frijol y calabaza juntos, como en la milpa. El mismo terreno da varias cosechas, "
              "el frijol aporta algo de nitrógeno y la calabaza cubre el suelo."),
    "sequia": "Cambia un año de {main} por {crop}, que tolera mejor la sequía y el calor.",
    "menos_agua": "Cambia un año de {main} por {crop}, que en tu zona necesita menos agua de riego.",
    "invierno": ("Agrega {crop} en otoño-invierno, después de la cosecha, aprovechando {water}. "
                 "El terreno deja de quedar descubierto en invierno."),
    "verano": ("Agrega {crop} en primavera-verano, entre dos cultivos de otoño-invierno, aprovechando {water}. "
               "El terreno deja de quedar descubierto en verano, cuando llueve más fuerte."),
    "forraje": "Incluye {crop} para alimentar a tus animales.",
    "ingreso": "Alterna con {crop}, el cultivo de mayor valor por hectárea entre los que ya se siembran en tu distrito.",
    "propuesta": "Es una rotación que pediste comparar.",
}
TEMPLATE_NAMES = {
    "actual": "Tu rotación actual", "leguminosa": "Con leguminosa", "milpa": "Milpa", "sequia": "Más tolerante a sequía", "menos_agua": "Menos agua de riego",
    "invierno": "Con cultivo de invierno", "verano": "Con cultivo de verano", "forraje": "Con forraje", "ingreso": "Más ingreso", "propuesta": "Tu propuesta",
}
TEMPLATE_RISKS = {
    "leguminosa": ["El precio de {crop} cambia mucho entre años; antes de sembrar, asegura a quién venderlo.",
                   "{Crop} no sustituye todo el fertilizante del cultivo siguiente."],
    "milpa": ["La milpa requiere más mano de obra y es difícil de mecanizar.",
              "Los rendimientos de la milpa aquí son una suposición, no un dato de tu distrito (ver vacíos)."],
    "sequia": ["El año que siembres {crop} no tendrás {main} para autoconsumo."],
    "menos_agua": ["El año que siembres {crop} no tendrás {main}; revisa si conviene por precio y comprador."],
    "invierno": ["El ingreso extra es bruto: al segundo cultivo hay que restarle semilla, siembra, insumos y cosecha.",
                 "Siembra y cosecha más seguidas: más trabajo y menos tiempo para preparar el terreno."],
    "verano": ["El ingreso extra es bruto: al segundo cultivo hay que restarle semilla, siembra, insumos y cosecha.",
               "Siembra y cosecha más seguidas: más trabajo y menos tiempo para preparar el terreno."],
    "forraje": ["El forraje se lleva más biomasa y nutrientes de la parcela."],
    "ingreso": ["Cultivo que quizá no conoces: revisa costos, maquinaria, semilla y comprador antes de cambiar."],
}
CHECKS = {
    "leguminosa": ["¿Qué variedad de {crop} conviene en tu zona y cómo inocularla?",
                   "¿Cuánto fertilizante puedes reducir en el {main} que sigue a {crop}?"],
    "milpa": ["¿Qué densidad y arreglo de siembra de la milpa funcionan en tu zona?"],
    "sequia": ["¿Hay comprador de {crop} cerca y a qué precio?"],
    "menos_agua": ["¿Cuántos riegos necesita {crop} en tu módulo de riego y cuánto cuestan?"],
    "invierno": ["¿Queda suficiente humedad (o agua de riego) después de la cosecha para sembrar {crop}?"],
    "verano": ["¿Alcanza el agua y el tiempo entre cosechas para sembrar {crop} en verano?"],
    "forraje": ["¿Cuánto forraje necesitan tus animales y cuándo?"],
    "ingreso": ["¿Cuánto cuesta producir {crop} por hectárea y quién lo compra?"],
}


def money(x):
    return f"${x:,.0f}"


def months_text(months):
    if not months:
        return "ninguno"
    return ", ".join(MONTHS[m - 1] for m in months)


def crop_names(rotation):
    seen = []
    for year in rotation:
        for c in (year.get("pv"), year.get("oi")):
            if c and c not in seen:
                seen.append(c)
    return seen


def indicator_rows(evaluation, score, water, net=False):
    v = evaluation["values"]
    siap_ev = evaluation["siap_evidence"]
    cost_ev = min([item["cost"]["evidencia"] for item in evaluation["seasons"] if item.get("cost")] or ["sin datos"],
                  key=lambda e: {"alta": 3, "media": 2, "baja": 1}.get(e, 0))
    rows = {
        "ingreso": (v["ingreso"], money(v["ingreso"]) if np.isfinite(v["ingreso"]) else "sin datos", siap_ev),
        "ingreso_p10": (v["ingreso_p10"], money(v["ingreso_p10"]) if np.isfinite(v["ingreso_p10"]) else "sin datos", siap_ev),
        "riesgo": (v["riesgo"], f"{10 * v['riesgo']:.1f} de cada 10" if np.isfinite(v["riesgo"]) else "sin datos", siap_ev),
        "agua": ((v["agua_cubierta"], f"{v['agua_cubierta']:.0%}", "media") if water == "temporal"
                 else (v["agua"], f"{v['agua']:.0f} mm (≈{10 * v['agua']:,.0f} m³/ha)", "media")),
        "nitrogeno": (v["nitrogeno"], f"{v['nitrogeno']:+.0f} kg N/ha", "baja"),
        "carbono": (v["carbono"], f"{v['carbono']:.2f} t C/ha", "baja"),
        "erosion": (v["erosion"], f"{v['erosion']:.0%}", "media"),
        "plagas": (v["plagas"], f"{v['plagas']:.0%}", "regla"),
        "forraje": (v["forraje"], f"{v['forraje']:.1f} t MS/ha", "media"),
    }
    if np.isfinite(v.get("ganancia", np.nan)):
        both = min([siap_ev, cost_ev], key=lambda e: {"alta": 3, "media": 2, "baja": 1}.get(e, 0))
        rows["ganancia"] = (v["ganancia"], signed_money(v["ganancia"]), both)
        rows["ganancia_p10"] = (v["ganancia_p10"], signed_money(v["ganancia_p10"]), both)
        rows["prob_perdida"] = (v["prob_perdida"], f"{10 * v['prob_perdida']:.1f} de cada 10", both)
    if np.isfinite(v.get("costo_equilibrio", np.nan)):
        rows["costo_equilibrio"] = (v["costo_equilibrio"], money(v["costo_equilibrio"]), siap_ev)
        rows["costo_equilibrio_8de10"] = (v["costo_equilibrio_8de10"], money(v["costo_equilibrio_8de10"]), siap_ev)
    if net:      # the income scores were computed on profit: show them there
        score = {**score, "ganancia": score.get("ingreso"), "ganancia_p10": score.get("ingreso_p10"),
                 "ingreso": None, "ingreso_p10": None}
    out = {}
    for name, (value, text, ev) in rows.items():
        unit = UNITS[f"agua_{water}"] if name == "agua" else UNITS[name]
        out[name] = {"valor": None if value is None or not np.isfinite(value) else round(float(value), 3),
                     "texto": text, "unidad": unit, "puntaje": None if score.get(name) is None else round(score[name]),
                     "evidencia": ev, "fuente": SOURCES[name]}
    return out


def siap_evidence_lines(place, evaluation):
    lines = []
    for item in evaluation["seasons"]:
        s, prod = item["season"], item["prod"]
        if prod is None:
            continue
        for part, p in prod.items():
            where = {"distrito": f"en el distrito {place.ddr_name}", "estado": f"en {place.state} (no hay suficientes "
                     "registros en tu distrito)", "nacional": "a nivel nacional (no hay registros en tu distrito ni "
                     "en tu estado)"}[p["level"]]
            lines.append({
                "texto": (f"{catalog.name(part).capitalize()} ({CYCLES[s.cycle]}, {place.water}): {where} hay "
                          f"{p['years']} años con registro y ~{p['sown_ha']:,.0f} ha sembradas por año. Produce "
                          f"{p['expected']:.2f} t por ha sembrada (últimos 10 años, contando lo que se pierde) a "
                          f"{money(p['price'])}/t (precio medio rural, últimos 5 años)."),
                "fuente": "SIAP", "evidencia": p["evidence"]})
    return lines


def signed_money(x):
    return ("+" if x >= 0 else "−") + money(abs(x))


def _fmt_diff(name, d):
    return {"ingreso": lambda: signed_money(d), "ingreso_p10": lambda: signed_money(d), "riesgo": lambda: f"{10 * d:+.1f} años de cada 10",
            "agua_temporal": lambda: f"{100 * d:+.0f} puntos", "agua_riego": lambda: f"{d:+.0f} mm",
            "nitrogeno": lambda: f"{d:+.0f} kg N/ha", "ganancia_p10": lambda: signed_money(d),
            "prob_perdida": lambda: f"{10 * d:+.1f} años de cada 10", "carbono": lambda: f"{d:+.2f} t C/ha",
            "erosion": lambda: f"{100 * d:+.0f} puntos", "plagas": lambda: f"{100 * d:+.0f} puntos",
            "forraje": lambda: f"{d:+.1f} t MS/ha"}[name]()


# indicator, label when better, label when worse, minimum difference, sign (+1: higher is better)
COMPARISONS = [
    ("ingreso_p10", "Más ingreso en un año malo", "Menos ingreso en un año malo", 500, 1),
    ("riesgo", "Menos años malos", "Más años malos", 0.05, -1),
    ("agua_temporal", "La lluvia cubre mejor lo que pide el cultivo en año seco", "La lluvia cubre peor lo que pide el cultivo en año seco", 0.04, 1),
    ("agua_riego", "Necesita menos riego", "Necesita más riego", 30, -1),
    ("nitrogeno", "Mejor balance de nitrógeno", "Saca más nitrógeno del suelo", 10, 1),
    ("carbono", "Deja más carbono (materia orgánica) en el suelo", "Deja menos carbono en el suelo", 0.04, 1),
    ("erosion", "Menos lluvia sobre suelo descubierto", "Más lluvia sobre suelo descubierto", 0.03, -1),
    ("plagas", "Rompe más los ciclos de plagas", "Rompe menos los ciclos de plagas", 0.25, 1),
    ("forraje", "Más forraje", "Menos forraje", 0.5, 1),
]


def compare_lines(values, base, income_diff, water, assumed=False, net=False):
    good, bad = [], []
    word = "ganancia" if net else "ingreso"
    if income_diff:
        d, (lo, hi) = income_diff["media"], income_diff["intervalo_90"]
        text = (f"{signed_money(d)} por ha al año en promedio frente a tu rotación actual "
                f"(rango 90%: {signed_money(lo)} a {signed_money(hi)}; {income_diff['años']} años de SIAP)")
        if assumed:
            (good if d > 0 else bad).append(f"{word.capitalize()} según el supuesto de rendimiento (no medido en tu distrito): " + text)
        elif income_diff["clara"]:
            (good if d > 0 else bad).append((f"Más {word}: " if d > 0 else f"Menos {word}: ") + text)
        else:
            (bad if d < 0 else good).append(f"Diferencia de {word} no clara: " + text)
    comparisons = COMPARISONS
    if net:
        comparisons = [("ganancia_p10", "Te queda más en un año malo", "Te queda menos en un año malo", 500, 1),
                       ("prob_perdida", "Menos años con pérdida", "Más años con pérdida", 0.05, -1)] + COMPARISONS[1:]
    for name, better, worse, threshold, sign in comparisons:
        key = name
        if name.startswith("agua_"):
            if name != f"agua_{water}":
                continue
            key = "agua_cubierta" if water == "temporal" else "agua"
        a, b = values.get(key), base.get(key)
        if a is None or b is None or not (np.isfinite(a) and np.isfinite(b)):
            continue
        d = a - b
        if abs(d) < threshold:
            continue
        (good if sign * d > 0 else bad).append(f"{better if sign * d > 0 else worse} ({_fmt_diff(name, d)})")
    return good, bad


def card(place, template, rotation, evaluation, baseline, income_diff, residue, extra=None, net=False):
    names = crop_names(rotation)
    base_names = crop_names(baseline["rotation"]) if baseline else names
    new = [c for c in names if c not in base_names] or names
    crop = new[-1]
    main = base_names[0] if base_names else crop
    fill = {"crop": catalog.name(crop), "Crop": catalog.name(crop).capitalize(), "main": catalog.name(main),
            "water": ("la humedad que queda en el suelo" if template == "invierno" else "las lluvias")
             if place.water == "temporal" else "el riego"}
    assumed = any(c in catalog.COMPOSITES for c in names) or evaluation["siap_evidence"] != "alta"
    good, bad = ([], []) if template == "actual" else compare_lines(
        evaluation["values"], baseline["evaluation"]["values"], income_diff, place.water, assumed, net)
    risks = bad + [r.format(**fill) for r in TEMPLATE_RISKS.get(template, []) if not (net and "bruto" in r)]
    risks += evaluation["warnings"]
    gaps = list(evaluation["gaps"])
    gaps += cost_gap_lines(rotation, evaluation, baseline if template != "actual" else None)
    if any(c in catalog.COMPOSITES for c in names):
        shares = ", ".join(f"{catalog.name(k).split(' (')[0]} {int(100 * v)}%" for k, v in catalog.MILPA.items())
        gaps.append(f"Rendimiento de la milpa supuesto, como parte de lo que rinde cada cultivo sembrado solo: {shares} "
                    "(suma 1.25; en promedio las asociaciones de cultivos rinden 1.22 veces lo mismo sembrado por "
                    "separado, Yu et al. 2015). Falta validarlo con milpas de tu zona.")
    if any(p["level"] != "distrito" for item in evaluation["seasons"] if item["prod"] for p in item["prod"].values()):
        gaps.append("Algún cultivo no tiene registros suficientes en tu distrito; se usaron datos del estado o nacionales.")
    checks = [c.format(**fill) for c in CHECKS.get(template, [])]
    if template != "actual":
        checks.append("¿Qué plagas, enfermedades y malezas hay en tu zona para estos cultivos?")
    return {
        "por_que": REASONS.get(template, REASONS["propuesta"]).format(**fill) + (f" {extra}" if extra else ""),
        "evidencia": siap_evidence_lines(place, evaluation) + cost_evidence_lines(evaluation)
                     + moisture_lines(place, evaluation),
        "beneficios": good,
        "riesgos": risks,
        "vacios": gaps,
        "revisar_con_tecnico": checks,
        "meses_descubiertos": months_text(evaluation["bare_months"]),
        "residuo": RESIDUE_LABELS[residue],
    }


def cost_evidence_lines(evaluation):
    lines, seen = [], set()
    for item in evaluation["seasons"]:
        c, s = item.get("cost"), item["season"]
        if not c or s.crop in seen:
            continue
        seen.add(s.crop)
        lines.append({"texto": f"Costo de {catalog.name(s.crop)}: {money(c['valor'])} por ha (lo que nos dijiste).",
                      "fuente": "tu dato", "evidencia": c["evidencia"]})
    for item in evaluation["seasons"]:
        p = item["prod"] or {}
        for part, q in p.items():
            if q.get("own_yield_factor"):
                lines.append({"texto": f"{catalog.name(part).capitalize()}: usamos tu rendimiento de año normal; SIAP "
                              "solo aporta cómo varía de un año a otro.", "fuente": "tu dato", "evidencia": "alta"})
    return lines


def cost_gap_lines(rotation, evaluation, baseline):
    """What is missing about costs, and the most an unknown crop can cost to match the current rotation."""
    missing = evaluation["missing_costs"]
    if not missing:
        return []
    names = ", ".join(catalog.name(c) for c in missing)
    lines = [f"No tenemos el costo de {names} en tu zona: el ingreso es el valor de la cosecha, sin restar costos."]
    v = evaluation["values"]
    if baseline is not None:
        base = baseline["evaluation"]["values"]
        if np.isfinite(base.get("ganancia", np.nan)) and np.isfinite(v.get("ingreso", np.nan)):
            years = len(rotation)
            unknown = sum(1 for item in evaluation["seasons"] if item["prod"] is not None and not item.get("cost"))
            room = (v["ingreso"] * years - evaluation["cost_per_year"] * years - base["ganancia"] * years) / unknown
            lines.append(f"Para que esta rotación te deje lo mismo que la actual, {names} tendría que costarte menos de "
                         f"{money(max(room, 0))} por ha" + (" (no alcanza ni con costo cero)." if room <= 0 else "."))
    return lines


def cost_summary(place, evaluations, net):
    """Which costs the farmer gave, which are missing, and the question the assistant should ask."""
    from .costs import reference_for

    used, missing = {}, {}
    for e in evaluations:
        for item in e["seasons"]:
            if item["prod"] is None:
                continue
            c, s = item.get("cost"), item["season"]
            if c:
                used[s.crop] = c
            else:
                missing.setdefault(s.crop, s.cycle)
    missing = {k: v for k, v in missing.items() if k not in used}
    references = [r for r in (reference_for(place, c, cycle) for c, cycle in missing.items()) if r]
    question = None
    if missing:
        question = (f"¿Cuánto te cuesta sembrar una hectárea de {', '.join(catalog.name(c) for c in missing)} "
                    "(semilla, fertilizante, maquinaria o yunta, jornales y cosecha)?")
        if references:
            question += " Como referencia, " + "; ".join(
                f"FIRA estima unos {money(r['mxn_ha'])}/ha para {r['cultivo']} ({r['temporada']}, sin renta de la "
                f"tierra, para rendimientos de {r['rendimiento_supuesto_t_ha']:g} t/ha)" for r in references) + \
                ". ¿El tuyo es parecido?"
    return {
        "ganancia_calculada": net,
        "usados": [{"cultivo": catalog.name(k), "mxn_ha": v["valor"], "fuente": v["fuente"]} for k, v in used.items()],
        "faltantes": [catalog.name(c) for c in missing],     # current rotation's crops first
        "pregunta_sugerida": question,
        "referencias_para_preguntar": references,
        "nota": ("Solo uso los costos que tú me das. Con ellos calculo cuánto te queda y en cuántos años de cada 10 "
                 "perderías dinero; sin ellos te digo lo máximo que puede costarte una hectárea para no perder."),
    }


def satellite_lines(place, modeled_bare):
    """What MODIS sees in the area's cropland, compared with the calendar the tool assumes."""
    from .observed import low_green_months

    if place.observed is None:
        return []
    low, high = low_green_months(place.observed)
    if not low:
        return []
    out = [f"Lo que ve el satélite (MODIS, NASA, 2003-2025): las tierras de cultivo de tu zona están menos verdes en "
           f"{months_text(low)} y más verdes en {months_text(high)}."]
    if modeled_bare:
        overlap = len(set(low) & set(modeled_bare)) / len(set(low))
        green_when_bare = sorted(set(high) & set(modeled_bare))
        if len(green_when_bare) >= 0.6 * len(high):
            out.append(f"Ojo: el satélite ve la zona más verde en {months_text(green_when_bare)}, cuando con tu rotación "
                       "la parcela estaría sin cultivo. Puede ser vegetación que crece con las lluvias (malezas, monte) "
                       "o cultivos de verano de tus vecinos; ese verdor no cuenta como cultivo en la comparación.")
        elif overlap >= 0.6:
            out.append("Coincide con el calendario que supuse para tu rotación.")
        else:
            out.append("No coincide del todo con el calendario que supuse: puede haber riego, otro calendario de "
                       "siembra, malezas o árboles en esos terrenos. Dime cuándo siembras y cosechas para ajustarlo.")
    return out


def moisture_lines(place, evaluation):
    """SMAP relative wetness at sowing for crops sown on residual moisture."""
    from .indicators import MONTH_NAMES, MONTH_OF_DAY
    from .observed import relative_moisture

    lines = []
    for item in evaluation["seasons"]:
        s = item["season"]
        if s.cycle != "oi" or place.water != "temporal":
            continue
        month = int(MONTH_OF_DAY[s.sow_day])
        wet = relative_moisture(place.observed, month + 1)
        if wet is None:
            lines.append({"texto": f"Sin datos de SMAP para {catalog.name(s.crop)}: se supuso el suelo lleno de agua "
                                   "al sembrar.", "fuente": "supuesto", "evidencia": "baja"})
            continue
        lines.append({"texto": (f"Humedad del suelo al sembrar {catalog.name(s.crop)} ({MONTH_NAMES[month]}): SMAP "
                                f"(NASA) la ubica en {wet:.0%} entre lo más seco y lo más húmedo de 2015-2025 (0-100 cm); "
                                "con eso se calcula el agua guardada que puede usar."),
                      "fuente": "NASA SMAP", "evidencia": "media"})
    return lines


GENERAL_GAPS = [
    "Costos: solo usamos los que tú nos das; sin ellos se muestra el valor de la cosecha y el costo máximo para no perder.",
    "SIAP reporta por distrito, no por parcela: tu parcela puede rendir más o menos que el promedio.",
    "Precios: mediana de los últimos 5 años, sin ajustar por inflación ni proyectar a futuro.",
    "Todavía no se incluye el efecto de un cultivo sobre el rendimiento del siguiente (p. ej., maíz después de frijol).",
    "Nitrógeno: balance sin fertilizante ni estiércol, con valores de fijación de estudios internacionales.",
    "Carbono: sirve para comparar opciones, no para medir el cambio real de materia orgánica (eso requiere análisis de suelo).",
    "Clima de NASA POWER en celdas de ~50 km: en hondonadas puede helar más y la lluvia de tu parcela puede variar.",
]


def place_summary(place, current_eval):
    c = place.climate
    lgp = place.lgp
    lines = []
    if lgp:
        lines.append(f"Temporada de lluvias (meses en que la lluvia alcanza al menos la mitad de la evaporación): "
                     f"{MONTHS[lgp[0]]} a {MONTHS[lgp[1]]}.")
    else:
        lines.append("Ningún mes tiene lluvia suficiente para un cultivo de temporal sin riesgo alto.")
    if place.climate_years is not None and not place.climate_years.empty:
        annual = place.climate_years.groupby("year")["rain"].sum()
        lines.append(f"Lluvia anual típica ~{annual.median():,.0f} mm; en un año seco (1 de cada 5) ~{annual.quantile(0.2):,.0f} mm.")
    frost = [m + 1 for m in range(12) if c["frost_prob"].iloc[m] >= 0.2]
    if frost:
        lines.append(f"Meses con riesgo de helada (en 2 de cada 10 años o más hay una noche ≤2 °C): {months_text(frost)}.")
    heat = [m + 1 for m in range(12) if c["heat_days"].iloc[m] >= 3]
    if heat:
        lines.append(f"Meses con calor fuerte (3 días o más ≥35 °C en promedio): {months_text(heat)}.")
    rain = c["rain"].to_numpy()
    if rain[6] < 0.8 * (rain[5] + rain[8]) / 2 or rain[7] < 0.8 * (rain[5] + rain[8]) / 2:
        lines.append("Hay canícula: julio-agosto llueve menos que junio y septiembre.")
    if place.sowing_month is None:
        first = next((item["season"] for item in current_eval["seasons"] if item["season"].cycle == "pv"), None)
        if first is not None:
            month = MONTHS[int(np.searchsorted(np.cumsum([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]), first.sow_day, side="right"))]
            basis = "inicio de las lluvias" if place.water == "temporal" else "fecha típica de riego"
            lines.append(f"Supuse que siembras en {month} ({basis}). Si siembras en otro mes, dímelo para ajustar "
                         "heladas, agua y calendario.")
    bare = current_eval["bare_months"]
    lines.append(f"Con tu rotación actual la parcela queda descubierta en: {months_text(bare)}.")
    lines.extend(satellite_lines(place, bare))
    erosive = [m for m in bare if rain[m - 1] >= 60]
    if erosive:
        lines.append(f"Ojo: en {months_text(erosive)} llueve fuerte y el suelo puede estar descubierto.")
    lines.extend(current_eval["warnings"])
    return lines
