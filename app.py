import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from openai import AsyncOpenAI


APP_NAME = "alice-becomes-smarter"
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "3.0"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "120"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))
LOG_REQUESTS = os.getenv("LOG_REQUESTS", "false").lower() in {"1", "true", "yes", "on"}
PROMPT_FILE = Path(os.getenv("PROMPT_FILE", "/opt/alice-gpt/prompt.txt"))

# Optional home settings. HOME_CITY lets "какая погода?" work without naming a city.
# HOME_TIMEZONE overrides meta.timezone from Yandex (useful in the Dialogs test console).
HOME_CITY = os.getenv("HOME_CITY", "").strip()
HOME_TIMEZONE = os.getenv("HOME_TIMEZONE", "").strip()
WEATHER_TIMEOUT_SECONDS = float(os.getenv("WEATHER_TIMEOUT_SECONDS", "1.0"))

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


RUS_WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

RUS_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь и туман",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    56: "слабая ледяная морось",
    57: "сильная ледяная морось",
    61: "слабый дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "слабый ледяной дождь",
    67: "сильный ледяной дождь",
    71: "слабый снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "слабые ливни",
    81: "ливни",
    82: "сильные ливни",
    85: "слабый снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с небольшим градом",
    99: "гроза с сильным градом",
}

location_cache: dict[str, dict] = {}


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


def effective_timezone(meta: dict) -> str:
    timezone_name = HOME_TIMEZONE or meta.get("timezone") or "UTC"
    try:
        ZoneInfo(timezone_name)
        return timezone_name
    except ZoneInfoNotFoundError:
        return "UTC"


def current_datetime_answer(meta: dict, user_text: str) -> str | None:
    text = user_text.lower()

    asks_time = any(
        phrase in text
        for phrase in (
            "который час",
            "сколько времени",
            "текущее время",
            "сейчас времени",
            "какое время",
        )
    )
    asks_date = any(
        phrase in text
        for phrase in (
            "какая сегодня дата",
            "какое сегодня число",
            "какой сегодня день",
            "какой день недели",
            "текущая дата",
            "сегодняшняя дата",
        )
    )

    if not (asks_time or asks_date):
        return None

    timezone_name = effective_timezone(meta)
    now = datetime.now(ZoneInfo(timezone_name))

    date_text = (
        f"{now.day} {RUS_MONTHS[now.month]} {now.year} года, "
        f"{RUS_WEEKDAYS[now.weekday()]}"
    )
    time_text = f"{now.hour:02d}:{now.minute:02d}"

    if asks_time and asks_date:
        return f"Сейчас {time_text}. Сегодня {date_text}."
    if asks_time:
        return f"Сейчас {time_text}."
    return f"Сегодня {date_text}."


def is_weather_query(text: str) -> bool:
    text = text.lower()
    return any(
        key in text
        for key in (
            "погод",
            "температур",
            "градус",
            "дожд",
            "снег",
            "ветер",
            "осад",
        )
    )


def extract_geo_city(request_data: dict) -> str:
    nlu = request_data.get("nlu") or {}
    tokens = nlu.get("tokens") or []

    for entity in nlu.get("entities") or []:
        if entity.get("type") != "YANDEX.GEO":
            continue

        value = entity.get("value") or {}
        city = value.get("city")
        if city:
            return str(city).strip()

        token_range = entity.get("tokens") or {}
        start = token_range.get("start")
        end = token_range.get("end")
        if isinstance(start, int) and isinstance(end, int) and tokens:
            phrase = " ".join(tokens[start:end]).strip()
            if phrase:
                return phrase

    return ""


