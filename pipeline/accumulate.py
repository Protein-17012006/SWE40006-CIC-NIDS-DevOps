"""What one file adds to the database, accumulated chunk by chunk in bounded memory (ING-05).

Only running counts, the per-group sample and one set of row hashes stay in memory, so a
4 GB day file needs no more than a chunk at a time.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.data.fields import FIELD_NAMES
from pipeline.clean import STEPS, CleanChunk

SAMPLE_COLUMNS = (
    "ts",
    "label",
    "attack_category",
    "dst_port",
    "protocol",
    "flow_duration_us",
    "fwd_packets",
    "bwd_packets",
    "fwd_bytes",
    "bwd_bytes",
    "flow_bytes_per_s",
    "flow_packets_per_s",
    "src_ip",
    "dst_ip",
)
_NOT_EXTRA = FIELD_NAMES | {"attack_category"}
_KEY = "_sample_key"


class Deduplicator:
    """Drops rows already seen in this file, by 64-bit hash of every value."""

    def __init__(self) -> None:
        self._seen: set[int] = set()

    def drop(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        hashes = pd.util.hash_pandas_object(frame, index=False).to_numpy()
        keep = np.ones(len(frame), dtype=bool)
        for i, value in enumerate(hashes.tolist()):
            if value in self._seen:
                keep[i] = False
            else:
                self._seen.add(value)
        return frame[keep].reset_index(drop=True), int((~keep).sum())


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame:
        return frame[name]
    return pd.Series([None] * len(frame), index=frame.index, dtype="object")


def _json_value(value: object) -> object:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


class Aggregates:
    def __init__(self, sample_per_group: int = 2000, top_ports: int = 50, seed: int = 0) -> None:
        self.sample_per_group = sample_per_group
        self.top_ports = top_ports
        self._rng = np.random.default_rng(seed)
        self.rows = 0
        self.first_ts: datetime | None = None
        self.last_ts: datetime | None = None
        self._hourly: Counter[tuple] = Counter()
        self._ports: Counter[tuple] = Counter()
        self._sample: pd.DataFrame | None = None

    def add(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        self.rows += len(frame)
        ts = _column(frame, "timestamp")
        if "timestamp" in frame and ts.notna().any():
            low, high = ts.min(), ts.max()
            self.first_ts = low if self.first_ts is None else min(self.first_ts, low)
            self.last_ts = high if self.last_ts is None else max(self.last_ts, high)
        hour = pd.to_datetime(ts).dt.floor("h") if "timestamp" in frame else ts
        day = pd.to_datetime(ts).dt.normalize() if "timestamp" in frame else ts
        label, category = _column(frame, "label"), _column(frame, "attack_category")

        keys = pd.DataFrame({"hour": hour, "label": label, "attack_category": category})
        for key, n in keys.value_counts(dropna=False).items():
            self._hourly[key] += int(n)
        keys = pd.DataFrame(
            {
                "day": day,
                "attack_category": category,
                "protocol": frame["protocol"],
                "dst_port": frame["dst_port"],
            }
        )
        for key, n in keys.value_counts(dropna=False).items():
            self._ports[key] += int(n)
        self._add_sample(frame.assign(**{_KEY: self._rng.random(len(frame)), "_day": day}))

    def _add_sample(self, frame: pd.DataFrame) -> None:
        if "attack_category" not in frame:
            frame = frame.assign(attack_category=pd.NA)
        combined = frame if self._sample is None else pd.concat([self._sample, frame])
        combined = combined.sort_values(_KEY, kind="stable")
        groups = combined.groupby(["attack_category", "_day"], dropna=False, sort=False)
        self._sample = groups.head(self.sample_per_group).reset_index(drop=True)

    def hourly(self) -> pd.DataFrame:
        rows = [(*key, n) for key, n in self._hourly.items()]
        frame = pd.DataFrame(rows, columns=["hour", "label", "attack_category", "flows"])
        return self._nulls(frame.sort_values(["hour", "label"], na_position="first"))

    def ports(self) -> pd.DataFrame:
        rows = [(*key, n) for key, n in self._ports.items()]
        frame = pd.DataFrame(
            rows, columns=["day", "attack_category", "protocol", "dst_port", "flows"]
        )
        group = ["day", "attack_category", "protocol"]
        frame = frame.sort_values(["flows", "dst_port"], ascending=[False, True])
        rank = frame.groupby(group, dropna=False, sort=False).cumcount()
        top, rest = frame[rank < self.top_ports], frame[rank >= self.top_ports]
        other = rest.groupby(group, dropna=False, as_index=False)["flows"].sum()
        other["dst_port"] = -1
        result = pd.concat([top, other[frame.columns]], ignore_index=True)
        result["day"] = [None if pd.isna(d) else d.date() for d in result["day"]]
        result["protocol"] = result["protocol"].astype(int)
        result["dst_port"] = result["dst_port"].astype(int)
        return self._nulls(result.reset_index(drop=True))

    def sample(self) -> pd.DataFrame:
        if self._sample is None:
            return pd.DataFrame(columns=[*SAMPLE_COLUMNS, "extras"])
        frame = self._sample
        extra_names = [c for c in frame.columns if c not in _NOT_EXTRA and not c.startswith("_")]
        out = pd.DataFrame({"ts": _column(frame, "timestamp")})
        for name in SAMPLE_COLUMNS[1:]:
            out[name] = _column(frame, name)
        out["extras"] = [
            {name: _json_value(value) for name, value in zip(extra_names, values, strict=True)}
            for values in frame[extra_names].itertuples(index=False, name=None)
        ]
        return out.reset_index(drop=True)

    @staticmethod
    def _nulls(frame: pd.DataFrame) -> pd.DataFrame:
        """Missing labels, categories and hours as None or NaT, never NaN strings."""
        for name in ("label", "attack_category"):
            if name in frame:
                frame[name] = [None if pd.isna(v) else v for v in frame[name]]
        return frame.reset_index(drop=True)


@dataclass(frozen=True)
class ColumnIssue:
    column_name: str
    nulls: int
    infinite: int
    action: str


class Quality:
    def __init__(self) -> None:
        self._steps: Counter[str] = Counter(dict.fromkeys(STEPS, 0))
        self._nulls: Counter[str] = Counter()
        self._infinite: Counter[str] = Counter()
        self._low: dict[str, float] = {}
        self._high: dict[str, float] = {}
        self._numeric: set[str] = set()
        self._has_null: set[str] = set()

    def add(self, chunk: CleanChunk, kept: pd.DataFrame, duplicates: int) -> None:
        for step in STEPS:
            if step != "duplicates_removed":
                self._steps[step] += chunk.steps.get(step, 0)
        self._steps["duplicates_removed"] += duplicates
        self._nulls.update(chunk.nulls)
        self._infinite.update(chunk.infinite)
        for name in kept.columns:
            if str(kept[name].dtype) not in ("Int64", "Float64"):
                continue
            self._numeric.add(name)
            values = kept[name].dropna()
            if len(values) < len(kept):
                self._has_null.add(name)
            if values.empty:
                continue
            low, high = float(values.min()), float(values.max())
            self._low[name] = min(self._low.get(name, low), low)
            self._high[name] = max(self._high.get(name, high), high)

    def steps(self) -> dict[str, int]:
        return {step: int(self._steps[step]) for step in STEPS}

    def columns(self) -> list[ColumnIssue]:
        issues = []
        for name in sorted(self._numeric | set(self._nulls) | set(self._infinite)):
            # One value in every row: all null, or one number and no null
            all_null = name in self._numeric and name not in self._low
            one_value = self._low.get(name, 0.0) == self._high.get(name, 1.0)
            constant = all_null or (one_value and name not in self._has_null)
            if constant:
                action = "constant, hidden"
            elif self._infinite[name]:
                action = "infinite set to null"
            elif self._nulls[name]:
                action = "kept as null"
            else:
                continue
            issues.append(ColumnIssue(name, self._nulls[name], self._infinite[name], action))
        return issues
