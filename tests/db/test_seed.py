import pytest
import sqlalchemy as sa


@pytest.mark.db
def test_seed_fills_every_table(seeded_db_url):
    engine = sa.create_engine(seeded_db_url)
    with engine.connect() as conn:

        def rows(sql: str) -> list[tuple]:
            return [tuple(row) for row in conn.execute(sa.text(sql)).all()]

        assert rows("SELECT dataset_id, status, has_label, row_count FROM datasets ORDER BY 1") == [
            ("broken", "quarantined", False, 0),
            ("cse-cic-ids2018", "loaded", True, 7155),
            ("simulated-real-traffic-01", "loaded", False, 1000),
        ]
        assert rows("SELECT run_id, status FROM ingestion_runs ORDER BY 1") == [
            (1, "loaded"),
            (2, "failed"),
            (3, "loaded"),
            (4, "loaded"),
            (5, "quarantined"),
        ]
        assert rows("SELECT SUM(flows) FROM agg_ports WHERE dataset_id = 'cse-cic-ids2018'") == [
            (7155,)
        ]
        assert rows("SELECT COUNT(*) FROM flow_sample") == [(40,)]
        assert rows("SELECT SUM(rows_affected) FROM quality_steps") == [(128,)]
    engine.dispose()
