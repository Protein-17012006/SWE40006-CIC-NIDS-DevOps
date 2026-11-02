from app.data.storage import has_bucket, read_text

REPORT = "quarantine/broken/missing-dst-port/report.md"


def test_read_text(bucket, monkeypatch, settings_env, capsys):
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    bucket.put_text(REPORT, "# Report", "text/markdown")
    assert has_bucket() is True
    assert read_text(REPORT) == "# Report"
    assert read_text("quarantine/nothing.md") is None
    out = capsys.readouterr().out
    assert '"event": "s3_read_failed"' in out and '"key": "quarantine/nothing.md"' in out


def test_no_bucket(settings_env):
    assert has_bucket() is False and read_text(REPORT) is None
