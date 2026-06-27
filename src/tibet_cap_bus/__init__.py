"""tibet-cap-bus — identity-bound causal command substrate.

Public API:
- Runtime: CapBusRuntime + helpers
- Event contract: validate_gateway_event_record + load_event_records
- Verdict contract: validate_verdict_record + check_mode_coherence (airlock_runtime_verdict.v1 immune-switch)
- SSM magic-bytes: 1-byte routing header (Priority/Intent/Hardware)
"""

from .event_contract import (
    load_event_records,
    validate_gateway_event_record,
    validate_gateway_event_records,
)
from .verdict_contract import (
    VERDICT_KIND,
    check_mode_coherence,
    load_verdict_records,
    validate_verdict_record,
    validate_verdict_records,
)
from .verdict_transitions import (
    POSTURE_TRANSITION_INTENT,
    diff_switches,
    make_posture_transition_event,
)
from .models import Cap, CapReceipt, ExecutionResult, UsageEvent
from .runtime import (
    build_export_all,
    CapBusRuntime,
    build_cbom_export,
    build_default_runtime,
    build_demo_chain_cap,
    build_demo_triage_caps,
    build_gateway_event_export,
    build_governance_export,
)
from .ssm_magic import (
    Priority,
    Intent,
    Hardware,
    encode as encode_magic_bytes,
    decode as decode_magic_bytes,
    describe as describe_magic_bytes,
    magic_bytes_from_event,
)
from .gpu_mailbox import (
    GPURingBufferInjector,
    ContentAddressedVRAM,
    PossessionReceipt,
    TTLEnforcer,
    JISPrefetcher,
    resolve_waint_block_offset,
)

__all__ = [
    "Cap",
    "CapReceipt",
    "ExecutionResult",
    "UsageEvent",
    "load_event_records",
    "validate_gateway_event_record",
    "validate_gateway_event_records",
    "CapBusRuntime",
    "build_export_all",
    "build_cbom_export",
    "build_default_runtime",
    "build_demo_chain_cap",
    "build_demo_triage_caps",
    "build_gateway_event_export",
    "build_governance_export",
    "Priority",
    "Intent",
    "Hardware",
    "encode_magic_bytes",
    "decode_magic_bytes",
    "describe_magic_bytes",
    "magic_bytes_from_event",
    # GPU mailbox (lifted from gravity.aint reference, single-source on tibet_mux.verify)
    "GPURingBufferInjector",
    "ContentAddressedVRAM",
    "PossessionReceipt",
    "TTLEnforcer",
    "JISPrefetcher",
    "resolve_waint_block_offset",
]

__version__ = "0.1.5"
