"""Optional, application-owned Studio presentation and continuation contract.

An adapter is loaded only from the operator's local registry. It cannot grant
runtime permissions: the service intersects declarations with saved state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class StudioTurn:
    """One submitted input and its actual runtime identities."""

    task: str
    session_id: str | None
    run_id: str | None
    status: str


class StudioAdapter(Protocol):
    """Application hook; no frontend code or execution loop is required."""

    def capabilities(self) -> dict[str, object]:
        """Declare display and input capabilities, not authorizations."""
        ...

    def continuation_task(self, turns: Sequence[StudioTurn], message: str) -> str:
        """Build a new task for a linked Session after the previous turn ends."""
        ...