def fallback_city_from_text(text: str) -> str:
    # Fallback for cases where Yandex did not produce YANDEX.GEO.
    match = re.search(
        r"\b(?:в|во)\s+([а-яёa-z\- ]{2,40}?)(?:\s+(?:сегодня|завтра|сейчас))?[?.!]*$",
        text.lower(),
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def http_json(url: str, timeout: float) -> dict:
    request = UrlRequest(
        url,
        headers={"User-Agent": f"{APP_NAME}/1.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode_city(city: str) -> dict:
    cache_key = city.casefold()
    if cache_key in location_cache:
        return location_cache[cache_key]

    query = urlencode(
        {
            "name": city,
            "count": 1,
            "language": "ru",
            "format": "json",
        }
    )
    data = http_json(
        f"https://geocoding-api.open-meteo.com/v1/search?{query}",
        timeout=WEATHER_TIMEOUT_SECONDS,
    )
    results = data.get("results") or []
    if not results:
        raise ValueError(f"Location not found: {city}")

    location = results[0]
    location_cache[cache_key] = location
    return location


def weather_description(code) -> str:
    try:
        return WEATHER_CODES.get(int(code), "погода без уточнения")
    except (TypeError, ValueError):
        return "погода без уточнения"


def weather_answer(city: str, user_text: str) -> str:
    location = geocode_city(city)

    query = urlencode(
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "precipitation,weather_code,wind_speed_10m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "timezone": "auto",
            "forecast_days": 2,
            "wind_speed_unit": "ms",
        }
    )

    data = http_json(
        f"https://api.open-meteo.com/v1/forecast?{query}",
        timeout=WEATHER_TIMEOUT_SECONDS,
    )

    name = location.get("name") or city
    country = location.get("country")
    place = f"{name}, {country}" if country else name

    daily = data.get("daily") or {}
    wants_tomorrow = "завтра" in user_text.lower()

    if wants_tomorrow:
        idx = 1
        max_values = daily.get("temperature_2m_max") or []
        min_values = daily.get("temperature_2m_min") or []
        code_values = daily.get("weather_code") or []
        rain_values = daily.get("precipitation_probability_max") or []

        if len(max_values) <= idx or len(min_values) <= idx:
            raise ValueError("Tomorrow forecast is missing")

        description = weather_description(code_values[idx] if len(code_values) > idx else None)
        rain_probability = rain_values[idx] if len(rain_values) > idx else None
        rain_part = (
            f", вероятность осадков до {round(rain_probability)} процентов"
            if rain_probability is not None
            else ""
        )
        return (
            f"Завтра, {place}: {description}, "
            f"от {round(min_values[idx])} до {round(max_values[idx])} градусов"
            f"{rain_part}."
        )

    current = data.get("current") or {}
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    precipitation = current.get("precipitation")
    description = weather_description(current.get("weather_code"))

    max_values = daily.get("temperature_2m_max") or []
    min_values = daily.get("temperature_2m_min") or []
    rain_values = daily.get("precipitation_probability_max") or []

    parts = [f"{place}: сейчас {description}"]
    if temp is not None:
        parts.append(f"{round(temp)} градусов")
    if feels is not None:
        parts.append(f"ощущается как {round(feels)}")
    if wind is not None:
        parts.append(f"ветер {round(wind, 1)} метра в секунду")
    if humidity is not None:
        parts.append(f"влажность {round(humidity)} процентов")

    answer = ", ".join(parts) + "."

    if min_values and max_values:
        answer += (
            f" Сегодня от {round(min_values[0])} до {round(max_values[0])} градусов"
        )
        if rain_values and rain_values[0] is not None:
            answer += f", вероятность осадков до {round(rain_values[0])} процентов"
        answer += "."

    if precipitation and precipitation > 0:
        answer += f" За последний интервал выпало около {precipitation:g} миллиметра осадков."

    return answer


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": APP_NAME,
        "model": GROQ_MODEL,
        "home_city_configured": bool(HOME_CITY),
        "home_timezone": HOME_TIMEZONE or None,
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
    meta = data.get("meta") or {}
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

    # Date/time are answered locally from the Yandex device timezone (or HOME_TIMEZONE).
    datetime_answer = current_datetime_answer(meta, user_text)
    if datetime_answer:
        return alice_response(datetime_answer, version)

    # Weather is fetched from Open-Meteo. No API key is required.
    if is_weather_query(user_text):
        city = extract_geo_city(request_data) or fallback_city_from_text(user_text) or HOME_CITY
        if not city:
            return alice_response(
                "Не знаю твой домашний город. Скажи, например, «погода в Казани», "
                "или задай HOME_CITY в настройках сервера.",
                version,
            )

        try:
            started = time.perf_counter()
            answer = await asyncio.wait_for(
                asyncio.to_thread(weather_answer, city, user_text),
                timeout=max(WEATHER_TIMEOUT_SECONDS * 2.5, 1.5),
            )
            elapsed = time.perf_counter() - started
            print(f"Weather response time: {elapsed:.2f}s ({city})", flush=True)
            return alice_response(answer, version)
        except Exception as exc:
            print("Weather error:", repr(exc), flush=True)
            return alice_response(
                "Не удалось быстро получить данные о погоде. Попробуй ещё раз.",
                version,
            )

    history = sessions.setdefault(session_id, [])
    history.append({"role": "user", "content": user_text})
    history = history[-MAX_HISTORY_MESSAGES:]
    sessions[session_id] = history

    timezone_name = effective_timezone(meta)
    now = datetime.now(ZoneInfo(timezone_name))
    live_context = (
        f"Текущая локальная дата и время пользователя: "
        f"{now.day} {RUS_MONTHS[now.month]} {now.year}, "
        f"{RUS_WEEKDAYS[now.weekday()]}, {now.hour:02d}:{now.minute:02d}. "
        f"Часовой пояс: {timezone_name}."
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\n" + live_context,
        }
    ] + history

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
