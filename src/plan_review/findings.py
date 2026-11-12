"""The result type every rule returns."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    """Ordered so that a higher value is more serious."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name.lower()


# A finding at or above this severity makes the command exit with status 1.
BLOCKING_SEVERITY = Severity.HIGH


@dataclass(frozen=True)
class Finding:
    """One risky change: which rule matched, how serious it is, where, and why."""

    rule_id: str
    severity: Severity
    address: str
    why: str

    @property
    def is_blocking(self) -> bool:
        return self.severity >= BLOCKING_SEVERITY
