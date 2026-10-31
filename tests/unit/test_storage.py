import pytest

from pipeline.storage import parse_raw_key


def test_parse_raw_key_dataset_folder():
    f = parse_raw_key("raw/cse-cic-ids2018/Wednesday-14-02-2018.csv")
    assert (f.key, f.dataset_id, f.name) == (
        "raw/cse-cic-ids2018/Wednesday-14-02-2018.csv",
        "cse-cic-ids2018",
        "Wednesday-14-02-2018",
    )
    assert f.processed_prefix == "processed/cse-cic-ids2018/Wednesday-14-02-2018/"
    assert f.report_key == "quarantine/cse-cic-ids2018/Wednesday-14-02-2018/report.md"
    assert f.draft_key == "quarantine/cse-cic-ids2018/Wednesday-14-02-2018/draft-contract.yaml"


def test_parse_raw_key_file_directly_in_raw_and_odd_names():
    direct = parse_raw_key("raw/simulated-real-traffic-01.csv")
    assert (direct.dataset_id, direct.name) == (
        "simulated-real-traffic-01",
        "simulated-real-traffic-01",
    )
    f = parse_raw_key("raw/My Capture/day 1.CSV")
    assert (f.dataset_id, f.name) == ("my-capture", "day 1")
    nested = parse_raw_key("raw/site_A/2026/11/day.csv")
    assert (nested.dataset_id, nested.name) == ("site-a", "2026/11/day")


@pytest.mark.parametrize(
    "key",
    [
        "raw/readme.txt",
        "processed/x.csv",
        "raw/folder/",
        "raw/",
        "raw/@@.csv",
        "raw.csv",
        "raw/a/.csv",
    ],
)
def test_parse_raw_key_ignores_non_csv_and_outside_raw(key):
    assert parse_raw_key(key) is None


def test_resolve_key_decodes_event_keys(bucket):
    bucket.put_text("raw/my capture.csv", "a\n", "text/csv")
    assert bucket.resolve_key("raw/my capture.csv") == "raw/my capture.csv"
    assert bucket.resolve_key("raw/my+capture.csv") == "raw/my capture.csv"
    assert bucket.resolve_key("raw/my%20capture.csv") == "raw/my capture.csv"
    with pytest.raises(FileNotFoundError, match="raw/other.csv"):
        bucket.resolve_key("raw/other.csv")


def test_a_real_plus_sign_in_a_key_still_resolves(bucket):
    bucket.put_text("raw/a+b.csv", "a\n", "text/csv")
    assert bucket.resolve_key("raw/a+b.csv") == "raw/a+b.csv"


def test_text_and_files_round_trip(bucket, tmp_path):
    bucket.put_text("quarantine/d/f/report.md", "# Report\n", "text/markdown")
    assert bucket.read_text("quarantine/d/f/report.md") == "# Report\n"
    src = tmp_path / "part-0000.parquet"
    src.write_bytes(b"PAR1")
    bucket.upload(src, "processed/d/f/part-0000.parquet")
    bucket.download("processed/d/f/part-0000.parquet", tmp_path / "copy")
    assert (tmp_path / "copy").read_bytes() == b"PAR1"
    assert bucket.exists("processed/d/f/part-0000.parquet")
    assert not bucket.exists("processed/d/f/part-0001.parquet")


def test_delete_prefix_removes_only_that_prefix(bucket):
    for k in (
        "processed/d/a/part-0000.parquet",
        "processed/d/a/part-0001.parquet",
        "processed/d/ab/part-0000.parquet",
    ):
        bucket.put_text(k, "x", "application/octet-stream")
    assert bucket.delete_prefix("processed/d/a/") == 2
    assert bucket.exists("processed/d/ab/part-0000.parquet")
    assert not bucket.exists("processed/d/a/part-0000.parquet")
    assert bucket.delete_prefix("processed/none/") == 0
