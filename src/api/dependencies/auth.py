"""Temporary caller-identity dependency.

S12 introduces real auth/RLS; until then callers pass their user id explicitly
so the subjects/sessions endpoints can be exercised end-to-end.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Header


async def get_current_user_id(x_user_id: UUID = Header(..., alias="X-User-Id")) -> UUID:
    return x_user_id
