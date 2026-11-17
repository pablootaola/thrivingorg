"""Source adapters. Each returns a list of Opportunity plus a SourceHealth record.

Health vocabulary follows the control plane: HEALTHY, DEGRADED, DOWN, PAYWALL,
and WORKER_CAPABILITY_LIMITED, which attaches to the worker and never to a source.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceHealth:
    source: str
    status: str = "HEALTHY"
    queries: int = 0
    raw_hits: int = 0
    relevant: int = 0
    errors: list[str] = field(default_factory=list)

    def fail(self, msg: str, worker_limited: bool = False) -> None:
        self.errors.append(msg)
        self.status = "WORKER_CAPABILITY_LIMITED" if worker_limited else "DEGRADED"
