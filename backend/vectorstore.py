"""Vector database layer (Node 2 dependency): seeds and queries a Chroma
collection of local events for semantic retrieval, with real date/time
filtering.

Embeddings are computed via Gemini's embedding API rather than Chroma's
bundled ONNX-based default embedding function. The ONNX path relies on a
native library (onnxruntime) compiled expecting AVX2/AVX-512 CPU
instructions, which crashes with an illegal-instruction error on hosts
(like Render's free tier) that lack those instructions. Routing embeddings
through Gemini avoids that native dependency entirely and reuses the same
API key already used for the LLM calls in agent.py.

The seeded dataset only describes *when* things happen in relative terms
("Today, 4:00 PM", "Tomorrow, 3:00 PM", "This weekend, 3:00 PM"), so on every
app startup we resolve those into actual timestamps relative to right now
and reseed the collection fresh.
"""
import os
import re
from datetime import datetime, timedelta, time as dtime

import chromadb
import google.generativeai as genai

from seed_data import EVENTS

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_data")
COLLECTION_NAME = "outsy_events"
EMBEDDING_MODEL = "models/text-embedding-004"

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.IGNORECASE)

_gemini_api_key = os.environ.get("GEMINI_API_KEY")
if not _gemini_api_key:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
        "(or set it in your host's environment variables) with a key from "
        "https://aistudio.google.com/app/apikey"
    )
genai.configure(api_key=_gemini_api_key)

_client = chromadb.PersistentClient(path=CHROMA_DIR)


def _embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    """Embeds a list of strings one at a time via Gemini. task_type should be
    'retrieval_document' when embedding seeded events, or 'retrieval_query'
    when embedding a user's search text — this improves match quality since
    Gemini's embedding model is tuned differently for each role."""
    embeddings = []
    for text in texts:
        result = genai.embed_content(model=EMBEDDING_MODEL, content=text, task_type=task_type)
        embeddings.append(result["embedding"])
    return embeddings


def _event_document(event: dict) -> str:
    """Text blob that gets embedded for semantic search."""
    return (
        f"{event['activity_type']} activity called '{event['name']}' "
        f"in {event['location']}, {event['city']}. {event['description']} "
        f"Time: {event['time']}. Price: {event['price']}."
    )


def _parse_hour_minute(time_str: str) -> tuple[int, int]:
    match = _TIME_RE.search(time_str)
    if not match:
        return 12, 0  # fallback: noon, if a time string ever lacks a clock time
    hour_str, minute_str, meridiem = match.groups()
    hour = int(hour_str) % 12
    if meridiem.upper() == "PM":
        hour += 12
    return hour, int(minute_str)


def _infer_day(time_str: str) -> str:
    """Buckets a free-text time string into today / tomorrow / weekend.
    'Tonight' counts as today."""
    t = time_str.lower()
    if "tomorrow" in t:
        return "tomorrow"
    if "weekend" in t:
        return "weekend"
    return "today"


def _resolve_event_datetime(time_str: str, now: datetime) -> datetime:
    """Turns a relative time string into a concrete datetime relative to `now`."""
    day = _infer_day(time_str)
    if day == "tomorrow":
        date_ = (now + timedelta(days=1)).date()
    elif day == "weekend":
        days_ahead = (5 - now.weekday()) % 7  # Monday=0 ... Saturday=5
        if days_ahead == 0 and now.weekday() != 5:
            days_ahead = 7
        date_ = (now + timedelta(days=days_ahead)).date()
    else:
        date_ = now.date()

    hour, minute = _parse_hour_minute(time_str)
    return datetime.combine(date_, dtime(hour=hour, minute=minute))


def get_collection():
    return _client.get_or_create_collection(name=COLLECTION_NAME)


def reseed_collection() -> int:
    """Drops and rebuilds the collection every call, resolving each event's
    relative time into a real timestamp anchored to *now*, and computing
    embeddings via Gemini instead of Chroma's default ONNX path. Cheap at 30
    docs — called once on every app startup so dates never go stale."""
    try:
        _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # didn't exist yet — fine

    collection = _client.get_or_create_collection(name=COLLECTION_NAME)
    now = datetime.now()

    documents = [_event_document(e) for e in EVENTS]
    embeddings = _embed_texts(documents, task_type="retrieval_document")

    metadatas = []
    for e in EVENTS:
        event_dt = _resolve_event_datetime(e["time"], now)
        metadatas.append({
            "name": e["name"],
            "activity_type": e["activity_type"],
            "location": e["location"],
            "city": e["city"],
            "lat": e["lat"],
            "lng": e["lng"],
            "time": e["time"],
            "day": _infer_day(e["time"]),
            "event_timestamp": event_dt.timestamp(),
            "price": e["price"],
            "description": e["description"],
            "host_name": e["host_name"],
            "host_phone": e["host_phone"],
        })

    collection.add(
        ids=[e["event_id"] for e in EVENTS],
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(EVENTS)


def get_event_by_id(event_id: str) -> dict | None:
    collection = get_collection()
    result = collection.get(ids=[event_id])
    if not result["ids"]:
        return None
    meta = result["metadatas"][0]
    return {"event_id": event_id, **meta}


def semantic_search(query_text: str, top_k: int = 5, where: dict | None = None) -> list[dict]:
    collection = get_collection()
    query_embedding = _embed_texts([query_text], task_type="retrieval_query")[0]

    query_kwargs = {"query_embeddings": [query_embedding], "n_results": top_k}
    if where:
        query_kwargs["where"] = where
    result = collection.query(**query_kwargs)

    matches = []
    ids = result["ids"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    for event_id, meta, distance in zip(ids, metadatas, distances):
        score = max(0.0, 1.0 - distance / 2.0)
        matches.append({"event_id": event_id, "score": round(score, 3), **meta})

    return matches