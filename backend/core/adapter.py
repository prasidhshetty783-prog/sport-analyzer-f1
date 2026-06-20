"""SportAdapter: the seam future sports plug into. F1 implements it now.
Deliberately minimal (working agreement: don't over-engineer beyond this)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SessionInfo:
    session_id: str
    name: str
    year: int
    country: str
    total_laps: int
    duration_s: float
    mode: str  # "replay" | "live"


class SportAdapter(ABC):
    @abstractmethod
    def list_sessions(self) -> list[SessionInfo]:
        """Sessions available to stream (recorded fixtures and/or live)."""

    @abstractmethod
    def create_engine(self, session_id: str, bus) -> object:
        """Build the event producer (replay engine / live client) for a session."""

    @abstractmethod
    def get_static_assets(self, session_id: str) -> dict:
        """Track outline, circuit metadata, etc. (Phase 2+)."""
