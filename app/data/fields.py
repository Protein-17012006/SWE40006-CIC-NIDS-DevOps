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
ATTACK_ONLY: tuple[str, ...] = ATTACK_CATEGORIES[1:]

# One colour per category on every chart (UI-09), checked for colour-blind separation in report
# section 5.1. Brute force, Web attack and Botnet have under 3:1 contrast on white, so charts that
# use them carry value labels or sit beside a table. .streamlit/config.toml repeats them in order.
CATEGORY_COLORS: dict[str, str] = {
    "Benign": "#8F8D86",
    "DoS": "#2A78D6",
    "DDoS": "#EB6834",
    "Brute force": "#1BAF7A",
    "Web attack": "#EDA100",
    "Botnet": "#E87BA4",
    "Infiltration": "#008300",
}

# The cleaning steps ingestion counts (pipeline.clean.STEPS), in the order the Data quality page
# lists them; repeated here so the dashboard does not import pandera at start-up
QUALITY_STEPS: tuple[str, ...] = (
    "duplicates_removed",
    "infinite_set_to_null",
    "missing_kept_as_null",
    "repeated_headers_dropped",
    "labels_trimmed",
)

# The canonical numeric fields the Feature explorer compares: name to (label, unit)
NUMERIC_FIELDS: dict[str, tuple[str, str]] = {
    "flow_duration_us": ("Flow duration", "µs"),
    "fwd_packets": ("Forward packets", "pkt"),
    "bwd_packets": ("Backward packets", "pkt"),
    "fwd_bytes": ("Forward bytes", "B"),
    "bwd_bytes": ("Backward bytes", "B"),
    "flow_bytes_per_s": ("Bytes per second", "B/s"),
    "flow_packets_per_s": ("Packets per second", "pkt/s"),
}
