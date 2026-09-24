import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from openai import AsyncOpenAI


APP_NAME = "alice-becomes-smarter"
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "3.3"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "120"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))
LOG_REQUESTS = os.getenv("LOG_REQUESTS", "false").lower() in {"1", "true", "yes", "on"}
PROMPT_FILE = Path(os.getenv("PROMPT_FILE", "/opt/alice-gpt/prompt.txt"))

DEFAULT_SYSTEM_PROMPT = """Ты отдельный голосовой ИИ-помощник, работающий внутри пользовательского навыка Яндекс Алисы.

Ты НЕ являешься Алисой и НЕ являешься моделью Яндекса.
Твои ответы генерирует внешняя языковая модель через Groq API.
Яндекс Алиса используется только как голосовой интерфейс: она распознаёт речь пользователя и озвучивает твой ответ.

Правила:
- отвечай на русском языке, если пользователь не попросил иначе;
- отвечай естественно и по существу;
- обычно отвечай 1-3 короткими предложениями;
- если нужен полный ответ, можешь ответить подробнее;
- не используй Markdown и таблицы;
- не начинай ответ с лишних вступлений;
- не выдавай себя за Яндекс Алису;
- если вопрос простой, отвечай максимально кратко;
- ответ будет озвучиваться голосом, поэтому формулируй его так, чтобы он хорошо звучал вслух.
"""


def load_prompt() -> str:
    try:
        text = PROMPT_FILE.read_text(encoding="utf-8").strip()
        return text or DEFAULT_SYSTEM_PROMPT
    except FileNotFoundError:
        return DEFAULT_SYSTEM_PROMPT


SYSTEM_PROMPT = load_prompt()

app = FastAPI(title=APP_NAME)

client = AsyncOpenAI(
    api_key=os.environ["GROQ_API_KEY"],
    base_url="https://api.groq.com/openai/v1",
    timeout=min(MODEL_TIMEOUT_SECONDS, 3.5),
    max_retries=0,
)

# Для личного использования история хранится в RAM.
sessions: dict[str, list[dict[str, str]]] = {}


def alice_response(text: str, version: str = "1.0", end_session: bool = False):
    text = (text or "").strip()
    if not text:
        text = "Не получилось сформировать ответ. Попробуй ещё раз."

    # response.text у Яндекс Диалогов ограничен 1024 символами.
    if len(text) > 1000:
        text = text[:1000]

    return {
        "version": version,
        "response": {
            "text": text,
            "end_session": end_session,
        },
    }


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": APP_NAME,
        "model": GROQ_MODEL,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        return alice_response("Некорректный запрос.")

    if LOG_REQUESTS:
        print("YANDEX REQUEST:", json.dumps(data, ensure_ascii=False), flush=True)

    version = data.get("version", "1.0")
    session = data.get("session", {})
    request_data = data.get("request", {})

    session_id = session.get("session_id", "unknown")
    user_text = request_data.get("original_utterance", "").strip()

    # Health/ping without LLM call.
    if user_text.lower() == "ping":
        return alice_response("pong", version)

    if session.get("new", False):
        sessions[session_id] = []
        if not user_text:
            return alice_response(
                "Привет! Я умный помощник. Что хочешь спросить?",
                version,
            )

    if not user_text:
        return alice_response("Слушаю. Что хочешь спросить?", version)

    if user_text.lower() in {
        "выход",
        "выйти",
        "закройся",
        "завершить",
        "хватит",
        "стоп",
    }:
        sessions.pop(session_id, None)
        return alice_response("Хорошо. До встречи!", version, end_session=True)

    history = sessions.setdefault(session_id, [])
    history.append({"role": "user", "content": user_text})
    history = history[-MAX_HISTORY_MESSAGES:]
    sessions[session_id] = history

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        started = time.perf_counter()

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.6,
                extra_body={"reasoning_effort": "none"},
            ),
            timeout=MODEL_TIMEOUT_SECONDS,
        )

        elapsed = time.perf_counter() - started
        answer = (response.choices[0].message.content or "").strip()

        print(f"Groq response time: {elapsed:.2f}s", flush=True)

        if not answer:
            return alice_response(
                "Не получилось сформировать ответ. Попробуй ещё раз.",
                version,
            )

        history.append({"role": "assistant", "content": answer})
        sessions[session_id] = history[-MAX_HISTORY_MESSAGES:]

        if LOG_REQUESTS:
            print("FINAL ANSWER:", repr(answer), flush=True)

        return alice_response(answer, version)

    except asyncio.TimeoutError:
        print(f"Groq timeout: > {MODEL_TIMEOUT_SECONDS}s", flush=True)
        return alice_response(
            "Ответ занял слишком много времени. Попробуй ещё раз.",
            version,
        )
    except Exception as exc:
        print("Groq error:", repr(exc), flush=True)
        return alice_response(
            "Не получилось получить ответ. Попробуй ещё раз.",
            version,
        )
