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
