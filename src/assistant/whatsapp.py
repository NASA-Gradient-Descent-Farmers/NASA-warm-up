"""Twilio WhatsApp webhook: receives a farmer's message, answers with the agent.

    uvicorn src.assistant.whatsapp:app --host 0.0.0.0 --port 8000

Environment:
    ANTHROPIC_API_KEY     Claude API key
    TWILIO_ACCOUNT_SID    Twilio account SID (starts with AC)
    TWILIO_AUTH_TOKEN     Twilio auth token (also used to check that requests come from Twilio)
    TWILIO_WHATSAPP_FROM  sender, e.g. whatsapp:+14155238886 (the Twilio sandbox number)
    PUBLIC_URL            optional: the public base URL Twilio calls (for the signature check behind proxies)
    SKIP_TWILIO_SIGNATURE set to 1 only for local tests

Twilio expects an answer within ~15 s, and a comparison with Claude can take longer, so the webhook answers
at once and the reply is sent afterwards through Twilio's REST API, split into WhatsApp-sized messages.
"""

import logging
import os
import time

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

log = logging.getLogger("field-shift")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Field Shift WhatsApp assistant")
_agent = None
_twilio = None
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
SORRY = "Perdón, tuve un problema para responderte. Intenta de nuevo en un momento, o escribe *reiniciar*."


def agent():
    global _agent
    if _agent is None:
        from .agent import Agent
        _agent = Agent()
    return _agent


def twilio():
    global _twilio
    if _twilio is None:
        from twilio.rest import Client
        _twilio = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    return _twilio


def send(to, body):
    twilio().messages.create(from_=os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"), to=to, body=body)


def answer(user, text):
    start = time.time()
    try:
        messages = agent().reply(user, text)
    except Exception:
        log.exception("agent failed for %s", user[-4:])
        messages = [SORRY]
    for message in messages:
        try:
            send(user, message)
        except Exception:
            log.exception("twilio send failed")
            break
        time.sleep(0.5)                      # keep the messages in order on the phone
    log.info("answered %s in %.1fs (%d messages)", user[-4:], time.time() - start, len(messages))


def valid_signature(request, form):
    if os.environ.get("SKIP_TWILIO_SIGNATURE") == "1":
        return True
    from twilio.request_validator import RequestValidator
    url = str(request.url)
    if os.environ.get("PUBLIC_URL"):
        url = os.environ["PUBLIC_URL"].rstrip("/") + request.url.path
    return RequestValidator(os.environ["TWILIO_AUTH_TOKEN"]).validate(
        url, dict(form), request.headers.get("X-Twilio-Signature", ""))


@app.get("/", response_class=PlainTextResponse)
def health():
    return "ok"


@app.post("/whatsapp")
async def whatsapp(request: Request, background: BackgroundTasks):
    form = await request.form()
    if not valid_signature(request, form):
        raise HTTPException(status_code=403, detail="invalid Twilio signature")
    user, text = form.get("From", ""), (form.get("Body") or "").strip()
    if user and text:
        background.add_task(answer, user, text)
    elif user and int(form.get("NumMedia", 0) or 0):
        background.add_task(send, user, "Por ahora solo entiendo mensajes de texto. ¿Me lo escribes?")
    return Response(content=EMPTY_TWIML, media_type="application/xml")
