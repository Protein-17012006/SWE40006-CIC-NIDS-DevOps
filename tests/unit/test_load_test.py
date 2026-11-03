"""The load test's verdict on Locust's statistics, and the page-shell parser its users rely on."""

from scripts.load_verdict import main, verdict
from tests.load.shell import static_paths

STATS = (
    "Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,"
    "Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%"
)


def stats(tmp_path, requests, failures, p95):
    path = tmp_path / "locust_stats.csv"
    numbers = f"{requests},{failures},40,50,10,900,500,4,0,40,45,50,55,70,{p95},300,400,800,900,900"
    path.write_text(f"{STATS}\nGET,/,{numbers}\n,Aggregated,{numbers}\n")
    return path


def failures_csv(tmp_path, rows):
    path = tmp_path / "locust_failures.csv"
    lines = "".join(f'{method},{name},"{error}",{count}\n' for method, name, error, count in rows)
    path.write_text("Method,Name,Error,Occurrences\n" + lines)
    return path


def test_clean_run_passes(tmp_path):
    v = verdict(stats(tmp_path, 1200, 0, 180), failures_csv(tmp_path, []))
    assert (v.ok, v.requests, v.failures, v.server_errors, v.p95_ms, v.notes) == (
        True,
        1200,
        0,
        0,
        180,
        [],
    )


def test_any_failure_fails_and_5xx_are_counted(tmp_path):
    rows = [
        ("GET", "/", "HTTPError('503 Server Error: Service Unavailable for url: /')", 2),
        ("GET", "/_stcore/health", "ConnectionResetError(104, 'Connection reset by peer')", 1),
    ]
    v = verdict(stats(tmp_path, 1200, 3, 200), failures_csv(tmp_path, rows))
    assert not v.ok and (v.failures, v.server_errors) == (3, 2)
    assert v.notes == ["3 requests failed, 2 of them with a 5xx"]


def test_slow_run_only_warns(tmp_path, capsys):
    s, f = stats(tmp_path, 1200, 0, 2500), failures_csv(tmp_path, [])
    assert verdict(s, f).notes == ["p95 2,500 ms is above 2,000 ms"]
    assert main([str(s), str(f)]) == 0
    assert "::warning::p95 2,500 ms is above 2,000 ms" in capsys.readouterr().out


def test_no_requests_fails(tmp_path):
    v = verdict(stats(tmp_path, 0, 0, 0), failures_csv(tmp_path, []))
    assert not v.ok and v.notes == ["Locust sent no requests"]


def test_missing_statistics_fail(tmp_path):
    v = verdict(tmp_path / "none_stats.csv", tmp_path / "none_failures.csv")
    assert not v.ok and v.notes == ["Locust wrote no statistics"]


def test_failed_run_prints_an_error_annotation(tmp_path, capsys):
    s, f = stats(tmp_path, 0, 0, 0), failures_csv(tmp_path, [])
    assert main([str(s), str(f)]) == 1
    out = capsys.readouterr().out
    assert "::error::Locust sent no requests" in out and "| Requests |" in out


def test_static_paths_reads_scripts_preloads_and_styles():
    shell = (
        '<link rel="shortcut icon" href="./favicon.png" />'
        '<script type="module" crossorigin src="./static/js/index.Dlja0TUX.js"></script>'
        '<link rel="modulepreload" crossorigin href="./static/js/react-dom.CbzydqoA.js">'
        '<link rel="modulepreload" crossorigin href="./static/js/react-dom.CbzydqoA.js">'
    )
    assert static_paths(shell) == [
        "/static/js/index.Dlja0TUX.js",
        "/static/js/react-dom.CbzydqoA.js",
    ]
    assert static_paths("<html></html>") == []
