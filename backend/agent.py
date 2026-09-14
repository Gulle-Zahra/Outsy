"""The agentic core of Outsy: a 3-node LangGraph graph.

  Node 1 - Intake          extracts structured intent from raw user text
  Node 2 - RAG / Retrieval semantic search over the seeded event vector DB
  Node 3 - Booking Engine  turns a chosen event into a ready-to-send
                           WhatsApp booking message + wa.me link

The graph has two entry points, chosen at runtime:
  - a fresh query (no event picked yet)  -> Intake -> Retrieval -> END
  - a booking request (event picked)     -> Booking Engine -> END

This keeps "discovery" and "booking" as one coherent agent rather than two
disconnected endpoints, while letting each API call only pay for the work
it actually needs.
"""
import os
import urllib.parse
from datetime import datetime, timedelta

from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI

from models import AgentState, ExtractedIntent
from seed_data import EVENTS
from vectorstore import semantic_search, get_event_by_id

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")


def _llm():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and add your key from https://aistudio.google.com/app/apikey"
        )
    return ChatGoogleGenerativeAI(model=GEMINI_MODEL, google_api_key=api_key, temperature=0.2)


# ---------------------------------------------------------------------------
# Node 1 — Intake
# ---------------------------------------------------------------------------

def intake_node(state: AgentState) -> AgentState:
    structured_llm = _llm().with_structured_output(ExtractedIntent)
    now = datetime.now()
    prompt = (
        f"Today is {now.strftime('%A, %B %d, %Y')}. A user in a Pakistani city is "
        "describing what they want to do, in casual language. Extract the location, "
        "city, activity type, time window, day_reference, earliest_hour, and budget "
        "they mention or clearly imply. For city, use your knowledge of Pakistani "
        "neighbourhoods to work out whether the mentioned area is in Lahore, Karachi, "
        "or Islamabad, even if the user only names a locality and never the city "
        "itself. Use today's actual date above to work out whether a mentioned "
        "weekday (e.g. 'Sunday') falls into 'today', 'tomorrow', or 'weekend'. Leave "
        "a field null if it's genuinely not mentioned or implied — don't invent "
        "details.\n\n"
        f"User message: \"{state.text}\""
    )
    extracted = structured_llm.invoke(prompt)
    state.extracted = extracted
    return state


# ---------------------------------------------------------------------------
# Node 2 — RAG / Retrieval
# ---------------------------------------------------------------------------

KNOWN_CITIES = ["lahore", "karachi", "islamabad"]
# Maps every seeded neighbourhood to its city so "Johar Town" resolves to
# Lahore even though the user never said the city name.
LOCATION_TO_CITY = {e["location"].lower(): e["city"] for e in EVENTS}
# Longest-first so a more specific type (e.g. "tabletop roleplay") is checked
# before a shorter one that might otherwise partial-match first.
KNOWN_ACTIVITY_TYPES = sorted({e["activity_type"].lower() for e in EVENTS}, key=len, reverse=True)


def _detect_city(extracted: ExtractedIntent, raw_text: str) -> str | None:
    # Prefer the LLM's own geography knowledge — it can resolve neighbourhoods
    # we've never seeded an event for (e.g. "Thokar" -> Lahore).
    if extracted.city and extracted.city.strip().lower() in KNOWN_CITIES:
        return extracted.city.strip().capitalize()

    haystack = f"{extracted.location or ''} {raw_text or ''}".lower()
    for city in KNOWN_CITIES:
        if city in haystack:
            return city.capitalize()
    for location, city in LOCATION_TO_CITY.items():
        if location in haystack:
            return city
    return None


def _detect_activity_type(extracted: ExtractedIntent, raw_text: str) -> str | None:
    """Only returns a type when the user's wording actually names one we have
    in the dataset (e.g. 'pottery', 'board games'). Vague requests like
    'something artistic' correctly return None and fall through to pure
    semantic ranking instead of being forced into a category."""
    haystack = f"{extracted.activity_type or ''} {raw_text or ''}".lower()
    for activity in KNOWN_ACTIVITY_TYPES:
        if activity in haystack:
            return activity
    return None


def _detect_day(extracted: ExtractedIntent) -> str | None:
    """Prefer the LLM's structured day_reference; fall back to null."""
    if extracted.day_reference in ("today", "tomorrow", "weekend"):
        return extracted.day_reference
    return None


def _time_range_for_day(day_reference: str | None, earliest_hour: int | None):
    """Returns (start_ts, end_ts) as unix timestamps bounding the requested
    day, or None if no day was specified. Mirrors the same date resolution
    vectorstore.py uses when seeding, so filters line up with stored data."""
    if day_reference is None:
        return None

    now = datetime.now()
    if day_reference == "tomorrow":
        start_date = (now + timedelta(days=1)).date()
        end_date = start_date + timedelta(days=1)
    elif day_reference == "weekend":
        days_ahead = (5 - now.weekday()) % 7  # Monday=0 ... Saturday=5
        if days_ahead == 0 and now.weekday() != 5:
            days_ahead = 7
        start_date = (now + timedelta(days=days_ahead)).date()
        end_date = start_date + timedelta(days=2)  # covers Saturday + Sunday
    else:  # "today"
        start_date = now.date()
        end_date = start_date + timedelta(days=1)

    start_hour = earliest_hour if earliest_hour is not None else 0
    start_dt = datetime.combine(start_date, datetime.min.time()) + timedelta(hours=start_hour)
    end_dt = datetime.combine(end_date, datetime.min.time())
    return start_dt.timestamp(), end_dt.timestamp()


