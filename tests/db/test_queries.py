from datetime import date

import pandas as pd
import pytest
import sqlalchemy as sa

from app.data.db import make_engine, ping
from app.data.queries import (
    attack_flows_per_day,
    attack_mix,
    busiest_hours,
    capture_days,
    cleaning_steps,
    column_issues,
    dataset_files,
    datasets_table,
    field_histogram,
    field_stats,
    flows_by_category,
    flows_per_hour,
    flows_per_hour_on,
    kpi_totals,
    last_ingestion_run,
    loaded_datasets,
    main_ports,
    numeric_extras,
    protocol_mix,
    quarantined_files,
    recent_runs,
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


@pytest.mark.db
def test_protocol_mix(filters_for):
    mix = protocol_mix(filters_for()).set_index(["attack_category", "protocol"])["share"]
    assert mix["Benign"].round(3).to_dict() == {"TCP": 0.625, "UDP": 0.347, "ICMP": 0.028}
    assert mix["DDoS"].round(3).to_dict() == {"TCP": 0.995, "UDP": 0.005}
    unlabelled = protocol_mix(filters_for(UNLABELLED))
    assert unlabelled["attack_category"].isna().all()
    assert unlabelled["protocol"].tolist() == ["TCP", "UDP"]


@pytest.mark.db
def test_main_ports(filters_for):
    ports = main_ports(filters_for()).set_index("attack_category")
    assert ports.index.tolist() == [
        "DoS",
        "DDoS",
        "Brute force",
        "Web attack",
        "Botnet",
        "Infiltration",
    ]
    assert ports.loc["Infiltration"].tolist() == [445, pytest.approx(0.6), 3389, pytest.approx(0.3)]
    assert ports.loc["Brute force", "main_port"] == 21
    assert pd.isna(ports.loc["Web attack", "next_port"])
    assert len(main_ports(filters_for(categories=["DDoS"]))) == 1


@pytest.mark.db
def test_pipeline_queries(use_seeded_db):
    table = datasets_table()
    assert table[["dataset_id", "files", "row_count", "status"]].values.tolist() == [
        ["cse-cic-ids2018", 2, 7155, "loaded"],
        ["broken", 1, 0, "quarantined"],
        ["simulated-real-traffic-01", 1, 1000, "loaded"],
    ]
    assert recent_runs()["run_id"].tolist() == [5, 4, 3, 2, 1]
    assert recent_runs(limit=2)["run_id"].tolist() == [5, 4]
    assert quarantined_files()[["run_id", "file_key"]].values.tolist() == [
        [5, "raw/broken/missing-dst-port.csv"]
    ]


@pytest.mark.db
def test_cleaning_steps(use_seeded_db):
    assert cleaning_steps("cse-cic-ids2018").values.tolist() == [
        ["duplicates_removed", 100],
        ["infinite_set_to_null", 20],
        ["missing_kept_as_null", 7],
        ["repeated_headers_dropped", 1],
        ["labels_trimmed", 0],
    ]


@pytest.mark.db
def test_column_issues(use_seeded_db):
    assert column_issues("cse-cic-ids2018").values.tolist() == [
        ["flow_bytes_per_s", 7, 20, "infinite set to null"],
        ["flow_packets_per_s", 0, 20, "infinite set to null"],
        ["bwd_psh_flags", 0, 0, "constant, hidden"],
    ]
    assert column_issues("simulated-real-traffic-01").empty


@pytest.mark.db
def test_field_stats(filters_for):
    from app.data.fields import ATTACK_CATEGORIES

    stats = field_stats(filters_for(), "flow_duration_us", False).set_index("attack_category")
    assert stats.loc["Benign", ["samples", "median", "mean"]].tolist() == [5, 30000, 30000]
    assert stats.loc["DDoS", "median"] == 6000
    assert stats.index.tolist() == list(ATTACK_CATEGORIES)


@pytest.mark.db
def test_field_stats_positive_only(filters_for):  # Review Focus 3
    def median(positive_only):
        stats = field_stats(filters_for(), "bwd_packets", positive_only)
        return stats.set_index("attack_category").loc["Benign", "median"]

    assert (median(False), median(True)) == (1.0, 2.0)


@pytest.mark.db
def test_text_extras_not_offered(filters_for):  # Review Focus 5
    assert numeric_extras(filters_for())["field"].tolist() == ["fwd_pkt_len_max"]
    assert numeric_extras(filters_for(UNLABELLED))["field"].tolist() == ["pkt_entropy"]
    entropy = field_stats(filters_for(UNLABELLED), "pkt_entropy", False)
    assert entropy["median"].tolist() == [3.0] and entropy["attack_category"].isna().all()


@pytest.mark.db
def test_unknown_field_rejected(filters_for):  # Review Focus 5
    for field in ("flow_duration_us; DROP TABLE datasets", "geo_country_x", "label"):
        with pytest.raises(ValueError, match="unknown field"):
            field_stats(filters_for(), field, False)
        with pytest.raises(ValueError, match="unknown field"):
            field_histogram(filters_for(), field, True)


@pytest.mark.db
def test_field_histogram(filters_for):
    bins = field_histogram(filters_for(), "flow_duration_us", True)
    assert bins.groupby("attack_category")["samples"].sum().eq(5).all()
    assert (bins["bin_end"] > bins["bin_start"]).all() and bins["bin_start"].min() > 0


@pytest.mark.db
def test_feature_explorer_reads_the_database_once_per_question(filters_for, monkeypatch):
    """The page asks for the field list and both sets of statistics on every rerun: the field
    list must not depend on the categories, and the two statistics come from one query."""
    from app.data import queries

    every, ddos = filters_for(), filters_for(categories=["DDoS"])
    sql: list[str] = []
    real_read = queries._read

    def counting_read(query, **params):
        sql.append(query)
        return real_read(query, **params)

    monkeypatch.setattr(queries, "_read", counting_read)
    assert numeric_extras(every)["field"].tolist() == ["fwd_pkt_len_max"]
    assert numeric_extras(ddos)["field"].tolist() == ["fwd_pkt_len_max"]
    field_stats(every, "fwd_pkt_len_max", True)
    field_stats(every, "fwd_pkt_len_max", False)
    assert len(sql) == 3  # the extras probe, the column issues, one statistics query
