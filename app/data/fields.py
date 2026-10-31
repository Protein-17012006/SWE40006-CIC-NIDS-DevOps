"""The canonical fields every page and the ingestion job use (report section 4.1)."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Field:
    name: str
    kind: Literal["datetime", "integer", "float", "text"]
    required: bool


CANONICAL_FIELDS: tuple[Field, ...] = (
    Field("timestamp", "datetime", False),
    Field("dst_port", "integer", True),
    Field("protocol", "integer", True),
    Field("flow_duration_us", "float", True),
    Field("fwd_packets", "integer", True),
    Field("bwd_packets", "integer", True),
    Field("fwd_bytes", "float", True),
    Field("bwd_bytes", "float", True),
    Field("flow_bytes_per_s", "float", False),
    Field("flow_packets_per_s", "float", False),
    Field("src_ip", "text", False),
    Field("dst_ip", "text", False),
    Field("label", "text", False),
)
FIELD_NAMES: frozenset[str] = frozenset(f.name for f in CANONICAL_FIELDS)
REQUIRED_FIELDS: frozenset[str] = frozenset(f.name for f in CANONICAL_FIELDS if f.required)

ATTACK_CATEGORIES: tuple[str, ...] = (
    "Benign",
    "DoS",
    "DDoS",
    "Brute force",
    "Web attack",
    "Botnet",
    "Infiltration",
)
