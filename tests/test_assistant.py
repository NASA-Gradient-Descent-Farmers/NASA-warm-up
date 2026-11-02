"""Tests for the WhatsApp assistant (src/assistant), with a fake Claude client: no API key or network needed."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.assistant import agent as agent_mod
from src.assistant import tools
from src.assistant.agent import Agent, Store, split, trim


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in vars(self).items() if v is not None}


class FakeClient:
    """Answers with a scripted list of responses and records what it was sent."""

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs["messages"])))
        return self.responses.pop(0)


def text(t):
    return SimpleNamespace(content=[Block(type="text", text=t)], stop_reason="end_turn")


def tool_use(name, args, id_="t1"):
    return SimpleNamespace(content=[Block(type="tool_use", id=id_, name=name, input=args)], stop_reason="tool_use")


def test_split_respects_whatsapp_limit():
    long = "\n\n".join(["párrafo " * 60] * 6)
    parts = split(long, limit=500)
    assert all(len(p) <= 500 for p in parts) and len(parts) > 3
    assert split("hola") == ["hola"]


def test_trim_never_starts_with_a_tool_result():
    msgs = []
    for i in range(20):
        msgs += [{"role": "user", "content": f"m{i}"},
                 {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "{}"}]},
                 {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}]
    out = trim(msgs, keep=10)
    assert out[0]["role"] == "user" and isinstance(out[0]["content"], str)


def test_agent_runs_the_tool_and_keeps_history(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "FUNCTIONS", {**tools.FUNCTIONS, "buscar_lugar": lambda nombre, estado=None: {"lugares": [nombre]}})
    client = FakeClient([tool_use("buscar_lugar", {"nombre": "San Juan"}), text("¿Cuál San Juan?")])
    bot = Agent(client=client, store=Store(tmp_path / "c.sqlite"))
    assert bot.reply("u1", "Siembro en San Juan") == ["¿Cuál San Juan?"]
    sent = client.calls[1]
    assert sent[-1]["content"][0]["type"] == "tool_result" and "San Juan" in sent[-1]["content"][0]["content"]
    history = bot.store.get("u1")
    assert history[0]["content"] == "Siembro en San Juan" and len(history) == 4


def test_greeting_and_reset_need_no_model_call(tmp_path):
    client = FakeClient([])
    bot = Agent(client=client, store=Store(tmp_path / "c.sqlite"))
    assert "municipio" in bot.reply("u1", "Hola")[0]
    assert "municipio" in bot.reply("u1", "reiniciar")[0]
    assert client.calls == [] and bot.store.get("u1") == []


def test_tool_errors_go_back_to_the_model():
    out = json.loads(tools.call("comparar_rotaciones", {"lugar": "Lugar que no existe", "rotacion_actual": "maíz"}))
    assert "error" in out
    out = json.loads(tools.call("comparar_rotaciones", {"lugar": "x", "rotacion_actual": "maíz", "inventado": 1}))
    assert "error" in out


@pytest.mark.skipif(not Path("data/shared/rotations_siap_crop_years.parquet").exists(), reason="no shared data")
def test_compact_result_keeps_what_the_assistant_needs():
    out = json.loads(tools.call("comparar_rotaciones", {"lugar": "Celaya", "estado": "Guanajuato", "rotacion_actual": "maíz"}))
    assert len(out["rotaciones"]) >= 3 and out["costos"]["pregunta_sugerida"]
    card = out["rotaciones"][1]
    assert {"por_que", "evidencia", "beneficios", "riesgos", "vacios", "revisar_con_tecnico"} <= set(card)
    assert len(json.dumps(out, ensure_ascii=False)) < 20000


def test_webhook_answers_at_once_and_replies_in_background(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from src.assistant import whatsapp

    monkeypatch.setenv("SKIP_TWILIO_SIGNATURE", "1")
    sent = []
    monkeypatch.setattr(whatsapp, "agent", lambda: SimpleNamespace(reply=lambda user, t: [f"eco: {t}", "fin"]))
    monkeypatch.setattr(whatsapp, "send", lambda to, body: sent.append((to, body)))
    monkeypatch.setattr(whatsapp.time, "sleep", lambda s: None)
    r = TestClient(whatsapp.app).post("/whatsapp", data={"From": "whatsapp:+5215555555555", "Body": "hola"})
    assert r.status_code == 200 and "<Response>" in r.text
    assert sent == [("whatsapp:+5215555555555", "eco: hola"), ("whatsapp:+5215555555555", "fin")]


def test_webhook_rejects_unsigned_requests(monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from src.assistant import whatsapp

    monkeypatch.delenv("SKIP_TWILIO_SIGNATURE", raising=False)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    r = TestClient(whatsapp.app).post("/whatsapp", data={"From": "whatsapp:+1", "Body": "hola"})
    assert r.status_code == 403
