"""Data models for the insight engine."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Optional


@dataclasses.dataclass
class Insight:
    """An insight row ready to write to the store.

    Matches the `insight` table schema in data-model.md.
    """

    kind: str
    severity: str  # 'info' | 'notice' | 'warning'
    app_id: Optional[int]
    endpoint_id: Optional[int]
    title: str
    body: str
    suggestion: Optional[str]
    evidence: dict[str, Any]
    created_at: int

    def evidence_json(self) -> str:
        return json.dumps(self.evidence)
