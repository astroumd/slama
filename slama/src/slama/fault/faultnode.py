"""FaultNode: one entry in the fault DAG. Holds static config plus the
runtime debounce / dedup state used by the fault loop."""
from __future__ import annotations

from dataclasses import dataclass, field

from slama.monitor.monitorpoint import Validity


FAULT_STATES: frozenset[Validity] = frozenset({
    Validity.INVALID_NO_DATA,
    Validity.INVALID_NO_HW,
    Validity.INVALID_HW_BAD,
    Validity.VALID_ERROR,
    Validity.VALID_ERROR_LOW,
    Validity.VALID_ERROR_HIGH,
})


@dataclass
class FaultNode:
    canonical_name: str
    parents: list[str] = field(default_factory=list)
    transient_filter_s: float = 0.0
    actions: list[str] = field(default_factory=list)

    first_fault_t: float | None = None
    last_reported_t: float | None = None
    last_reported_validity: Validity | None = None


@dataclass
class FaultEvent:
    """A single root-fault occurrence dispatched to Action.fire()."""
    canonical_name: str
    validity: Validity
    timestamp: float          # wall-clock (time.time())
    transient_filter_s: float
