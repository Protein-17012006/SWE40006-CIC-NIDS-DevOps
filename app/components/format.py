"""How numbers, dates and units read on every page. Dates avoid %-d, which Windows lacks."""

from datetime import date, datetime

_COUNT_SCALES = ((1e9, " B"), (1e6, " M"), (1e3, " k"))
# Each unit scales by thousands to the next, largest first
_UNIT_SCALES = {
    "µs": ((1e6, "s"), (1e3, "ms"), (1, "µs")),
    "B": ((1e9, "GB"), (1e6, "MB"), (1e3, "kB"), (1, "B")),
    "B/s": ((1e9, "GB/s"), (1e6, "MB/s"), (1e3, "kB/s"), (1, "B/s")),
}


def compact(n: float) -> str:
    """Three significant digits with a k, M or B suffix: 7155 reads 7.16 k."""
    for scale, suffix in _COUNT_SCALES:
        if abs(n) >= scale:
            return f"{n / scale:.3g}{suffix}"
    return f"{n:.3g}"


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
    """A value in the largest unit that keeps it at 1 or more: 30,000 µs reads 30 ms."""
    for scale, name in _UNIT_SCALES.get(unit, ()):
        if abs(value) >= scale or scale == 1:
            return f"{value / scale:.3g} {name}"
    return f"{value:.3g} {unit}".rstrip()


def basename(key: str) -> str:
    return key.rsplit("/", 1)[-1]
