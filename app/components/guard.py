"""Which fields a chart needs that the selected dataset lacks (UI-08)."""

from collections.abc import Sequence

from app.components.filters import Filters


def missing(f: Filters, needs: Sequence[str]) -> list[str]:
    """The needed fields the dataset lacks, in the order they were asked for."""
    present = set(f.fields) | set(f.extra_fields)
    lacking = []
    for field in needs:
        if field == "label":
            found = f.has_label
        elif field == "timestamp":
            found = "timestamp" in f.fields and f.date_from is not None
        else:
            found = field in present
        if not found:
            lacking.append(field)
    return lacking
