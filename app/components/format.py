"""How numbers, dates and units read on every page. Dates avoid %-d, which Windows lacks."""

from datetime import date, datetime

# Scales by thousands, largest first, each ending at 1
_COUNT_SCALES = ((1e9, "B"), (1e6, "M"), (1e3, "k"), (1, ""))
_UNIT_SCALES = {
    "µs": ((1e6, "s"), (1e3, "ms"), (1, "µs")),
    "B": ((1e9, "GB"), (1e6, "MB"), (1e3, "kB"), (1, "B")),
    "B/s": ((1e9, "GB/s"), (1e6, "MB/s"), (1e3, "kB/s"), (1, "B/s")),
}


def _scaled(value: float, scales: tuple[tuple[float, str], ...]) -> tuple[str, str]:
    """Three significant digits in the largest scale the value reaches. A value that rounds up
    to 1,000 (999.6) moves to the next scale, so .3g never falls back to 1e+03."""
    for place, (factor, name) in enumerate(scales):
        if abs(value) < factor and factor != 1:
            continue
        text = f"{value / factor:.3g}"
        if abs(float(text)) < 1000:
            return text, name
        if place == 0:  # beyond the largest scale: whole numbers with separators
            return f"{value / factor:,.0f}", name
        bigger, bigger_name = scales[place - 1]
        return f"{value / bigger:.3g}", bigger_name
    raise ValueError(f"no scale for {value}")  # unreachable: every scale list ends at 1


def compact(n: float) -> str:
    """Three significant digits with a k, M or B suffix: 7155 reads 7.16 k."""
    return " ".join(part for part in _scaled(n, _COUNT_SCALES) if part)


def plural(n: int, one: str, many: str | None = None) -> str:
    """A count with its noun: 1 file, 2 files, 6 categories."""
    return f"{n} {one if n == 1 else many or one + 's'}"


def percent(share: float) -> str:
    return f"{share * 100:.1f} %"


def mmss(seconds: float) -> str:
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"


def day_label(d: date) -> str:
    return f"{d.day} {d:%b}"


def date_label(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def span_label(first: date, last: date) -> str:
    if first == last:
        return date_label(first)
    return f"{day_label(first)} – {date_label(last)}"


def stamp_label(ts: datetime) -> str:
    return f"{ts.day} {ts:%b %Y, %H:%M} UTC"


def hour_label(hour: int) -> str:
    return f"{hour:02d}:00"


def with_unit(value: float, unit: str) -> str:
    """A value in the largest unit that keeps it at 1 or more: 30,000 µs reads 30 ms. Units
    without their own scale take a k, M or B prefix: 1,234 pkt reads 1.23 k pkt."""
    if unit in _UNIT_SCALES:
        text, name = _scaled(value, _UNIT_SCALES[unit])
        return f"{text} {name}"
    text, prefix = _scaled(value, _COUNT_SCALES)
    return " ".join(part for part in (text, prefix, unit) if part)


def basename(key: str) -> str:
    return key.rsplit("/", 1)[-1]
