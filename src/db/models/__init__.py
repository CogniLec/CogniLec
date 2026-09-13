"""SQLAlchemy models – import all models here so Alembic can discover them."""

from __future__ import annotations

from src.db.models.agent_run import AgentRun
from src.db.models.base import Base
from src.db.models.flashcard import Flashcard, FlashcardReview
from src.db.models.note_asset import AssetType, NoteAsset
from src.db.models.note_link import NoteLink, NoteLinkType
from src.db.models.note_provenance import NoteProvenance
from src.db.models.note_section import NoteSection
from src.db.models.question import Question
from src.db.models.segment import Segment
from src.db.models.session import Session, SessionStatus
from src.db.models.subject import Subject
from src.db.models.topic import Topic
from src.db.models.user import User
from src.db.models.utterance import Utterance

__all__ = [
    "AgentRun",
    "AssetType",
    "Base",
    "Flashcard",
    "FlashcardReview",
    "NoteAsset",
    "NoteLink",
    "NoteLinkType",
    "NoteProvenance",
    "NoteSection",
    "Question",
    "Segment",
    "Session",
    "SessionStatus",
    "Subject",
    "Topic",
    "User",
    "Utterance",
]
