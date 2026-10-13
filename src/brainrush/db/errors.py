"""Domain errors shared by repositories and services."""
from __future__ import annotations


class NotFoundError(LookupError):
    """A required record does not exist."""


class ConflictError(RuntimeError):
    """The record exists but its state forbids the requested transition."""
