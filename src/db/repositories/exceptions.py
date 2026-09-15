"""Repository-layer exceptions."""

from __future__ import annotations


class DuplicateKeyError(Exception):
    """Raised when a unique constraint would be violated."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Subject '{name}' already exists for user")


class InvalidStatusTransitionError(Exception):
    """Raised when a session status transition is not permitted."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Cannot transition session from '{current}' to '{target}'")


class SessionNotFoundError(Exception):
    """Raised when a session id does not exist."""

    def __init__(self, session_id: object) -> None:
        super().__init__(f"Session {session_id} not found")
