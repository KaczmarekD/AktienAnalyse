"""Datenformate zwischen den Services: Event-Envelope, Events v1, DTOs.

Nur Pydantic-Modelle, keine Fachlogik und keine Infrastruktur (import-linter).
"""

from .base import Contract
from .envelope import Envelope, new_envelope

__all__ = ["Contract", "Envelope", "new_envelope"]