def _build_where(city: str | None = None, time_range: tuple | None = None,
                  activity_type: str | None = None) -> dict | None:
    clauses = []
    if activity_type:
        clauses.append({"activity_type": activity_type})
    if city:
        clauses.append({"city": city})
    if time_range:
        clauses.append({"event_timestamp": {"$gte": time_range[0]}})
        clauses.append({"event_timestamp": {"$lt": time_range[1]}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def retrieval_node(state: AgentState) -> AgentState:
    extracted = state.extracted or ExtractedIntent()
    query_parts = [
        extracted.activity_type or "",
        extracted.location or "",
        extracted.time_window or "",
        state.text or "",
    ]
    query_text = " ".join(p for p in query_parts if p).strip() or (state.text or "")

    city = _detect_city(extracted, state.text or "")
    activity_type = _detect_activity_type(extracted, state.text or "")
    day_reference = _detect_day(extracted)
    time_range = _time_range_for_day(day_reference, extracted.earliest_hour)

    # Relax city/time before ever dropping a confidently-detected activity
    # type — a literal "pottery" request should never silently widen into
    # "any craft workshop" just because Lahore-today has few pottery events.
    where_candidates = []
    if activity_type and city and time_range:
        where_candidates.append(_build_where(city, time_range, activity_type))
    if activity_type and city:
        where_candidates.append(_build_where(city=city, activity_type=activity_type))
    if activity_type and time_range:
        where_candidates.append(_build_where(time_range=time_range, activity_type=activity_type))
    if activity_type:
        where_candidates.append(_build_where(activity_type=activity_type))
    if city and time_range:
        where_candidates.append(_build_where(city, time_range))
    if city:
        where_candidates.append(_build_where(city=city))
    if time_range:
        where_candidates.append(_build_where(time_range=time_range))
    where_candidates.append(None)

    raw_matches = []
    for where in where_candidates:
        raw_matches = semantic_search(query_text, top_k=5, where=where)
        if raw_matches:
            break

    state.matches = [
        {
            "event_id": m["event_id"],
            "name": m["name"],
            "lat": m["lat"],
            "lng": m["lng"],
            "time": m["time"],
            "activity_type": m["activity_type"],
            "location": m["location"],
            "city": m["city"],
            "price": m["price"],
            "description": m["description"],
            "score": m["score"],
        }
        for m in raw_matches
    ]
    return state


# ---------------------------------------------------------------------------
# Node 3 — Booking Engine
# ---------------------------------------------------------------------------

def booking_node(state: AgentState) -> AgentState:
    event = get_event_by_id(state.selected_event_id)
    if event is None:
        raise ValueError(f"Unknown event_id: {state.selected_event_id}")

    name = state.user_name or "a friend"
    prompt = (
        "Write a short, friendly WhatsApp message (2-3 sentences max) from a "
        "customer to a local event host in Pakistan, asking to book a spot. "
        "Be specific and natural, not robotic. Include the activity name, the "
        "time, and the customer's name. Do not add a greeting like 'Dear Sir'.\n\n"
        f"Activity: {event['name']}\n"
        f"Time: {event['time']}\n"
        f"Location: {event['location']}, {event['city']}\n"
        f"Price: {event['price']}\n"
        f"Customer name: {name}"
    )
    response = _llm().invoke(prompt)
    message = response.content.strip()

    encoded_message = urllib.parse.quote(message)
    wa_link = f"https://wa.me/{event['host_phone']}?text={encoded_message}"

    state.booking_message = message
    state.wa_link = wa_link
    state.event_name = event["name"]
    return state


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _route_start(state: AgentState) -> str:
    return "booking" if state.selected_event_id else "intake"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intake", intake_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("booking", booking_node)

    graph.add_conditional_edges(START, _route_start, {"intake": "intake", "booking": "booking"})
    graph.add_edge("intake", "retrieval")
    graph.add_edge("retrieval", END)
    graph.add_edge("booking", END)

    return graph.compile()


outsy_graph = build_graph()


def run_query(text: str, lat: float | None, lng: float | None) -> AgentState:
    result = outsy_graph.invoke(AgentState(text=text, lat=lat, lng=lng))
    return AgentState(**result)


def run_booking(event_id: str, user_name: str) -> AgentState:
    result = outsy_graph.invoke(AgentState(selected_event_id=event_id, user_name=user_name))
    return AgentState(**result)