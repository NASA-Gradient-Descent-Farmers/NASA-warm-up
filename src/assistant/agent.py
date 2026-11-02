"""Conversation loop with Claude: one history per phone number, tool calls run locally.

    from src.assistant.agent import Agent
    agent = Agent()                       # needs ANTHROPIC_API_KEY in the environment
    for message in agent.reply("whatsapp:+52...", "Hola, siembro maíz en Celaya"):
        print(message)
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from . import prompts, tools

MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = 1500
MAX_TOOL_ROUNDS = 4
HISTORY_MESSAGES = 30            # kept per conversation; older turns are dropped
WHATSAPP_LIMIT = 1500            # Twilio rejects WhatsApp bodies over 1,600 characters
DB = Path(os.environ.get("ASSISTANT_DB", "data/assistant/conversations.sqlite"))
RESET_WORDS = {"reiniciar", "reset", "empezar de nuevo", "borrar"}


class Store:
    """Conversation histories in SQLite (survives restarts; fine for a demo with a few users)."""

    def __init__(self, path=DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS chats (user TEXT PRIMARY KEY, messages TEXT, updated REAL)")
        self.lock = threading.Lock()

    def get(self, user):
        row = self.db.execute("SELECT messages FROM chats WHERE user = ?", (user,)).fetchone()
        return json.loads(row[0]) if row else []

    def put(self, user, messages):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO chats VALUES (?, ?, ?)", (user, json.dumps(messages), time.time()))
            self.db.commit()

    def reset(self, user):
        with self.lock:
            self.db.execute("DELETE FROM chats WHERE user = ?", (user,))
            self.db.commit()


def trim(messages, keep=HISTORY_MESSAGES):
    """Last `keep` messages, starting at a plain user message so no tool result loses its tool call."""
    if len(messages) <= keep:
        return messages
    out = messages[-keep:]
    while out and not (out[0]["role"] == "user" and isinstance(out[0]["content"], str)):
        out = out[1:]
    return out


def split(text, limit=WHATSAPP_LIMIT):
    """Split a reply into WhatsApp-sized messages at paragraph, then line, then word boundaries."""
    parts = []
    for block in [b.strip() for b in text.split("\n\n") if b.strip()]:
        if parts and len(parts[-1]) + 2 + len(block) <= limit:
            parts[-1] += "\n\n" + block
            continue
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else block.rfind(" ", 0, limit)
            parts.append(block[:cut].strip())
            block = block[cut:].strip()
        parts.append(block)
    return parts or [""]


class Agent:
    def __init__(self, client=None, store=None, model=MODEL):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.store, self.model = client, store or Store(), model

    def _create(self, messages):
        return self.client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS, tools=tools.TOOLS, messages=messages,
            system=[{"type": "text", "text": prompts.SYSTEM, "cache_control": {"type": "ephemeral"}}])

    def reply(self, user, text):
        """WhatsApp-sized reply messages to one incoming message."""
        if text.strip().lower() in RESET_WORDS:
            self.store.reset(user)
            return [prompts.WELCOME]
        history = self.store.get(user)
        if not history and len(text.strip()) <= 20 and text.strip().lower().strip("!¡.") in {"hola", "buenas", "buenos días", "buenas tardes", "hi", "hello"}:
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": prompts.WELCOME})
            self.store.put(user, history)
            return [prompts.WELCOME]
        history.append({"role": "user", "content": text})
        messages = trim(history)
        final = ""
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = self._create(messages)
            blocks = [b.model_dump(exclude_none=True) for b in response.content]
            messages.append({"role": "assistant", "content": blocks})
            final = "\n\n".join(b["text"] for b in blocks if b["type"] == "text").strip()
            calls = [b for b in blocks if b["type"] == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                break
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c["id"], "content": tools.call(c["name"], c["input"])}
                for c in calls]})
        else:
            final = final or "Perdón, no pude terminar la comparación. ¿Me repites lo que necesitas?"
        self.store.put(user, messages)
        return split(final or "Perdón, no te entendí. ¿Me lo dices de otra forma?")
