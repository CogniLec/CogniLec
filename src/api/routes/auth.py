"""Auth endpoints."""

from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
    settings,
    verify_password,
)
from src.api.dependencies.database import get_db_session
from src.api.schemas.auth import RefreshRequest, TokenResponse, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """Register a new user."""
    result = await session.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": user_in.email},
    )
    if result.fetchone():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    hashed_password = get_password_hash(user_in.password)
    result = await session.execute(
        text("""
            INSERT INTO users (email, hashed_password, is_active)
            VALUES (:email, :hashed_password, true)
            RETURNING id, email, is_active, created_at, updated_at
        """),
        {"email": user_in.email, "hashed_password": hashed_password},
    )
    await session.commit()
    user = result.mappings().first()
    return dict(user)  # type: ignore[arg-type]


@router.post("/login", response_model=TokenResponse)
async def login(
    user_in: UserCreate,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Login and get tokens."""
    result = await session.execute(
        text("SELECT id, email, hashed_password, is_active FROM users WHERE email = :email"),
        {"email": user_in.email},
    )
    user = result.mappings().first()

    if user is None or not verify_password(user_in.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    access_token = create_access_token(data={"sub": str(user["id"])})
    refresh_token = create_refresh_token(data={"sub": str(user["id"])})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Exchange a valid refresh token for a new access/refresh token pair.

    The refresh token itself was always issued by /login, but there was
    previously no endpoint to actually redeem it -- see docs/gaps.md.
    Rejects an access token here (token_type check) so the two token kinds
    can't be swapped for each other.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload: dict[str, Any] = jwt.decode(
            body.refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")
        if user_id is None or token_type != "refresh":
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception from None

    result = await session.execute(
        text("SELECT id, is_active FROM users WHERE id = :user_id"),
        {"user_id": user_id},
    )
    user = result.mappings().first()
    if user is None or not user["is_active"]:
        raise credentials_exception

    access_token = create_access_token(data={"sub": str(user["id"])})
    new_refresh_token = create_refresh_token(data={"sub": str(user["id"])})

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
) -> dict[str, object]:
    """Get current user profile."""
    return current_user
