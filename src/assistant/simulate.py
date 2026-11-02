"""Talk to the assistant in the terminal, or replay scripted farmer conversations.

    source /root/.anthropic_env                      # or export ANTHROPIC_API_KEY=...
    python -m src.assistant.simulate                 # interactive chat
    python -m src.assistant.simulate --script all    # replay every scripted conversation, save transcripts
"""

import argparse
import json
from pathlib import Path

from .agent import Agent, Store

SCRIPTS = {
    "oaxaca_milpa": [
        "Hola",
        "Estoy en Villa de Zaachila, Oaxaca",
        "Siembro maíz cada año, de temporal",
        "Me importa no perder la cosecha y cuidar la tierra",
        "El rastrojo se lo doy a mis borregos",
        "Cuéntame más de la primera opción",
    ],
    "bajio_agua": [
        "Buenas tardes, tengo 4 hectáreas en Celaya Guanajuato de temporal, siembro maíz",
        "Lo que más me preocupa es el agua y ganar un poco más. El rastrojo lo dejo",
        "¿Y lo del garbanzo? ¿Cuánto me quedaría?",
        "Sembrar el maíz me cuesta como 9 mil por hectárea y el garbanzo unos 6 mil",
    ],
    "sinaloa_riego": [
        "Hola, soy de Culiacán, Sinaloa, siembro maíz de riego",
        "Quiero ahorrar agua",
        "No tengo animales y el rastrojo lo dejo",
    ],
    "lugar_ambiguo": [
        "Hola, siembro frijol en San Juan",
        "Es en Durango",
    ],
    "fuera_de_tema": [
        "¿Qué dosis de glifosato le echo al maíz?",
    ],
}


def run_script(agent, name, turns, out_dir):
    user = f"sim:{name}"
    agent.store.reset(user)
    lines = []
    for text in turns:
        lines.append(f"👨‍🌾 {text}")
        for message in agent.reply(user, text):
            lines.append(f"🤖 {message}")
        lines.append("")
    transcript = "\n".join(lines)
    path = Path(out_dir) / f"{name}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript)
    print(transcript)
    return path


def interactive(agent, user="sim:terminal"):
    print("Escribe tu mensaje (Ctrl-D para salir, 'reiniciar' para empezar de cero).")
    while True:
        try:
            text = input("👨‍🌾 ")
        except EOFError:
            break
        for message in agent.reply(user, text):
            print(f"🤖 {message}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--script", help="name of a scripted conversation, or 'all'")
    parser.add_argument("--out", default="data/assistant/transcripts")
    parser.add_argument("--db", default="data/assistant/simulate.sqlite")
    args = parser.parse_args()
    agent = Agent(store=Store(args.db))
    if args.script:
        names = list(SCRIPTS) if args.script == "all" else [args.script]
        for name in names:
            print(f"\n===== {name} =====")
            run_script(agent, name, SCRIPTS[name], args.out)
    else:
        interactive(agent)


if __name__ == "__main__":
    main()
