"""FastAPI router - Topics (S31 label edit API)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.database import get_db_session
from src.db.repositories.topic_repo import TopicRepository
from src.ml.clustering.schemas import TopicResponse

router = APIRouter(prefix="/subjects/{subject_id}/topics", tags=["topics"])


class TopicLabelUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=200)


@router.put("/{topic_id}/label", response_model=TopicResponse)
async def update_topic_label(
    subject_id: uuid.UUID,
    topic_id: uuid.UUID,
    body: TopicLabelUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> TopicResponse:
    """Update a topic's label (user edit). Preserved across re-clustering (S32)."""
    repo = TopicRepository(db)
    topic = await repo.get(subject_id, topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    await repo.update_label(subject_id, topic_id, body.label, is_user_edited=True)
    topic = await repo.get(subject_id, topic_id)
    return TopicResponse.model_validate(topic)
