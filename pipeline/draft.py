"""What a quarantined file gets: a readable report and a draft contract (ING-03, ING-08)."""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd
import yaml

from app.data.fields import CANONICAL_FIELDS, REQUIRED_FIELDS
from pipeline.contracts import (
    TODO,
    Contract,
    closest_contract,
    missing_fields,
    normalise,
    normalise_header,
)
from pipeline.storage import RawFile

# CICFlowMeter and CIC-IDS2017 spellings of the canonical fields
SYNONYMS: dict[str, tuple[str, ...]] = {
    "timestamp": ("Timestamp",),
    "dst_port": ("Destination Port", "Dst Port", "DstPort"),
    "protocol": ("Protocol", "Proto"),
    "flow_duration_us": ("Flow Duration",),
    "fwd_packets": ("Total Fwd Packets", "Tot Fwd Pkts"),
    "bwd_packets": ("Total Backward Packets", "Tot Bwd Pkts"),
    "fwd_bytes": ("Total Length of Fwd Packets", "TotLen Fwd Pkts"),
    "bwd_bytes": ("Total Length of Bwd Packets", "TotLen Bwd Pkts"),
    "flow_bytes_per_s": ("Flow Bytes/s", "Flow Byts/s"),
    "flow_packets_per_s": ("Flow Packets/s", "Flow Pkts/s"),
    "src_ip": ("Source IP", "Src IP"),
    "dst_ip": ("Destination IP", "Dst IP"),
    "label": ("Label",),
}
TIMESTAMP_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p",
)
SIMILARITY = 0.8
_ORDER = [f.name for f in CANONICAL_FIELDS]
_SAMPLE_VALUES = 200


def _own_names(field: str, contracts: Sequence[Contract]) -> set[str]:
    names = {field}
    names.update(normalise(c.fields[field].column) for c in contracts if field in c.fields)
    return names


def propose_mapping(header: Sequence[str], contracts: Sequence[Contract]) -> dict[str, str | None]:
    """Canonical field to the header's own spelling: exact names, then synonyms, then similarity."""
    columns = list(header)
    normal = normalise_header(columns)
    own = {f: _own_names(f, contracts) for f in _ORDER}
    synonyms = {f: {normalise(s) for s in SYNONYMS.get(f, ())} for f in _ORDER}
    mapping: dict[str, str | None] = dict.fromkeys(_ORDER)
    used: set[int] = set()

    for pool in (own, synonyms):
        for field in _ORDER:
            if mapping[field] is not None:
                continue
            for i, name in enumerate(normal):
                if i not in used and name in pool[field]:
                    mapping[field] = columns[i]
                    used.add(i)
                    break

    scored = []
    for field in (f for f in _ORDER if mapping[f] is None):
        candidates = own[field] | synonyms[field]
        for i, name in enumerate(normal):
            if i in used:
                continue
            ratio = max(SequenceMatcher(None, name, c).ratio() for c in candidates)
            if ratio >= SIMILARITY:
                scored.append((-ratio, _ORDER.index(field), i, field))
    for _, _, i, field in sorted(scored):
        if mapping[field] is None and i not in used:
            mapping[field] = columns[i]
            used.add(i)
    return mapping


def guess_timestamp_format(values: Sequence[str]) -> str | None:
    """The first known format that parses every value."""
    if not values:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            for value in values:
                datetime.strptime(value, fmt)  # noqa: DTZ007 - the files carry naive local times
        except ValueError:
            continue
        return fmt
    return None


def _values(header: Sequence[str], column: str, chunk: pd.DataFrame) -> list[str]:
    name = normalise_header(header)[list(header).index(column)]
    if name not in chunk:
        return []
    values = chunk[name].astype(str).str.strip()
    values = values[(values != "") & (values.map(normalise) != name)]
    return values.drop_duplicates().head(_SAMPLE_VALUES).tolist()


def draft_contract(
    dataset_id: str, header: Sequence[str], contracts: Sequence[Contract], first_chunk: pd.DataFrame
) -> str:
    mapping = propose_mapping(header, contracts)
    name = re.sub(r"-\d+$", "", dataset_id) or dataset_id
    fields = {
        f: (column.strip() if column else TODO)
        for f, column in mapping.items()
        if column or f in REQUIRED_FIELDS
    }
    data: dict[str, object] = {"name": name, "version": 1}
    if mapping["timestamp"]:
        stamps = _values(header, mapping["timestamp"], first_chunk)
        data["timestamp_format"] = guess_timestamp_format(stamps) or TODO
    data["fields"] = fields
    mapped = {c for c in mapping.values() if c}
    data["known_extras"] = [c.strip() for c in header if c not in mapped]
    if mapping["label"]:
        known = {label: cat for c in contracts for label, cat in c.label_map.items()}
        labels = _values(header, mapping["label"], first_chunk)
        data["label_map"] = {label: known.get(label, TODO) for label in labels} or {TODO: TODO}

    absent = [f for f, column in mapping.items() if not column and f not in REQUIRED_FIELDS]
    comment = (
        f"# Draft contract for {dataset_id}, proposed by the ingestion job from its header.\n"
        f"# Check every mapping and replace each TODO, then save this file as\n"
        f"# contracts/{name}.yaml and open a pull request with a sample of the file.\n"
    )
    if absent:
        comment += f"# Not found in the file: {', '.join(absent)}.\n"
    return comment + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def quarantine_report(
    raw: RawFile,
    run_id: int,
    reason: str,
    header: Sequence[str],
    contracts: Sequence[Contract],
    unknown_labels: Mapping[str, int] | None = None,
) -> str:
    lines = [
        f"# Quarantined: {raw.key}",
        "",
        f"Ingestion run #{run_id} · dataset `{raw.dataset_id}`",
        "",
        f"**Reason.** {reason}",
    ]
    closest = closest_contract(header, contracts)
    missing = missing_fields(header, closest) if closest else []
    if closest and missing:
        tag = f"{closest.name} v{closest.version}"
        lines += ["", "## Missing required fields", ""]
        lines += [f'- {f}: expected "{closest.fields[f].column}" ({tag})' for f in missing]

    known = set()
    for c in contracts:
        known.update(normalise(source.column) for source in c.fields.values())
        known.update(normalise(extra) for extra in c.known_extras)
    unknown = [c.strip() for c, n in zip(header, normalise_header(header), strict=True)]
    unknown = [c for c in unknown if normalise(c) not in known]
    if unknown:
        lines += ["", "## Columns no contract knows", ""]
        lines += [f"- `{c}`" for c in unknown]

    if unknown_labels:
        lines += ["", "## Unknown labels", "", "| Label | Rows |", "| --- | ---: |"]
        ranked = sorted(unknown_labels.items(), key=lambda item: (-item[1], item[0]))
        lines += [f"| {label} | {count:,} |" for label, count in ranked]

    lines += [
        "",
        "## Next steps",
        "",
        "1. Download `draft-contract.yaml` from this folder and check every mapping.",
        "2. Replace each TODO, save it as `contracts/<name>.yaml`, and add a sample of the file",
        "   under `tests/contracts/<name>/`.",
        "3. Open a pull request. After the deployment, reconcile re-ingests this file without",
        "   a new upload.",
        "",
    ]
    return "\n".join(lines)
