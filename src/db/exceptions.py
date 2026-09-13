"""Database exceptions."""

from __future__ import annotations


class SubjectNotFoundError(Exception):
    """Raised when a subject is not found."""


class SubjectAlreadyExistsError(Exception):
    """Raised when provisioning a subject that already exists."""


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""


class DuplicateKeyError(Exception):
    """Raised on unique constraint violation."""


class InvalidTransitionError(Exception):
    """Raised when an illegal session status transition is attempted (S23)."""


class SessionFailedError(Exception):
    """Raised when an operation cannot proceed because a session has failed (S23)."""
