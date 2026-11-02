from datetime import date

import pytest
import sqlalchemy as sa

from app.data.db import make_engine, ping
from app.data.queries import (
    attack_flows_per_day,
    attack_mix,
    busiest_hours,
    capture_days,
    dataset_files,
    flows_by_category,
    flows_per_hour,
    flows_per_hour_on,
    kpi_totals,
    last_ingestion_run,
    loaded_datasets,
    top_attack_labels,
    top_ports,
)
from tests.fixtures.seed import UNLABELLED


def _insert_runs(url: str, count: int) -> None:
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            for _ in range(count):
                conn.execute(
                    sa.text(
                        "INSERT INTO ingestion_runs (dataset_id, file_key, commit_sha, status) "
                        "VALUES ('d', 'raw/f.csv', 'abc1234', 'loaded')"
                    )
                )
    finally:
        engine.dispose()


@pytest.mark.db
def test_ping_reports_version_and_latency(migrated_db_url):
    engine = make_engine(migrated_db_url)
    try:
        result = ping(engine)
    finally:
        engine.dispose()
    assert result.ok and result.server_version.startswith("16.") and result.latency_ms >= 0


@pytest.mark.db
def test_last_ingestion_run_is_empty_then_latest(
    migrated_db_url, settings_env, monkeypatch, clear_caches
):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    assert last_ingestion_run().empty
    _insert_runs(migrated_db_url, count=2)
    clear_caches()
    assert last_ingestion_run()["run_id"].tolist() == [2]


@pytest.mark.db
def test_loaded_datasets_baseline_first(use_seeded_db):
    datasets = loaded_datasets()
    assert datasets["dataset_id"].tolist() == ["cse-cic-ids2018", "simulated-real-traffic-01"]
    assert datasets["extra_fields"].tolist() == [
        ["bwd_psh_flags", "fwd_pkt_len_max"],
        ["pkt_entropy", "geo_country"],
    ]


@pytest.mark.db
def test_kpi_totals(filters_for):
    row = kpi_totals(filters_for()).iloc[0]
    assert tuple(row) == (7155, 3555, 7, 6, 2, date(2018, 2, 14), date(2018, 2, 21))


@pytest.mark.db
def test_flows_by_category_keeps_benign_and_applies_filters(filters_for):
    def pairs(f):
        return list(flows_by_category(f).itertuples(index=False, name=None))

    assert pairs(filters_for()) == [
        ("Benign", 3600),
        ("DDoS", 2000),
        ("Brute force", 700),
        ("DoS", 600),
        ("Botnet", 200),
        ("Infiltration", 50),
        ("Web attack", 5),
    ]
    assert pairs(filters_for(categories=["DDoS"])) == [("Benign", 3600), ("DDoS", 2000)]
    one_day = filters_for(dates=(date(2018, 2, 21), date(2018, 2, 21)))
    assert pairs(one_day)[:2] == [("DDoS", 2000), ("Benign", 1100)]


@pytest.mark.db
def test_top_attack_labels_and_mix(filters_for):
    labels = top_attack_labels(filters_for())
    assert labels.iloc[0][["label", "flows"]].tolist() == ["DDOS attack-HOIC", 2000]
    assert len(labels) == 7 and labels.iloc[0]["share"] == pytest.approx(2000 / 3555)
    mix = attack_mix(filters_for())
    assert "Benign" not in mix["attack_category"].tolist()
    assert mix["share"].sum() == pytest.approx(1)


@pytest.mark.db
def test_top_ports_skips_the_other_bucket(filters_for):
    assert top_ports(filters_for())["dst_port"].tolist() == [80, 21, 22, 8080, 445, 3389, 53]
    assert top_ports(filters_for())["flows"].iloc[0] == 2597
    assert top_ports(filters_for(categories=["DDoS"])).values.tolist() == [[80, 1990], [53, 10]]
    assert top_ports(filters_for(UNLABELLED), 8, attack_only=False).values.tolist() == [
        [443, 500],
        [80, 300],
        [53, 150],
        [22, 50],
    ]


@pytest.mark.db
def test_flows_per_hour_and_dataset_files(filters_for):
    assert flows_per_hour(filters_for(UNLABELLED)).values.tolist() == [
        [9, 300],
        [10, 500],
        [11, 200],
    ]
    assert dataset_files("cse-cic-ids2018")["run_id"].tolist() == [1, 3]
    assert dataset_files(UNLABELLED)["new_columns"].iloc[0] == ["pkt_entropy", "geo_country"]


@pytest.mark.db
def test_capture_days(filters_for):
    assert capture_days(filters_for()).values.tolist() == [
        [date(2018, 2, 14), 3405, 905],
        [date(2018, 2, 21), 3750, 2650],
    ]
    assert capture_days(filters_for(UNLABELLED)).values.tolist() == [[date(2018, 3, 2), 1000, 0]]


@pytest.mark.db
def test_attack_flows_per_day_leaves_out_benign(filters_for):
    per_day = attack_flows_per_day(filters_for())
    day = per_day[per_day["day"] == date(2018, 2, 21)]
    assert dict(zip(day.attack_category, day.flows, strict=True)) == {
        "DDoS": 2000,
        "DoS": 600,
        "Infiltration": 50,
    }
    assert "Benign" not in per_day["attack_category"].tolist()


@pytest.mark.db
def test_flows_per_hour_on_one_day(filters_for):
    hours = flows_per_hour_on(filters_for(), date(2018, 2, 21))
    at_two = hours[hours["hour"] == 14]
    assert dict(zip(at_two.label, at_two.flows, strict=True)) == {
        "DDOS attack-HOIC": 2000,
        "Benign": 200,
    }
    assert sorted(hours["hour"].unique().tolist()) == [9, 14, 15, 16]


@pytest.mark.db
def test_busiest_hours(filters_for):
    assert busiest_hours(filters_for()).values.tolist() == [
        [date(2018, 2, 21), 14, 2200, "DDoS"],
        [date(2018, 2, 14), 10, 1400, "Benign"],
        [date(2018, 2, 14), 9, 1000, "Benign"],
        [date(2018, 2, 21), 9, 900, "Benign"],
        [date(2018, 2, 14), 11, 800, "Benign"],
    ]
    assert busiest_hours(filters_for(UNLABELLED))["main_category"].isna().all()
