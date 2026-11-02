from datetime import UTC, date, datetime

import pytest

from app.components.format import (
    basename,
    compact,
    date_label,
    day_label,
    hour_label,
    mmss,
    percent,
    span_label,
    stamp_label,
    with_unit,
)
from app.data.ports import port_label, protocol_name


@pytest.mark.parametrize(
    "n, text",
    [
        (0, "0"),
        (928, "928"),
        (1400, "1.4 k"),
        (2000, "2 k"),
        (7155, "7.16 k"),
        (654_321, "654 k"),
        (1_260_000, "1.26 M"),
        (13_480_000, "13.5 M"),
    ],
)
def test_compact(n, text):
    assert compact(n) == text


def test_percent_and_mmss():
    assert percent(0.49685) == "49.7 %" and percent(1) == "100.0 %"
    assert [mmss(s) for s in (41, 130, 3600)] == ["0:41", "2:10", "60:00"]


def test_dates():
    assert day_label(date(2018, 2, 14)) == "14 Feb" and date_label(date(2018, 3, 2)) == "2 Mar 2018"
    assert span_label(date(2018, 2, 14), date(2018, 2, 21)) == "14 Feb – 21 Feb 2018"
    assert span_label(date(2018, 3, 2), date(2018, 3, 2)) == "2 Mar 2018"
    assert stamp_label(datetime(2026, 10, 28, 9, 14, tzinfo=UTC)) == "28 Oct 2026, 09:14 UTC"
    assert hour_label(9) == "09:00"
    assert basename("raw/broken/missing-dst-port.csv") == "missing-dst-port.csv"


@pytest.mark.parametrize(
    "value, unit, text",
    [
        (10, "µs", "10 µs"),
        (30_000, "µs", "30 ms"),
        (4_200_000, "µs", "4.2 s"),
        (1500, "B", "1.5 kB"),
        (12, "pkt", "12 pkt"),
        (2.5, "", "2.5"),
    ],
)
def test_with_unit(value, unit, text):
    assert with_unit(value, unit) == text


def test_ports_and_protocols():
    assert [port_label(p) for p in (80, 0, 5000, -1)] == [
        "80 · HTTP",
        "0 · no port",
        "5000",
        "other",
    ]
    assert [protocol_name(n) for n in (6, 17, 1, 47)] == ["TCP", "UDP", "ICMP", "Other"]
