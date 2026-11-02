# WhatsApp assistant (MVP)

A farmer chats on WhatsApp. Claude collects the place, the current rotation, rainfed or irrigated, and priorities, one or two questions at a time. It then calls `comparar_rotaciones` and explains the options in short messages, with their evidence, risks and what to check with a technician.

Every number comes from the tool (`src/rotations`); the system prompt (`prompts.py`) forbids inventing any.

```
farmer ──WhatsApp──▶ Twilio ──POST /whatsapp──▶ whatsapp.py ──▶ agent.py ──Claude API (tool use)──▶ tools.py ──▶ src.rotations
                       ▲                            │ answers at once (empty TwiML)
                       └──────── Twilio REST API ◀──┘ then sends the reply, split into ≤1,500-character messages
```

| File | What it is |
|---|---|
| `tools.py` | `buscar_lugar` and `comparar_rotaciones`, their JSON schemas, and the compact result Claude sees (~12 KB instead of ~25 KB) |
| `prompts.py` | Spanish system prompt: what to ask and in which order, how to present results, rules (no invented numbers, no pesticide doses, refer to a technician) |
| `agent.py` | Conversation loop with Claude (default `claude-sonnet-5-5`, set `ASSISTANT_MODEL` to change), one history per phone number in SQLite, `reiniciar` resets it |
| `mcp_server.py` | The same tools as an MCP server (stdio for Claude Desktop, or `--http`) |
| `whatsapp.py` | FastAPI webhook for Twilio, with request signature check |
| `simulate.py` | Chat in the terminal, or replay scripted farmer conversations (`--script all`) |

## Try it locally (no Twilio needed)

```bash
pip install -r requirements-assistant.txt
export ANTHROPIC_API_KEY=...          # never commit it
python -m src.assistant.simulate                  # chat in the terminal
python -m src.assistant.simulate --script all     # 5 scripted farmers; transcripts in data/assistant/transcripts/
```

Transcripts from the first run (Claude Sonnet 5.5, Nov 1 2026) are in `examples/`.

Each conversation with one comparison costs roughly 1-3 US cents on Sonnet.

## Connect WhatsApp (Twilio sandbox)

1. Create a free Twilio account. In *Messaging → Try it out → Send a WhatsApp message*, join the sandbox from each test phone by sending the join code to +1 415 523 8886.
2. Deploy the webhook (below) and copy its public URL.
3. In the sandbox settings, set *When a message comes in* to `https://<your-url>/whatsapp` (method POST).
4. Set the environment variables: `ANTHROPIC_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`, and `PUBLIC_URL=https://<your-url>` (needed for the signature check behind the host's proxy).

**Deploy:** the repo has a `Dockerfile` and a Render blueprint (`render.yaml`). On Render: *New → Blueprint*, pick the repo and branch, and fill in the secrets. Render's free plan sleeps when idle, and the first WhatsApp message after a nap times out, so use the starter plan during the demo. For quick tests from a laptop: `uvicorn src.assistant.whatsapp:app --port 8000` plus `ngrok http 8000`.

**Sandbox limits:** only phones that joined the sandbox can chat; a sandbox session lasts 72 hours after the last join; messages over 1,600 characters are rejected (the bot splits at 1,500).

## Use the tools from Claude Desktop

Add to `claude_desktop_config.json`, with the repo root as working directory:

```json
{"mcpServers": {"field-shift": {"command": "python", "args": ["-m", "src.assistant.mcp_server"], "cwd": "/path/to/NASA-warm-up"}}}
```

Tests: `python -m pytest tests/test_assistant.py` (uses a fake Claude client, no key needed).
