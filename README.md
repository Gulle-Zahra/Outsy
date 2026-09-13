# Outsy

The autonomous lifestyle & activity concierge for Pakistani youth — built to
the PRD: text in, semantic match out, ready-to-send WhatsApp booking message
in under a minute.

## What's in here

```
outsy/
  backend/
    main.py          FastAPI app — POST /query, POST /book, GET /health
    agent.py          The 3-node LangGraph agent (Intake, Retrieval, Booking Engine), Gemini-powered
    models.py         Pydantic schemas (API contracts + agent state)
    vectorstore.py     Chroma vector DB setup + semantic search
    seed_data.py        ~30 seeded events across Lahore, Karachi, Islamabad
    requirements.txt
    .env.example
  frontend/
    index.html         Single-page chat + map UI (no build step)
  README.md
```

## How the agent works

One LangGraph graph, two ways in:

- **Fresh query** (`POST /query`): `START → Intake → Retrieval → END`
  - **Intake** uses Gemini with structured output to pull `location`,
    `activity_type`, `time_window`, `budget` out of the raw message.
  - **Retrieval** builds a search string from the extracted intent and runs a
    semantic search against the seeded Chroma collection, returning ranked
    matches.
- **Booking** (`POST /book`): `START → Booking Engine → END`
  - Looks up the chosen event, asks Gemini to draft a short, natural
    WhatsApp message, and wraps it into a `wa.me` deep link.

Retrieval embeddings use Chroma's bundled local embedding model (no API
calls, no cost) — Gemini is reserved for the two reasoning steps (intake
extraction and message generation), which is where an LLM actually adds
value over a keyword filter.

## Setup

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then open .env and paste your Gemini key from
# https://aistudio.google.com/app/apikey

uvicorn main:app --reload --port 8000
```

First run downloads Chroma's small local embedding model and seeds the 30
events automatically — you'll see `Seeded 30 events into the vector store.`
in the console. Needs internet access once; after that it's fully offline
for retrieval.

Check it's alive: open `http://localhost:8000/health` → `{"status":"ok"}`.

### 2. Frontend

No build step — it's one HTML file that calls the API at
`http://localhost:8000`. Just open it:

```bash
cd frontend
python3 -m http.server 5500
# then visit http://localhost:5500
```

(Opening `index.html` directly by double-clicking also works in most
browsers, since it only talks to `localhost:8000` over `fetch`.)

## Using it

1. Type a request like *"I'm in Johar Town, bored, want something artistic
   today afternoon"* — optionally tick "share my location."
2. Outsy extracts your intent, searches the seeded dataset, and drops
   matches as pins on the map with cards in the chat, ranked by relevance.
3. Click **Book this** on a card, enter your name, hit **Confirm** — Outsy
   drafts the message and gives you a one-tap **Open in WhatsApp** link
   straight to the host's number.

## Notes on scope (matches the PRD's 48-hour MVP boundaries)

- Text input only — voice-to-text is the PRD's stated stretch goal, not
  implemented here.
- Dataset is the seeded ~30 events (`seed_data.py`), not live scraping.
- No payments, no accounts, no host dashboard — booking handoff is the
  `wa.me` link, exactly as scoped.
- CORS is wide open (`allow_origins=["*"]`) for local hackathon use; tighten
  before deploying anywhere real.

## If something doesn't match well

Retrieval quality depends on the seeded dataset in `seed_data.py` and the
phrasing of `_event_document()` in `vectorstore.py`. If your fixed set of
demo queries returns a weak match, the fastest fix is usually rewording that
event's description, not tuning the model.
