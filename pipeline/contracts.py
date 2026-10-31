"""Data contracts: one YAML file per source, mapping its columns onto the canonical fields."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.data.fields import ATTACK_CATEGORIES, CANONICAL_FIELDS, FIELD_NAMES, REQUIRED_FIELDS

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
TODO = "TODO"
_NAME = re.compile(r"^[a-z0-9-]+$")
_FIELD_ORDER = [f.name for f in CANONICAL_FIELDS]


class ContractError(ValueError):
    """A contract file that cannot be loaded."""


def normalise(column: str) -> str:
    """Trim, lower-case, and turn every run of other characters into one underscore."""
    text = column.replace("﻿", "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def normalise_header(columns: Sequence[str]) -> list[str]:
    """Normalise a header; a name seen before gets _2, _3 and so on."""
    seen: dict[str, int] = {}
    result = []
    for column in columns:
        name = normalise(column)
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


class FieldSource(BaseModel):
    column: str
    scale: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def _from_name(cls, value: object) -> object:
        return {"column": value} if isinstance(value, str) else value


class Contract(BaseModel):
    name: str
    version: int = Field(ge=1)
    timestamp_format: str | None = None
    fields: dict[str, FieldSource]
    known_extras: list[str] = []
    label_map: dict[str, str] = {}

    @field_validator("name")
    @classmethod
    def _check_name(cls, name: str) -> str:
        if not _NAME.match(name):
            raise ValueError(f"name must use a-z, 0-9 and '-' only; got {name!r}")
        return name

    @field_validator("fields")
    @classmethod
    def _check_fields(cls, fields: dict[str, FieldSource]) -> dict[str, FieldSource]:
        unknown = sorted(set(fields) - FIELD_NAMES)
        if unknown:
            raise ValueError(f"unknown canonical fields: {', '.join(unknown)}")
        missing = [f for f in _FIELD_ORDER if f in REQUIRED_FIELDS and f not in fields]
        if missing:
            raise ValueError(f"required fields not mapped: {', '.join(missing)}")
        todo = [f for f, source in fields.items() if source.column.strip() == TODO]
        if todo:
            raise ValueError(f"fields still marked TODO: {', '.join(todo)}")
        return fields

    @field_validator("label_map")
    @classmethod
    def _check_label_map(cls, label_map: dict[str, str]) -> dict[str, str]:
        todo = [label for label, category in label_map.items() if category == TODO]
        if todo:
            raise ValueError(f"labels still marked TODO: {', '.join(todo)}")
        unknown = sorted(set(label_map.values()) - set(ATTACK_CATEGORIES))
        if unknown:
            raise ValueError(f"unknown attack categories: {', '.join(unknown)}")
        return label_map

    @model_validator(mode="after")
    def _check_pairs(self) -> "Contract":
        if ("timestamp" in self.fields) != (self.timestamp_format is not None):
            raise ValueError("timestamp_format is needed exactly when timestamp is mapped")
        if ("label" in self.fields) != bool(self.label_map):
            raise ValueError("label_map is needed exactly when label is mapped")
        return self

    @property
    def has_label(self) -> bool:
        return "label" in self.fields


def load_contracts(directory: Path = CONTRACTS_DIR) -> list[Contract]:
    contracts = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            contract = Contract.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as exc:
            raise ContractError(f"{path.name}: {exc}") from exc
        if contract.name != path.stem:
            raise ContractError(f"{path.name}: name {contract.name!r} must equal {path.stem!r}")
        contracts.append(contract)
    return sorted(contracts, key=lambda c: c.name)


@dataclass(frozen=True)
class Match:
    contract: Contract
    mapping: dict[str, str]
    extras: list[str]
    new_columns: list[str]


def _mapped(header: Sequence[str], contract: Contract) -> dict[str, str]:
    present = set(normalise_header(header))
    mapping = {}
    for field in _FIELD_ORDER:
        source = contract.fields.get(field)
        if source is not None and normalise(source.column) in present:
            mapping[field] = normalise(source.column)
    return mapping


def missing_fields(header: Sequence[str], contract: Contract) -> list[str]:
    mapping = _mapped(header, contract)
    return [f for f in _FIELD_ORDER if f in REQUIRED_FIELDS and f not in mapping]


def match_contract(header: Sequence[str], contracts: Sequence[Contract]) -> Match | None:
    """The contract whose required fields are all present; most matched columns wins."""
    columns = normalise_header(header)
    best: tuple[int, Match] | None = None
    for contract in sorted(contracts, key=lambda c: c.name):
        if missing_fields(header, contract):
            continue
        mapping = _mapped(header, contract)
        known = {normalise(c) for c in contract.known_extras}
        extras = [c for c in columns if c not in mapping.values()]
        score = len(mapping) + sum(1 for c in extras if c in known)
        if best is None or score > best[0]:
            new = [c for c in extras if c not in known]
            best = (score, Match(contract, mapping, extras, new))
    return best[1] if best else None


def closest_contract(header: Sequence[str], contracts: Sequence[Contract]) -> Contract | None:
    """The contract with the fewest missing required fields; ties go to the first name."""
    ranked = sorted(contracts, key=lambda c: (len(missing_fields(header, c)), c.name))
    return ranked[0] if ranked else None
