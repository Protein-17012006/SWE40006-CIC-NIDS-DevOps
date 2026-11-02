from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PIPELINE_PAGE = str(Path(__file__).resolve().parents[2] / "app" / "views" / "pipeline.py")


def test_tiles_with_unreachable_database(settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = AppTest.from_file(PIPELINE_PAGE, default_timeout=30).run()
    tiles = {m.label: m.value for m in at.metric}
    assert not at.exception
    assert tiles == {
        "Environment": "test",
        "App version": "abc1234",
        "Database": "Unreachable",
        "Last ingestion": "—",
    }


@pytest.mark.db
def test_tiles_with_migrated_database(settings_env, migrated_db_url, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    at = AppTest.from_file(PIPELINE_PAGE, default_timeout=30).run()
    tiles = {m.label: m.value for m in at.metric}
    assert tiles["Database"] == "Connected" and tiles["Last ingestion"] == "—"


DRAFT = "quarantine/broken/missing-dst-port/draft-contract.yaml"
LOADS_ON_DEPLOY = (
    "Once a contract for this file is merged and deployed, the deployment loads the file."
)


@pytest.mark.db
def test_pipeline_tables_and_quarantine_without_bucket(run_app):
    at = run_app("views/pipeline.py")
    assert not at.exception
    datasets, runs = (d.value for d in at.dataframe)
    assert datasets["Status"].tolist() == ["✅ Loaded", "⚠️ Quarantined", "✅ Loaded"]
    assert datasets["Dataset"].tolist()[0] == "cse-cic-ids2018 (2 files)"
    assert datasets["Contract"].tolist()[:2] == ["cse-cic-ids2018 v1", "no match"]
    assert runs["Run"].tolist() == ["#5", "#4", "#3", "#2", "#1"]
    assert runs["Status"].tolist()[3] == "❌ Failed"
    assert runs["Duration"].str.fullmatch(r"\d+:\d{2}").all()
    assert "missing-dst-port.csv" in at.warning[0].value and "run #5" in at.warning[0].value
    assert "View report" not in [b.label for b in at.button]
    assert LOADS_ON_DEPLOY in [c.value for c in at.caption]


@pytest.mark.db
def test_pipeline_quarantine_with_bucket(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    bucket.put_text(DRAFT, "name: broken\n", "application/yaml")
    at = run_app("views/pipeline.py")
    assert not at.exception
    assert [b.label for b in at.button].count("View report") == 1
    assert at.download_button[-1].label == "Download draft contract"


@pytest.mark.db
def test_pipeline_quarantine_draft_missing(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    at = run_app("views/pipeline.py")
    assert "The draft contract could not be read." in [c.value for c in at.caption]


@pytest.mark.db
def test_quarantine_without_a_draft_offers_none(run_app, seeded_db_url, bucket, monkeypatch):
    """A file quarantined for too many rejected rows has no draft contract to read."""
    import sqlalchemy as sa

    engine = sa.create_engine(seeded_db_url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ingestion_runs (dataset_id, file_key, commit_sha, status, message) "
                "VALUES ('noisy', 'raw/noisy.csv', 'seed000', 'quarantined', "
                "'31 % of rows were rejected.')"
            )
        )
    engine.dispose()
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    at = run_app("views/pipeline.py")
    assert len(at.warning) == 2
    assert [c.value for c in at.caption].count("The draft contract could not be read.") == 1
