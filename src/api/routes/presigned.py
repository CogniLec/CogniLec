"""FastAPI router - presigned object-store upload URLs (S14)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.services.storage.client import StorageClient
from src.services.storage.models import PresignedURLRequest, PresignedURLResponse

router = APIRouter(tags=["storage"])


@router.post("/presigned-url", response_model=PresignedURLResponse, status_code=status.HTTP_200_OK)
async def create_presigned_url(payload: PresignedURLRequest) -> PresignedURLResponse:
    client = StorageClient()
    try:
        return await client.generate_presigned_upload(
            bucket=payload.bucket,
            key=payload.key,
            expires_in=payload.expires_in,
            content_type=payload.content_type,
        )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Object storage unreachable: {exc}",
        ) from exc
