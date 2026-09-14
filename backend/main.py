from dotenv import load_dotenv
load_dotenv()  # must run before agent.py reads GEMINI_API_KEY

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import QueryRequest, QueryResponse, BookRequest, BookResponse, EventMatch
from vectorstore import reseed_collection
from agent import run_query, run_booking

app = FastAPI(title="Outsy API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # hackathon build — tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.on_event("startup")
def startup():
    seeded = reseed_collection()
    print(f"Reseeded {seeded} events into the vector store with fresh dates/times.")        


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        state = run_query(req.text, req.lat, req.lng)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    return QueryResponse(
        matches=state.matches,
        extracted=state.extracted,
    )


@app.post("/book", response_model=BookResponse)
def book(req: BookRequest):
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    try:
        state = run_booking(req.event_id, req.name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    return BookResponse(
        wa_link=state.wa_link,
        message=state.booking_message,
        event_name=state.event_name,
    )