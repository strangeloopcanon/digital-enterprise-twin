from __future__ import annotations

from typing import Protocol


class ToolRegistryView(Protocol):
    """Minimal typed view of tool catalog for monitors."""

    def get(self, name: str):  # pragma: no cover - shape contract only
        ...
