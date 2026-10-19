"""Datenformate zwischen den Services: Event-Envelope, Events v1, DTOs.

Nur Pydantic-Modelle, keine Fachlogik und keine Infrastruktur (import-linter).
"""

from .base import Contract, PositiveId
from .envelope import Envelope, UnknownEventError, new_envelope, parse_envelope

__all__ = [
    "Contract",
    "Envelope",
    "PositiveId",
    "UnknownEventError",
    "new_envelope",
    "parse_envelope",
]
