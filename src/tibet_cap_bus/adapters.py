from __future__ import annotations

from typing import Protocol

from .models import Cap, CapReceipt, DistributedCap, ExecutionResult, LanePolicy, PhaseEvidence, UsageEvent


class CausalPlacer(Protocol):
    def place(self, cap: Cap) -> tuple[int, PhaseEvidence]:
        """Assign a causal rank to a cap."""


class Distributor(Protocol):
    def distribute(self, cap: Cap, causal_rank: int) -> tuple[str, LanePolicy, PhaseEvidence]:
        """Assign a lane or channel to a cap."""


class Injector(Protocol):
    def inject(self, cap: Cap, lane_id: str, causal_rank: int) -> tuple[str, PhaseEvidence]:
        """Place the cap into an executor-bound memory slot."""


class Aligner(Protocol):
    def align(self, cap: Cap, lane_id: str, memory_slot: str) -> tuple[str, PhaseEvidence]:
        """Compute or confirm cluster alignment information."""


class Executor(Protocol):
    def execute(self, distributed: DistributedCap) -> tuple[CapReceipt, PhaseEvidence]:
        """Execute the cap and return a receipt."""


class UsageEventProjector(Protocol):
    def project(self, distributed: DistributedCap, receipt: CapReceipt) -> list[UsageEvent]:
        """Project runtime state into usage/telemetry events."""


class EventSink(Protocol):
    def record(self, result: ExecutionResult) -> None:
        """Capture the finished execution result for later analysis."""
