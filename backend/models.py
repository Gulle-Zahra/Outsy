"""Pydantic schemas shared across the API layer and the agent graph."""
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------- Intake (structured extraction target) ----------

class ExtractedIntent(BaseModel):
    """What Node 1 (Intake) pulls out of the user's raw message."""
    location: Optional[str] = Field(
        default=None,
        description="Neighbourhood, area, or city mentioned or implied (e.g. 'Johar Town', 'Gulberg', 'Karachi')."
    )
    city: Optional[str] = Field(
        default=None,
        description="Exactly one of 'Lahore', 'Karachi', or 'Islamabad' — infer this from the mentioned neighbourhood "
                    "using your knowledge of Pakistani geography (e.g. 'Thokar Niaz Baig' implies Lahore, 'Clifton' "
                    "implies Karachi, 'F-7' implies Islamabad). Null if the area doesn't clearly belong to one of "
                    "these three cities, or if no location was mentioned at all."
    )
    activity_type: Optional[str] = Field(
        default=None,
        description="The kind of activity requested, in plain words (e.g. 'pottery', 'board games', 'open mic', 'something artistic')."
    )
    time_window: Optional[str] = Field(
        default=None,
        description="When they want to go, in the user's own words (e.g. 'today afternoon', 'tonight', 'after 1pm tomorrow')."
    )
    day_reference: Optional[str] = Field(
        default=None,
        description="Exactly one of 'today', 'tomorrow', or 'weekend' if the message implies one of these, otherwise null. "
                    "'Tonight' and 'this afternoon' count as 'today'. A specific weekday like 'Sunday' should be mapped to "
                    "'today', 'tomorrow', or 'weekend' based on what day it actually is relative to today."
    )
    earliest_hour: Optional[int] = Field(
        default=None,
        description="If the user gives an earliest start time (e.g. 'after 1pm', 'from 5 onwards'), the hour in 24-hour "
                    "format (0-23). Null if no specific time was mentioned."
    )
    budget: Optional[str] = Field(
        default=None,
        description="Any budget or price hint mentioned (e.g. 'under 1000', 'cheap', 'no budget mentioned')."
    )


# ---------- API request/response contracts ----------

class QueryRequest(BaseModel):
    text: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class EventMatch(BaseModel):
    event_id: str
    name: str
    lat: float
    lng: float
    time: str
    activity_type: str
    location: str
    city: str
    price: str
    description: str
    score: float


class QueryResponse(BaseModel):
    matches: List[EventMatch]
    extracted: ExtractedIntent


class BookRequest(BaseModel):
    event_id: str
    name: str


class BookResponse(BaseModel):
    wa_link: str
    message: str
    event_name: str


# ---------- Agent graph state ----------

class AgentState(BaseModel):
    # inputs
    text: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    selected_event_id: Optional[str] = None
    user_name: Optional[str] = None

    # produced along the way
    extracted: Optional[ExtractedIntent] = None
    matches: List[EventMatch] = Field(default_factory=list)
    wa_link: Optional[str] = None
    booking_message: Optional[str] = None
    event_name: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True