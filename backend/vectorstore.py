"""Vector database layer (Node 2 dependency): seeds and queries a Chroma
collection of local events for semantic retrieval, with real date/time
filtering.

The seeded dataset only describes *when* things happen in relative terms
("Today, 4:00 PM", "Tomorrow, 3:00 PM", "This weekend, 3:00 PM"), so on every
app startup we resolve those into actual timestamps relative to right now
and reseed the collection fresh. That keeps "today" and "tomorrow" accurate
across days without needing to hand-maintain real dates in seed_data.py —
just restart the backend on the day you're demoing.

Embeddings use Chroma's bundled local embedding model (no API calls, no
cost) — Gemini is reserved for the reasoning steps in agent.py.
"""
import os
import re
from datetime import datetime, timedelta, time as dtime

import chromadb

from seed_data import EVENTS

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_data")
COLLECTION_NAME = "outsy_events"

_client = chromadb.PersistentClient(path=CHROMA_DIR)

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.IGNORECASE)


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
    relative time into a real timestamp anchored to *now*. Cheap at 30 docs —
    called once on every app startup so dates never go stale."""
    try:
        _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # didn't exist yet — fine

    collection = _client.get_or_create_collection(name=COLLECTION_NAME)
    now = datetime.now()

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
        documents=[_event_document(e) for e in EVENTS],
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
    query_kwargs = {"query_texts": [query_text], "n_results": top_k}
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