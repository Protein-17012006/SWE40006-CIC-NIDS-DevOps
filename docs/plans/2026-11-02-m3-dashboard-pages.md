# M3 Dashboard Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The six dashboard pages show real data from PostgreSQL in Streamlit's Material theme in all four environments, each page shipped by its own pull request through CI and CD.

**Architecture:** A first pull request swaps the theme and adds the parts every page shares: seeded test fixtures, sidebar filters kept in session state, a guard for missing fields, a `chart_card` that handles the hidden, failed, empty and CSV states, and Plotly helpers. Each later pull request adds one page: its queries in `app/data/queries.py` (cached, parameterised SQL over the aggregate and sample tables) and its view in `app/views/`, with AppTest page tests against the seeded fixtures.

**Tech Stack:** M2's stack plus `plotly`; Streamlit 1.66.1 (`st.navigation`, `st.dialog`, `st.download_button`, AppTest); headless Edge for screenshots of the deployed pages.

**Spec:** `docs/design/2026-11-02-dashboard-pages-design.md`, on top of the Design and Requirements Report (`C:\Users\huyho\OneDrive\Desktop\project_brief\Design_and_Requirements_Report_CIC-NIDS.docx`, sections 2.2, 4.4, 5 and 6.3) wherever the design does not depart from it. The build design and the M1 and M2 plans record what already exists.

## Global Constraints

- Every M1 and M2 global constraint still holds: venv `C:\Users\huyho\.venvs\cicnids`, `==` pins, JSON log lines without secrets or row data, `AWS_PROFILE=hoang` for AWS commands from the laptop, LF endings, commits ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- One branch and one pull request per row of design section 6.1: `feat/m3-shell`, `feat/m3-overview`, `feat/m3-timeline`, `feat/m3-targets`, `feat/m3-pipeline`, `feat/m3-data-quality`, `feat/m3-feature-explorer`. Each is cut from an up-to-date main after the previous one is merged. Production approvals are the user's, in the GitHub UI: ask, then wait.
- Theme: the `[theme]` and `[theme.sidebar]` tables of Streamlit 1.66.1's bundled `material-ui.toml` (path in design section 4.1), unchanged except `chartCategoricalColors`.
- Category colours, exactly, in `ATTACK_CATEGORIES` order: Benign `#8F8D86`, DoS `#2A78D6`, DDoS `#EB6834`, Brute force `#1BAF7A`, Web attack `#EDA100`, Botnet `#E87BA4`, Infiltration `#008300`. Single-measure charts `#6750A4`. Every chart 300 px high.
- Charts only through Plotly and `st.plotly_chart`; `plotly` is the one new runtime dependency. No custom CSS, no `unsafe_allow_html`, no third-party components.
- SQL only in `app/data/queries.py`. A field name reaches SQL only as a whitelisted canonical column or as a bound parameter (`extras ->> :field`).
- Query rules (report section 4.4): filters as bound parameters; Benign always kept; null hours and days kept; the category filter skipped when `has_label` is false; `dst_port = -1` is "other" and never ranks; counts from `agg_hourly` and `agg_ports`, distributions from `flow_sample`; a dataset's figures sum over its files; "latest run per file" is `DISTINCT ON (file_key) ... ORDER BY file_key, run_id DESC`.
- Copy, exactly: `Hidden: this chart needs the {field} field.`; `NO_FLOWS = "No flows match the filters."`; `NO_DATA = "No dataset is loaded yet. The runbook's \"Load data\" section explains how to load one."`; `DB_DOWN = "The database cannot be reached. The Pipeline page shows the connection status."`; `CARD_FAILED = "This card could not load its data. The logs have the error."`; status badges `✅ Loaded`, `⚠️ Quarantined`, `❌ Failed`, `⏳ Running`. Other copy is given by the task that draws it.
- Filter state lives in `st.session_state` under `filter_dataset` (a dataset id), `filter_dates` (a tuple of one or two dates) and `filter_categories` (a list of category names). Page tests pick a dataset with `at.session_state["filter_dataset"] = "simulated-real-traffic-01"`.
- Numbers on screen go through `app/components/format.py` (Task 2). No `%-d` in `strftime`: it fails on Windows. Tables show those formatted strings; a card's CSV download holds the raw query frame.
- Ledger: `.superpowers/sdd/2026-11-02-m3-dashboard-pages/progress.md` (git-ignored), same format as M2's.
- Test command: `TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres C:\Users\huyho\.venvs\cicnids\Scripts\python.exe -m pytest`, with `docker compose up -d db` running (start Docker Desktop first). CI keeps `--cov=pipeline --cov-fail-under=80`.

## Review Focus

1. **A date range picked halfway.** While a viewer picks a range, `st.date_input` returns one date and the page reruns. Pages treat it as that one day and never raise. Pinned by Task 3 (`test_single_date_counts_as_one_day`).
2. **Switching dataset after narrowing the filters.** Moving from the baseline to the one-day simulated file leaves a date range outside the new bounds and categories the file cannot have. Both reset to the new dataset's defaults without a Streamlit exception. Pinned by Task 3 (`test_changing_dataset_resets_dates_and_categories`).
3. **Zero and negative values on a log scale.** Real flows have `bwd_packets = 0` and some negative durations, and the Feature explorer's log scale is on by default. Log-scale charts use values above 0 and say so; the summary table uses every value. Pinned by Task 16 (`test_field_stats_positive_only`, `test_log_scale_caption_mentions_left_out_values`).
4. **No attack category selected.** Attack-only visuals show `NO_FLOWS`, the Benign bar still draws, and nothing raises. Pinned by Task 6 (`test_overview_with_no_categories`).
5. **Text or unknown extra fields.** `geo_country` holds text, and a crafted field name must never reach SQL. Text extras are not offered, and an unknown field raises `ValueError` before any SQL runs. Pinned by Task 16 (`test_text_extras_not_offered`, `test_unknown_field_rejected`).

---

## The seeded fixture

Task 1 loads this through `pipeline.load.start_run` and `finish_run`, so every table is filled the way ingestion fills it. Every later test asserts against these numbers.

**Runs**

| Run | File | Status | Read / loaded / rejected | Other |
| --- | --- | --- | --- | --- |
| 1 | `raw/cse-cic-ids2018/Wednesday-14-02-2018.csv` | loaded | 3,500 / 3,405 / 45 | contract `cse-cic-ids2018` v1; 15 source columns; first/last ts 14 Feb 2018 09:00 / 15:59 |
| 2 | `raw/cse-cic-ids2018/Wednesday-21-02-2018.csv` | failed | 0 / 0 / 0 | message `Failed: the task stopped before the run finished.`; no data |
| 3 | same file as run 2 | loaded | 3,800 / 3,750 / 0 | contract `cse-cic-ids2018` v1; 15 source columns; 21 Feb 2018 09:00 / 16:59 |
| 4 | `raw/simulated-real-traffic-01.csv` | loaded | 1,000 / 1,000 / 0 | contract `simulated-real-traffic` v1; 10 source columns; new columns `pkt_entropy`, `geo_country`; 2 Mar 2018 09:00 / 11:59 |
| 5 | `raw/broken/missing-dst-port.csv` | quarantined | 20 / 0 / 0 | message `1 required field not found: dst_port.`; `report_key` `quarantine/broken/missing-dst-port/report.md`; `draft_contract_key` `quarantine/broken/missing-dst-port/draft-contract.yaml`; no data |

Datasets that result: `cse-cic-ids2018` (loaded, label, 7,155 flows, every canonical field, extras `bwd_psh_flags`, `fwd_pkt_len_max`), `simulated-real-traffic-01` (loaded, no label, 1,000 flows, fields `timestamp`, `dst_port`, `protocol`, `flow_duration_us`, `fwd_packets`, `bwd_packets`, `fwd_bytes`, `bwd_bytes`, extras `pkt_entropy`, `geo_country`), `broken` (quarantined, 0 flows).

**`agg_hourly`** (hour: label, flows)

- 14 Feb 2018 — 09:00 Benign 1,000 · 10:00 Benign 1,000, FTP-BruteForce 400 · 11:00 Benign 500, SSH-Bruteforce 300 · 14:00 Bot 200 · 15:00 Brute Force -Web 5
- 21 Feb 2018 — 09:00 Benign 900 · 14:00 Benign 200, DDOS attack-HOIC 2,000 · 15:00 DoS attacks-Hulk 600 · 16:00 Infilteration 50
- 2 Mar 2018, no label — 09:00 300 · 10:00 500 · 11:00 200

Categories: FTP-BruteForce and SSH-Bruteforce are Brute force, Bot is Botnet, Brute Force -Web is Web attack, DDOS attack-HOIC is DDoS, DoS attacks-Hulk is DoS, Infilteration is Infiltration. Totals: Benign 3,600, DDoS 2,000, Brute force 700, DoS 600, Botnet 200, Infiltration 50, Web attack 5; attacks 3,555; all 7,155.

**`agg_ports`** (category: protocol/port flows)

- 14 Feb — Benign 6/443 1,500, 17/53 900, 1/0 100 · Brute force 6/21 400, 6/22 300 · Botnet 6/8080 198, 6/80 2 · Web attack 6/80 5
- 21 Feb — Benign 6/443 700, 17/53 350, 6/-1 50 · DDoS 6/80 1,990, 17/53 10 · DoS 6/80 600 · Infiltration 6/445 30, 6/3389 15, 6/-1 5
- 2 Mar, no category — 6/443 500, 6/80 300, 17/53 150, 6/22 50

**`flow_sample`**: five rows per labelled category and five unlabelled rows (40). Row i (1 to 5): `flow_duration_us` = base × i, with base Benign 10,000, DoS 1,000, DDoS 2,000, Brute force 3,000, Web attack 1,000,000, Botnet 500, Infiltration 100, unlabelled 4,000; `fwd_packets` = i; `bwd_packets` = 0, 0, 1, 2, 3; `fwd_bytes` = 100 i; `bwd_bytes` = 50 × `bwd_packets`; `flow_bytes_per_s` = 1,000 i and `flow_packets_per_s` = 10 i (labelled only); `ts`, `label`, `dst_port`, `protocol` from the category's first hourly and port rows. Extras: labelled `{"bwd_psh_flags": 0, "fwd_pkt_len_max": 10 i}`, unlabelled `{"pkt_entropy": i as a float, "geo_country": "VN"}`.

**Quality**: run 1 steps `duplicates_removed` 50, `infinite_set_to_null` 12, `missing_kept_as_null` 7, `repeated_headers_dropped` 1, `labels_trimmed` 0, columns `flow_bytes_per_s` (7 nulls, 12 infinite, `infinite set to null`) and `bwd_psh_flags` (0, 0, `constant, hidden`). Run 3 steps 50, 8, 0, 0, 0, columns `flow_bytes_per_s` (0, 8, `infinite set to null`) and `bwd_psh_flags` (0, 0, `constant, hidden`). Run 4: every step 0, no columns.

## Shipping a pull request

Every "Ship" task runs these steps; the task adds its title, requirement IDs and what to look at.

1. **Local checks.** The test command, `python -m ruff check .` and `python -m ruff format --check .`. Expected: all pass.
2. **Pull request.** `git push -u origin <branch>`, then `gh pr create` with the template filled in (requirement IDs, definition-of-done ticks). Expected: `gh pr checks --watch` shows lint, test, cfn-lint and image green.
3. **Merge.** `gh pr merge --merge --delete-branch`. Expected: `gh run watch` on the new CD run shows development, test and staging deployed with passing smoke tests, and production waiting for approval.
4. **Look at the page.** For development (port 8082) and staging (port 8080) of `http://cicnids-1239707461.us-east-1.elb.amazonaws.com`: `"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --hide-scrollbars --window-size=1366,768 --virtual-time-budget=15000 --screenshot=<scratchpad>/<env>-<page>.png <url>/<page>`, then read the image. Then `aws logs filter-log-events --log-group-name /cicnids/<env> --start-time <deploy time in ms> --filter-pattern '{ $.event = "query_failed" || $.event = "s3_read_failed" }'`. Expected: the page as the task describes, at 1366 × 768 without horizontal scrolling, and no events.
5. **Production.** Ask the user to approve production in the CD run, and wait. Expected: production deployed; the same screenshot and log check on port 80 pass.
6. **Ledger.** Record the pull request, merge commit, CD run id, screenshot paths and anything that differed.

---

### Task 1: Branch, docs and the seeded fixture

**Files:**
- Create: `tests/fixtures/seed.py`, `tests/db/test_seed.py`
- Modify: `tests/conftest.py`, `.github/pull_request_template.md`
- Commit: `docs/design/2026-11-02-dashboard-pages-design.md`, `docs/plans/2026-11-02-m3-dashboard-pages.md`

**Interfaces:**
- Consumes: `pipeline.load.start_run(engine, dataset_id, file_key, commit_sha) -> int`, `finish_run(engine, run_id, record: RunRecord, data: FileData | None)`, `RunRecord`, `FileData`, `ColumnIssue` (`pipeline.accumulate`), `SAMPLE_COLUMNS`.
- Produces: `tests.fixtures.seed.LABELLED = "cse-cic-ids2018"`, `UNLABELLED = "simulated-real-traffic-01"`, `BROKEN = "broken"`; `seed(engine: sa.Engine) -> None` (the fixture above, on a migrated, empty database); `python -m tests.fixtures.seed` seeds `DATABASE_URL`; conftest fixture `seeded_db_url(migrated_db_url) -> str`.

- [ ] **Step 1: Branch, docs and ledger.** `git switch main && git pull && git switch -c feat/m3-shell`. In the pull request template, replace the first definition-of-done line with "It follows its page in `docs/design/2026-11-02-dashboard-pages-design.md` section 5 and is usable at 1366 × 768". Commit the template, the design and this plan: `Plan milestone 3: the dashboard pages`. Start the ledger.

- [ ] **Step 2: Write the failing test**

```python
# tests/db/test_seed.py
@pytest.mark.db
def test_seed_fills_every_table(seeded_db_url):
    engine = sa.create_engine(seeded_db_url)
    with engine.connect() as conn:
        rows = lambda sql: conn.execute(sa.text(sql)).all()
        assert rows("SELECT dataset_id, status, has_label, row_count FROM datasets ORDER BY 1") == [
            ("broken", "quarantined", False, 0),
            ("cse-cic-ids2018", "loaded", True, 7155),
            ("simulated-real-traffic-01", "loaded", False, 1000),
        ]
        assert rows("SELECT run_id, status FROM ingestion_runs ORDER BY 1") == [
            (1, "loaded"), (2, "failed"), (3, "loaded"), (4, "loaded"), (5, "quarantined")]
        assert rows("SELECT SUM(flows) FROM agg_ports WHERE dataset_id = 'cse-cic-ids2018'") == [(7155,)]
        assert rows("SELECT COUNT(*) FROM flow_sample") == [(40,)]
        assert rows("SELECT SUM(rows_affected) FROM quality_steps") == [(128,)]
    engine.dispose()
```

- [ ] **Step 3: Run it to see it fail.** Run: `python -m pytest tests/db/test_seed.py`. Expected: ERROR, fixture `seeded_db_url` not found.

- [ ] **Step 4: Implement `seed(engine)` and `seeded_db_url`.** Build each run's `FileData` and `RunRecord` from the fixture tables and call `start_run` then `finish_run` in run order (run 2 before run 3, so the latest run of that file is the loaded one). Commit sha `seed000`. `main()` refuses to run unless `APP_ENV` is `local` or `test`, so a real environment is never seeded.

- [ ] **Step 5: Run the test and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 6: Commit** — `Seed a labelled, an unlabelled and a quarantined dataset for page tests`.

### Task 2: Material theme, category colours, number formats and port names

**Files:**
- Modify: `.streamlit/config.toml`, `requirements.txt`, `app/data/fields.py`
- Create: `app/components/format.py`, `app/data/ports.py`, `tests/unit/test_theme.py`, `tests/unit/test_format.py`

**Interfaces:**
- Produces in `app/data/fields.py`: `CATEGORY_COLORS: dict[str, str]` (the Global Constraints colours, in `ATTACK_CATEGORIES` order); `ATTACK_ONLY: tuple[str, ...] = ATTACK_CATEGORIES[1:]`.
- Produces in `app/components/format.py`: `compact(n: float) -> str`; `percent(share: float) -> str`; `mmss(seconds: float) -> str`; `day_label(d: date) -> str`; `date_label(d: date) -> str`; `span_label(first: date, last: date) -> str`; `stamp_label(ts: datetime) -> str`; `hour_label(hour: int) -> str`; `with_unit(value: float, unit: str) -> str`; `basename(key: str) -> str`.
- Produces in `app/data/ports.py`: `SERVICE_NAMES: dict[int, str]` (0 no port, 21 FTP, 22 SSH, 25 SMTP, 53 DNS, 80 HTTP, 123 NTP, 139 NetBIOS, 443 HTTPS, 445 SMB, 3389 RDP, 8080 HTTP alt); `port_label(port: int) -> str`; `protocol_name(number: int) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_theme.py
def test_theme_is_material_with_category_colours():
    path = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    theme = config["theme"]
    assert theme["primaryColor"] == "#6750A4" and theme["baseRadius"] == "16px"
    assert "Roboto" in theme["font"] and "sidebar" in theme
    assert theme["chartCategoricalColors"] == [CATEGORY_COLORS[c] for c in ATTACK_CATEGORIES]
    assert config["client"]["toolbarMode"] == "minimal"
    assert config["browser"]["gatherUsageStats"] is False

def test_category_colours():
    assert CATEGORY_COLORS == {"Benign": "#8F8D86", "DoS": "#2A78D6", "DDoS": "#EB6834",
        "Brute force": "#1BAF7A", "Web attack": "#EDA100", "Botnet": "#E87BA4", "Infiltration": "#008300"}

# tests/unit/test_format.py
@pytest.mark.parametrize("n, text", [(0, "0"), (928, "928"), (1400, "1.4 k"), (2000, "2 k"),
    (7155, "7.16 k"), (654_321, "654 k"), (1_260_000, "1.26 M"), (13_480_000, "13.5 M")])
def test_compact(n, text): assert compact(n) == text

def test_percent_and_mmss():
    assert percent(0.49685) == "49.7 %" and percent(1) == "100.0 %"
    assert [mmss(s) for s in (41, 130, 3600)] == ["0:41", "2:10", "60:00"]

def test_dates():
    assert day_label(date(2018, 2, 14)) == "14 Feb" and date_label(date(2018, 3, 2)) == "2 Mar 2018"
    assert span_label(date(2018, 2, 14), date(2018, 2, 21)) == "14 Feb – 21 Feb 2018"
    assert span_label(date(2018, 3, 2), date(2018, 3, 2)) == "2 Mar 2018"
    assert stamp_label(datetime(2026, 10, 28, 9, 14, tzinfo=UTC)) == "28 Oct 2026, 09:14 UTC"
    assert hour_label(9) == "09:00" and basename("raw/broken/missing-dst-port.csv") == "missing-dst-port.csv"

@pytest.mark.parametrize("value, unit, text", [(10, "µs", "10 µs"), (30_000, "µs", "30 ms"),
    (4_200_000, "µs", "4.2 s"), (1500, "B", "1.5 kB"), (12, "pkt", "12 pkt"), (2.5, "", "2.5")])
def test_with_unit(value, unit, text): assert with_unit(value, unit) == text

def test_ports_and_protocols():
    assert [port_label(p) for p in (80, 0, 5000, -1)] == ["80 · HTTP", "0 · no port", "5000", "other"]
    assert [protocol_name(n) for n in (6, 17, 1, 47)] == ["TCP", "UDP", "ICMP", "Other"]
```

- [ ] **Step 2: Run them to see them fail.** Run: `python -m pytest tests/unit/test_theme.py tests/unit/test_format.py`. Expected: FAIL, `ImportError` for `CATEGORY_COLORS`.

- [ ] **Step 3: Implement.** Copy `material-ui.toml` into `.streamlit/config.toml` in place of the old `[theme]`, set `chartCategoricalColors`, keep `[browser]` and `[client]`. Pin `plotly` in `requirements.txt` at the latest release at least two weeks old (`python -m pip index versions plotly`) and install it. `compact` is `f"{n / scale:.3g}"` with the suffixes "", " k", " M", " B"; `percent` has one decimal; `with_unit` scales µs to ms and s, B to kB, MB and GB (factors of 1,000), and B/s likewise, with `.3g`; dates are built from `d.day` and `%b %Y`.

- [ ] **Step 4: Run the tests and the linters.** Expected: PASS; ruff clean. Run the app (`streamlit run app/main.py`) once and look: Roboto, purple navigation, 16 px corners.

- [ ] **Step 5: Commit** — `Switch to the Material theme and add category colours and number formats`.

### Task 3: Sidebar filters and the guard

**Files:**
- Create: `app/components/filters.py`, `app/components/guard.py`, `tests/unit/test_guard.py`, `tests/app/test_filters.py`
- Modify: `app/main.py`, `app/data/queries.py`, `tests/conftest.py`, `tests/db/test_queries.py`

**Interfaces:**
- Consumes: `CATEGORY_COLORS`, `ATTACK_ONLY` (Task 2); `seeded_db_url`, `LABELLED`, `UNLABELLED` (Task 1).
- Produces in `queries.py`: `loaded_datasets() -> pd.DataFrame` with `dataset_id, display_name, has_label, fields, extra_fields, row_count, first_ts, last_ts, loaded_at` (lists for the two array columns), status `loaded` only, `cse-cic-ids2018` first, then by `row_count` descending.
- Produces in `filters.py`: `BASELINE = "cse-cic-ids2018"`; `DATASET_KEY = "filter_dataset"`, `DATES_KEY = "filter_dates"`, `CATEGORIES_KEY = "filter_categories"`; `DB_DOWN`, `NO_DATA` (Global Constraints copy); frozen dataclass `Filters(dataset_id: str, display_name: str, has_label: bool, fields: tuple[str, ...], extra_fields: tuple[str, ...], date_from: date | None, date_to: date | None, categories: tuple[str, ...], row_count: int, loaded_at: datetime | None)`; `current_filters(datasets: pd.DataFrame, state: Mapping[str, object]) -> Filters | None` (pure); `sidebar_filters() -> None`; `page_filters() -> Filters`.
- Produces in `guard.py`: `missing(f: Filters, needs: Sequence[str]) -> list[str]` — `label` is missing when `has_label` is false, `timestamp` when it is not in `fields` or `date_from` is None, any other field when it is in neither `fields` nor `extra_fields`; order follows `needs`.
- Produces in `tests/conftest.py`: fixture `use_seeded_db(seeded_db_url, settings_env, monkeypatch, clear_caches) -> str` (sets `DATABASE_URL` to the seeded database, clears caches, returns the URL); fixture `filters_for(use_seeded_db)` returning `make(dataset: str = LABELLED, dates: tuple[date, ...] | None = None, categories: list[str] | None = None) -> Filters` (calls `current_filters(loaded_datasets(), state)`); fixture `run_app(use_seeded_db)` returning `run(script: str, state: Mapping[str, object] | None = None) -> AppTest` (`script` relative to `app/`, such as `"main.py"` or `"views/overview.py"`; clears caches, writes `state` into `at.session_state`, runs with `default_timeout=30`).
- Produces `tests/app/page_helpers.py` (imported as `from page_helpers import ...`; pytest's default import mode puts `tests/app` on `sys.path`): `tiles(at) -> dict[str, str]` (metric label to value), `captions(at) -> list[str]`, `markdown(at) -> set[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_guard.py
def test_guard_label_timestamp_and_extras():
    unlabelled = make(has_label=False, fields=("timestamp", "dst_port"), extra_fields=("pkt_entropy",))
    assert missing(unlabelled, ["label", "dst_port", "pkt_entropy"]) == ["label"]
    assert missing(make(fields=("dst_port",), date_from=None), ["timestamp"]) == ["timestamp"]

# tests/app/test_filters.py — DATASETS is a two-row frame like loaded_datasets() returns for the fixture
def test_defaults_to_baseline_full_span_all_categories():
    f = current_filters(DATASETS, {})
    assert (f.dataset_id, f.date_from, f.date_to) == ("cse-cic-ids2018", date(2018, 2, 14), date(2018, 2, 21))
    assert f.categories == ATTACK_ONLY

def test_single_date_counts_as_one_day():                       # Review Focus 1
    f = current_filters(DATASETS, {DATES_KEY: (date(2018, 2, 21),)})
    assert f.date_from == f.date_to == date(2018, 2, 21)

def test_dates_outside_the_span_fall_back_to_the_span():
    f = current_filters(DATASETS, {DATES_KEY: (date(2018, 3, 1), date(2018, 3, 2))})
    assert (f.date_from, f.date_to) == (date(2018, 2, 14), date(2018, 2, 21))

def test_unlabelled_dataset_has_no_categories():
    f = current_filters(DATASETS, {DATASET_KEY: "simulated-real-traffic-01", CATEGORIES_KEY: ["DDoS"]})
    assert f.has_label is False and f.categories == ()

def test_no_loaded_dataset():
    assert current_filters(DATASETS.iloc[0:0], {}) is None

@pytest.mark.db
def test_sidebar_draws_filters(run_app):
    at = run_app("main.py")
    assert at.selectbox(key=DATASET_KEY).options == ["cse-cic-ids2018", "simulated-real-traffic-01"]
    assert at.multiselect(key=CATEGORIES_KEY).value == list(ATTACK_ONLY)
    assert "FILTERS" in [c.value for c in at.sidebar.caption]

@pytest.mark.db
def test_changing_dataset_resets_dates_and_categories(run_app):    # Review Focus 2
    at = run_app("main.py")
    at.multiselect(key=CATEGORIES_KEY).set_value(["DDoS"]).run()
    at.selectbox(key=DATASET_KEY).select("simulated-real-traffic-01").run()
    assert not at.exception
    assert at.date_input(key=DATES_KEY).value == (date(2018, 3, 2), date(2018, 3, 2))
    assert at.multiselect(key=CATEGORIES_KEY).disabled

def test_sidebar_without_database(settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not at.exception and len(at.sidebar.selectbox) == 0

# tests/db/test_queries.py
@pytest.mark.db
def test_loaded_datasets_baseline_first(use_seeded_db):
    assert loaded_datasets()["dataset_id"].tolist() == ["cse-cic-ids2018", "simulated-real-traffic-01"]
```

`make(**overrides)` in `test_guard.py` builds a `Filters` with the labelled dataset's values; `DATASETS` in `test_filters.py` is the two-row frame `loaded_datasets()` returns for the fixture, built by hand.

- [ ] **Step 2: Run them to see them fail.** Run: `python -m pytest tests/unit/test_guard.py tests/app/test_filters.py tests/db/test_queries.py`. Expected: FAIL, `ModuleNotFoundError: No module named 'app.components.filters'`.

- [ ] **Step 3: Implement.** `sidebar_filters` draws, in `st.sidebar`: the caption "FILTERS"; "Dataset" (`st.selectbox`, options the dataset ids, `format_func` the display name, `on_change` deleting `DATES_KEY` and `CATEGORIES_KEY`); "Date range" (`st.date_input` bounded by the first and last day, drawn only when the dataset has timestamps); "Attack categories" (`st.multiselect` over `ATTACK_ONLY`, disabled with the caption "This dataset has no label." when `has_label` is false). It passes a widget's `value` only when its key is not yet in session state, so no "set via the Session State API" warning appears. When `loaded_datasets()` raises it logs `query_failed` and draws nothing; with no loaded dataset it draws nothing. `page_filters` shows `st.error(DB_DOWN)` and calls `st.stop()` when the query raises (after logging `query_failed`), `st.info(NO_DATA)` and `st.stop()` when there is no dataset, and otherwise returns `current_filters(loaded_datasets(), st.session_state)`. `main.py` calls `sidebar_filters()` right after `st.navigation`.

- [ ] **Step 4: Run the tests and the linters.** Expected: PASS, including `tests/app/test_main.py`; ruff clean.

- [ ] **Step 5: Commit** — `Add the sidebar filters and the field guard`.

### Task 4: Cards, charts and their states

**Files:**
- Modify: `app/components/layout.py`
- Create: `app/components/charts.py`, `tests/app/test_cards.py`, `tests/unit/test_charts.py`

**Interfaces:**
- Consumes: `Filters`, `missing` (Task 3); `CATEGORY_COLORS`, `compact` (Task 2); `log_event`.
- Produces in `layout.py`: `NO_FLOWS`, `CARD_FAILED` (Global Constraints copy); `hidden_card(title: str, field: str) -> None`; `chart_card(title: str, caption: str | Callable[[pd.DataFrame], str], load: Callable[[], pd.DataFrame], render: Callable[[pd.DataFrame], None], *, filters: Filters | None = None, needs: Sequence[str] = (), csv: bool = True) -> None`. `page_header`, `kpi_tile`, `env_banner`, the sidebar helpers and `coming_soon` stay.
- Produces in `charts.py`: `PRIMARY = "#6750A4"`; `CHART_HEIGHT = 300`; `PROTOCOL_COLORS = {"TCP": "#6750A4", "UDP": "#7D5260", "ICMP": "#625B71", "Other": "#CAC4D0"}`; `bars(df: pd.DataFrame, value: str, label: str, *, color: str | None = None, log: bool = False, horizontal: bool = True) -> go.Figure`; `stacked(df: pd.DataFrame, x: str, value: str, color: str, *, percent: bool = False, horizontal: bool = False, order: Sequence[str] | None = None, colors: Mapping[str, str] | None = None) -> go.Figure`; `share_bar(df: pd.DataFrame, category: str, share: str) -> go.Figure`; `box_from_stats(stats: pd.DataFrame, *, log: bool) -> go.Figure`; `histogram_from_bins(bins: pd.DataFrame, *, log: bool) -> go.Figure`; `show(fig: go.Figure, *, key: str | None = None, select: bool = False) -> object`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_charts.py
def test_bars_use_category_colours_value_labels_and_log_axis():
    df = pd.DataFrame({"attack_category": ["Benign", "DDoS"], "flows": [3600, 2000]})
    fig = bars(df, "flows", "attack_category", color="attack_category", log=True)
    assert list(fig.data[0].marker.color) == ["#8F8D86", "#EB6834"]
    assert list(fig.data[0].text) == ["3.6 k", "2 k"] and fig.layout.xaxis.type == "log"

def test_single_measure_bars_use_primary():
    fig = bars(pd.DataFrame({"port": ["80 · HTTP"], "flows": [10]}), "flows", "port")
    assert fig.data[0].marker.color == "#6750A4" and fig.layout.height == 300

def test_share_bar_labels_segments_of_ten_percent_or_more():
    df = pd.DataFrame({"attack_category": ["DDoS", "DoS", "Infiltration"], "share": [0.6, 0.35, 0.05]})
    assert [t.text[0] for t in share_bar(df, "attack_category", "share").data] == ["60.0 %", "35.0 %", ""]

def test_box_from_stats_uses_precomputed_fences():
    stats = pd.DataFrame({"attack_category": ["DDoS"], "p5": [1.0], "q1": [2.0], "median": [3.0], "q3": [4.0], "p95": [5.0]})
    box = box_from_stats(stats, log=False).data[0]
    assert (box.lowerfence[0], box.q1[0], box.median[0], box.q3[0], box.upperfence[0]) == (1, 2, 3, 4, 5)

# tests/app/test_cards.py — run(fn) is AppTest.from_function(fn).run(); each card function is
# module-level and imports what it uses inside its body, because from_function runs only its source
def test_card_hidden_when_field_missing():          # load must not be called
    at = run(card_needing_label_on_unlabelled_filters)
    assert at.caption[0].value == "Hidden: this chart needs the label field." and not at.exception

def test_failed_query_warns_and_logs(capsys):
    at = run(card_whose_load_raises)
    assert at.warning[0].value == CARD_FAILED
    assert '"event": "query_failed"' in capsys.readouterr().out

def test_empty_data_says_no_flows():
    at = run(card_with_empty_frame)
    assert at.info[0].value == NO_FLOWS and len(at.get("download_button")) == 0

def test_card_offers_csv():
    at = run(card_with_two_rows)
    assert at.get("download_button")[0].label == "CSV"
```

- [ ] **Step 2: Run them to see them fail.** Run: `python -m pytest tests/unit/test_charts.py tests/app/test_cards.py`. Expected: FAIL, `ModuleNotFoundError: No module named 'app.components.charts'`.

- [ ] **Step 3: Implement.** `chart_card`: when `missing(filters, needs)` is not empty, `hidden_card(title, <first missing field>)` (a bordered container with the bold title and the hidden caption) and return. Otherwise a bordered container whose first row is an `st.container(horizontal=True, horizontal_alignment="distribute")` holding the bold title; then `load()`. An exception logs `query_failed` with `card=title` and the message's first line and shows `st.warning(CARD_FAILED)`; an empty frame shows `st.info(NO_FLOWS)`; otherwise the caption (called with the frame when it is a callable), `render(frame)`, and, when `csv`, a tertiary `st.download_button("CSV", icon=":material/download:", file_name=<title slug>.csv)` added to the title row. Charts: `bars` colours by `CATEGORY_COLORS` when `color == "attack_category"`, else `PRIMARY`, with `compact` value labels outside the bars; `share_bar` is one 100 % horizontal stack with `percent` labels on segments of 0.10 or more and the legend below; `box_from_stats` draws one `go.Box` per row with `lowerfence=p5, q1, median, q3, upperfence=p95`, a white median line, and the category colour, or `PRIMARY` for "All traffic"; `show` calls `st.plotly_chart(fig, theme="streamlit", config={"displayModeBar": False})`, with `on_select="rerun"` and the key when `select`, and returns its result.

- [ ] **Step 4: Run the tests and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 5: Commit** — `Add cards with hidden, failed, empty and CSV states, and the Plotly helpers`.

### Task 5: Ship pull request 1 — theme and shared parts

Follow "Shipping a pull request". Title `M3: Material theme and shared dashboard parts`; requirement IDs UI-01, UI-08, UI-09, UI-11.

- [ ] **Step 1–6.** Look for: every page in the Material theme with the filters under the navigation; the placeholders still in place; the Pipeline tiles unchanged; in staging, the Dataset list starting with `cse-cic-ids2018`.

### Task 6: Overview page (UI-02, UI-08, UI-09)

Branch `feat/m3-overview`.

**Files:**
- Modify: `app/data/queries.py`, `app/views/overview.py`, `tests/db/test_queries.py`
- Create: `tests/app/test_overview_page.py`, `tests/app/test_page_states.py`

**Interfaces:**
- Consumes: Tasks 2 to 4; fixture `filters_for`.
- Produces in `queries.py` (each `@st.cache_data(ttl=300)`, taking `f: Filters` unless noted):
  - `kpi_totals(f) -> pd.DataFrame`, one row: `flows, attack_flows, attack_types, categories, capture_days, first_day, last_day`
  - `flows_by_category(f) -> [attack_category, flows]`, flows descending
  - `top_attack_labels(f, limit: int = 8) -> [label, attack_category, flows, share]`, share of attack flows
  - `attack_mix(f) -> [attack_category, flows, share]`, Benign left out
  - `flows_per_hour(f) -> [hour, flows]`, hour of day 0 to 23 summed over the selected days, all traffic
  - `top_ports(f, limit: int = 10, attack_only: bool = True) -> [dst_port, flows]`, `-1` left out
  - `dataset_files(dataset_id: str) -> [run_id, file_key, status, rows_read, rows_loaded, rows_rejected, source_columns, new_columns, started_at]`, the latest run of each file, by `file_key`

- [ ] **Step 1: Write the failing query tests**

```python
@pytest.mark.db
def test_kpi_totals(filters_for):
    row = kpi_totals(filters_for()).iloc[0]
    assert tuple(row) == (7155, 3555, 7, 6, 2, date(2018, 2, 14), date(2018, 2, 21))

@pytest.mark.db
def test_flows_by_category_keeps_benign_and_applies_filters(filters_for):
    pairs = lambda f: list(flows_by_category(f).itertuples(index=False, name=None))
    assert pairs(filters_for()) == [("Benign", 3600), ("DDoS", 2000), ("Brute force", 700),
        ("DoS", 600), ("Botnet", 200), ("Infiltration", 50), ("Web attack", 5)]
    assert pairs(filters_for(categories=["DDoS"])) == [("Benign", 3600), ("DDoS", 2000)]
    assert pairs(filters_for(dates=(date(2018, 2, 21), date(2018, 2, 21))))[:2] == [("DDoS", 2000), ("Benign", 1100)]

@pytest.mark.db
def test_top_attack_labels_and_mix(filters_for):
    labels = top_attack_labels(filters_for())
    assert labels.iloc[0][["label", "flows"]].tolist() == ["DDOS attack-HOIC", 2000] and len(labels) == 7
    mix = attack_mix(filters_for())
    assert "Benign" not in mix["attack_category"].tolist() and mix["share"].sum() == pytest.approx(1)

@pytest.mark.db
def test_top_ports_skips_the_other_bucket(filters_for):
    assert top_ports(filters_for())["dst_port"].tolist() == [80, 21, 22, 8080, 445, 3389, 53]
    assert top_ports(filters_for(categories=["DDoS"])).values.tolist() == [[80, 1990], [53, 10]]
    assert top_ports(filters_for(UNLABELLED), 8, attack_only=False).values.tolist() == [
        [443, 500], [80, 300], [53, 150], [22, 50]]

@pytest.mark.db
def test_flows_per_hour_and_dataset_files(filters_for):
    assert flows_per_hour(filters_for(UNLABELLED)).values.tolist() == [[9, 300], [10, 500], [11, 200]]
    assert dataset_files("cse-cic-ids2018")["run_id"].tolist() == [1, 3]
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL, `ImportError: cannot import name 'kpi_totals'`.

- [ ] **Step 3: Implement the queries.** Each follows report section 4.4's pattern: `dataset_id = :dataset_id`, `(hour IS NULL OR (hour >= :date_from AND hour < :date_to + INTERVAL '1 day'))` when the dataset has dates, and `(attack_category = 'Benign' OR attack_category = ANY(:categories))` when it has a label.

- [ ] **Step 4: Write the failing page tests**

```python
# tests/app/test_overview_page.py
PAGE = "views/overview.py"

@pytest.mark.db
def test_overview_labelled(run_app):
    at = run_app(PAGE)
    assert tiles(at) == {"Flows": "7.16 k", "Attack share": "49.7 %", "Attack types": "7", "Capture days": "2"}
    assert {"2 capture days", "3.56 k attack flows", "in 6 categories", "14 Feb – 21 Feb 2018"} <= set(captions(at))
    assert {"**Flows by category**", "**Top attack labels**", "**Attack mix**"} <= markdown(at)
    assert len(at.get("plotly_chart")) == 2 and len(at.dataframe) == 1

@pytest.mark.db
def test_overview_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert tiles(at) == {"Flows": "1 k", "Attack share": "—", "Attack types": "—", "New columns": "2"}
    assert at.info[0].value == ("This file has no label column, so the attack-category charts are hidden. "
        "Traffic charts still work, and the 2 new columns appear in the Feature explorer.")
    assert captions(at).count("Hidden: this chart needs the label field.") == 2

@pytest.mark.db
def test_overview_with_no_categories(run_app):                  # Review Focus 4
    at = run_app(PAGE, {"filter_categories": []})
    assert not at.exception and [i.value for i in at.info].count(NO_FLOWS) == 2
    assert len(at.get("plotly_chart")) == 1                     # Flows by category: Benign only

# tests/app/test_page_states.py — every page that reads the filters, in the two failure states
APP = Path(__file__).resolve().parents[2] / "app"
PAGES = ["overview"]                                            # each page task appends its view

@pytest.mark.parametrize("page", PAGES)
def test_page_without_database(page, settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    clear_caches()
    at = AppTest.from_file(str(APP / "views" / f"{page}.py"), default_timeout=30).run()
    assert not at.exception and at.error[0].value == DB_DOWN

@pytest.mark.db
@pytest.mark.parametrize("page", PAGES)
def test_page_on_an_empty_database(page, migrated_db_url, settings_env, monkeypatch, clear_caches):
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    clear_caches()
    at = AppTest.from_file(str(APP / "views" / f"{page}.py"), default_timeout=30).run()
    assert not at.exception and at.info[0].value == NO_DATA
```

- [ ] **Step 5: Run them to see them fail.** Expected: FAIL (the page still shows its placeholder).

- [ ] **Step 6: Implement the page.** `page_header("Overview")`, `page_filters()`, then the caption `{display name} · {compact(flows)} flows · {n} capture days, {span_label} · last loaded {stamp_label(loaded_at)}`. Labelled tiles: Flows (caption `{n} capture days`, singular for 1), Attack share (`{compact(attack_flows)} attack flows`), Attack types (`in {categories} categories`), Capture days (`span_label`). Unlabelled tiles: Flows; Attack share and Attack types "—" with the caption "no label column"; New columns (count; caption the names joined by ", ") when `dataset_files` reports new columns, else Capture days; then the `st.info` above (with "Traffic charts still work." ending the sentence when there are no new columns). Cards in design section 5.1 order, through `chart_card`: "Flows by category" (`Log scale · {span}`, `needs=("label",)`), "Top attack labels" (`Share of {compact(attack_flows)} attack flows`, table with Share through `percent`), "Attack mix" (`Share of attack flows by category`); unlabelled first row "Flows per hour" (`All traffic · {span}`, `needs=("timestamp",)`) and "Top destination ports" (`All traffic · linear scale`, `top_ports(f, 8, attack_only=False)`, labels through `port_label`).

- [ ] **Step 7: Run the tests and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 8: Commit** — `Build the Overview page and its unlabelled layout`.

### Task 7: Ship pull request 2 — Overview

Title `M3: Overview page`; IDs UI-02, UI-08, UI-09, UI-11.

- [ ] **Step 1–6.** Look for: in staging, Flows near 16.2 M for the baseline and the category bars on a log axis; with the simulated dataset selected (if staging holds it), the unlabelled layout under the staging banner.

### Task 8: Timeline page (UI-03)

Branch `feat/m3-timeline`.

**Files:**
- Modify: `app/data/queries.py`, `app/views/timeline.py`, `tests/db/test_queries.py`, `tests/app/test_page_states.py`
- Create: `tests/app/test_timeline_page.py`

**Interfaces:**
- Produces in `queries.py`:
  - `capture_days(f) -> [day, flows, attack_flows]` by day (`attack_flows` 0 without a label)
  - `attack_flows_per_day(f) -> [day, attack_category, flows]`, Benign left out
  - `flows_per_hour_on(f, day: date) -> [hour, label, attack_category, flows]`, Benign included
  - `busiest_hours(f, limit: int = 5) -> [day, hour, flows, main_category]`; the main category is the largest in that hour, Benign included, None without a label; ties go to the earlier day and hour

- [ ] **Step 1: Write the failing query tests**

```python
@pytest.mark.db
def test_timeline_queries(filters_for):
    f = filters_for()
    assert capture_days(f).values.tolist() == [[date(2018, 2, 14), 3405, 905], [date(2018, 2, 21), 3750, 2650]]
    per_day = attack_flows_per_day(f)
    day = per_day[per_day["day"] == date(2018, 2, 21)]
    assert dict(zip(day.attack_category, day.flows)) == {"DDoS": 2000, "DoS": 600, "Infiltration": 50}
    hour = flows_per_hour_on(f, date(2018, 2, 21)).query("hour == 14")
    assert dict(zip(hour.label, hour.flows)) == {"DDOS attack-HOIC": 2000, "Benign": 200}
    assert busiest_hours(f).values.tolist() == [
        [date(2018, 2, 21), 14, 2200, "DDoS"], [date(2018, 2, 14), 10, 1400, "Benign"],
        [date(2018, 2, 14), 9, 1000, "Benign"], [date(2018, 2, 21), 9, 900, "Benign"],
        [date(2018, 2, 14), 11, 800, "Benign"]]
    assert busiest_hours(filters_for(UNLABELLED))["main_category"].isna().all()
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement the queries.**

- [ ] **Step 4: Write the failing page tests**

```python
# tests/app/test_timeline_page.py — PAGE = "views/timeline.py"; every test is @pytest.mark.db
def test_timeline_defaults_to_the_busiest_attack_day(run_app):
    at = run_app(PAGE)
    assert at.selectbox(key="timeline_day").value == date(2018, 2, 21)
    assert "**Flows per hour on 21 Feb 2018**" in markdown(at)
    assert "DDOS attack-HOIC sent 2 k flows between 14:00 and 15:00" in captions(at)
    assert at.dataframe[0].value.iloc[0].tolist() == ["21 Feb", "14:00", "2.2 k", "DDoS"]

def test_timeline_follows_the_day_picker(run_app):
    at = run_app(PAGE)
    at.selectbox(key="timeline_day").select(date(2018, 2, 14)).run()
    assert "**Flows per hour on 14 Feb 2018**" in markdown(at)
    assert "Benign sent 1 k flows between 10:00 and 11:00" in captions(at)

def test_timeline_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert "Hidden: this chart needs the label field." in captions(at)
    assert at.selectbox(key="timeline_day").options == ["2 Mar 2018"]
    assert "Main category" not in at.dataframe[0].value.columns
```

Append `"timeline"` to `PAGES` in `tests/app/test_page_states.py`.

- [ ] **Step 5: Run them to see them fail.** Expected: FAIL.

- [ ] **Step 6: Implement the page.** Caption: "Benign traffic is hidden in the daily view so attacks stay visible", or "This dataset has no label, so the daily attack view is hidden". Card "Attack flows per capture day" (`Each capture day carries one attack campaign · {day_label} selected`, `needs=("label", "timestamp")`): bars per day stacked by attack category in `ATTACK_ONLY` order, value labels on top, the selected day shaded. Under it the day picker, `st.selectbox("Capture day", <days>, format_func=date_label, key="timeline_day")`, defaulting to the day with the most attack flows, or the first day without a label. A bar click may also set it, only through `show(fig, select=True)` writing `timeline_day` before the picker is drawn. Card "Flows per hour on {date_label}" (`needs=("timestamp",)`): 24 hourly bars stacked by category with Benign, or `PRIMARY` without a label; the caption names the peak hour's largest label, `{label} sent {compact(flows)} flows between {hour_label(h)} and {hour_label((h + 1) % 24)}`, or without a label `Peak: {compact(flows)} flows between … and …`. Card "Busiest hours" (`All capture days, attack and benign flows`): Day, Hour, Flows, Main category, the last left out without a label.

- [ ] **Step 7: Run the tests and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 8: Commit** — `Build the Timeline page with its day picker`.

### Task 9: Ship pull request 3 — Timeline

Title `M3: Timeline page`; IDs UI-03, UI-08, UI-11.

- [ ] **Step 1–6.** Look for: in staging, ten capture days with one dominant attack each, the busiest attack day picked, and its hourly chart naming the peak.

### Task 10: Targets page (UI-04)

Branch `feat/m3-targets`.

**Files:**
- Modify: `app/data/queries.py`, `app/views/targets.py`, `tests/db/test_queries.py`, `tests/app/test_page_states.py`
- Create: `tests/app/test_targets_page.py`

**Interfaces:**
- Consumes: `top_ports` (Task 6), `port_label`, `protocol_name`, `PROTOCOL_COLORS`.
- Produces in `queries.py`:
  - `protocol_mix(f) -> [attack_category, protocol, flows, share]`; `protocol` is "TCP", "UDP", "ICMP" or "Other", and share is within the category (None category without a label)
  - `main_ports(f) -> [attack_category, main_port, main_share, next_port, next_share]`, attack categories in `ATTACK_ONLY` order; `-1` never ranks but counts in the shares

- [ ] **Step 1: Write the failing query tests**

```python
@pytest.mark.db
def test_protocol_mix_and_main_ports(filters_for):
    mix = protocol_mix(filters_for()).set_index(["attack_category", "protocol"])["share"]
    assert mix["Benign"].round(3).to_dict() == {"TCP": 0.625, "UDP": 0.347, "ICMP": 0.028}
    assert mix["DDoS"].round(3).to_dict() == {"TCP": 0.995, "UDP": 0.005}
    ports = main_ports(filters_for()).set_index("attack_category")
    assert ports.loc["Infiltration"].tolist() == [445, pytest.approx(0.6), 3389, pytest.approx(0.3)]
    assert ports.loc["Brute force", "main_port"] == 21 and pd.isna(ports.loc["Web attack", "next_port"])
    assert protocol_mix(filters_for(UNLABELLED))["attack_category"].isna().all()
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement the queries.**

- [ ] **Step 4: Write the failing page tests**

```python
# tests/app/test_targets_page.py — PAGE = "views/targets.py"; every test is @pytest.mark.db
def test_targets_labelled(run_app):
    at = run_app(PAGE)
    assert at.caption[0].value.endswith("· 6 attack categories selected")
    assert at.info[0].value == 'Ports outside the top 50 per day, category and protocol are counted together as "other".'
    table = at.dataframe[0].value
    assert table.iloc[0].tolist() == ["DoS", "80 · HTTP", "100.0 %", "—"]
    assert table.set_index("Category").loc["DDoS", "Next port"] == "53 · DNS (0.5 %)"

def test_targets_one_category(run_app):                         # the UI-04 acceptance check
    at = run_app(PAGE, {"filter_categories": ["DDoS"]})
    assert at.caption[0].value.endswith("· 1 attack category selected") and len(at.dataframe[0].value) == 1

def test_targets_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert at.caption[0].value == "Destination ports and protocols of all traffic · this dataset has no label"
    assert "Hidden: this chart needs the label field." in captions(at)
```

Append `"targets"` to `PAGES`.

- [ ] **Step 5: Run them to see them fail.** Expected: FAIL.

- [ ] **Step 6: Implement the page.** Caption `Destination ports and protocols of attack traffic · {n} attack categor{y|ies} selected`, or the unlabelled caption above; then the `st.info`. Card "Top 10 destination ports" (`Attack flows · linear scale`, or `All traffic · linear scale`; `needs=("dst_port",)`): `bars` in `PRIMARY` with `port_label` labels from `top_ports(f, 10, attack_only=f.has_label)`. Card "Protocol mix by category" (`Share of flows per protocol, in TCP / UDP / ICMP order`, `needs=("protocol",)`): `stacked(..., percent=True, horizontal=True, order=("TCP", "UDP", "ICMP", "Other"), colors=PROTOCOL_COLORS)`, one bar per category in `ATTACK_CATEGORIES` order, or "All traffic". Card "Main port per attack category" (`Where each category sends most of its flows`, `needs=("label", "dst_port")`): Category, Main port, Share of its flows, Next port as `{port_label} ({percent})` or "—".

- [ ] **Step 7: Run the tests and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 8: Commit** — `Build the Targets page`.

### Task 11: Ship pull request 4 — Targets

Title `M3: Targets page`; IDs UI-04, UI-08, UI-11.

- [ ] **Step 1–6.** Look for: in staging, port 80 · HTTP on top; with only DDoS left in the filter, DDoS's own ports.

### Task 12: Pipeline page, the rest (UI-07)

Branch `feat/m3-pipeline`.

**Files:**
- Modify: `app/data/queries.py`, `app/views/pipeline.py`, `tests/db/test_queries.py`, `tests/app/test_pipeline_page.py`
- Create: `app/data/storage.py`, `tests/unit/test_app_storage.py`

**Interfaces:**
- Consumes: `pipeline.storage.Bucket(name, client=None).read_text(key) -> str`; the `bucket` fixture (moto, bucket `cicnids-test`).
- Produces in `queries.py`:
  - `datasets_table() -> [dataset_id, display_name, files, contract_name, contract_version, row_count, last_run_at, status]`, every dataset, `cse-cic-ids2018` first, then by display name
  - `recent_runs(limit: int = 20) -> [run_id, file_key, started_at, ended_at, rows_loaded, rows_rejected, status]`, newest first
  - `quarantined_files() -> [run_id, dataset_id, file_key, message, report_key, draft_contract_key]`, files whose latest run is quarantined, newest first
- Produces in `app/data/storage.py`: `has_bucket() -> bool`; `read_text(key: str) -> str | None` (None without a bucket; on a missing object or any client error it logs `s3_read_failed` at WARNING with the key and returns None).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.db
def test_pipeline_queries(use_seeded_db):
    table = datasets_table()
    assert table[["dataset_id", "files", "row_count", "status"]].values.tolist() == [
        ["cse-cic-ids2018", 2, 7155, "loaded"], ["broken", 1, 0, "quarantined"],
        ["simulated-real-traffic-01", 1, 1000, "loaded"]]
    assert recent_runs()["run_id"].tolist() == [5, 4, 3, 2, 1]
    assert quarantined_files()[["run_id", "file_key"]].values.tolist() == [[5, "raw/broken/missing-dst-port.csv"]]

# tests/unit/test_app_storage.py
def test_read_text(bucket, monkeypatch, settings_env, capsys):
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    bucket.put_text("quarantine/broken/missing-dst-port/report.md", "# Report", "text/markdown")
    assert read_text("quarantine/broken/missing-dst-port/report.md") == "# Report"
    assert read_text("quarantine/nothing.md") is None and '"event": "s3_read_failed"' in capsys.readouterr().out

def test_no_bucket(settings_env):
    assert has_bucket() is False and read_text("any") is None

# tests/app/test_pipeline_page.py, beside the tile tests; PAGE = "views/pipeline.py"
DRAFT = "quarantine/broken/missing-dst-port/draft-contract.yaml"

@pytest.mark.db
def test_pipeline_tables_and_quarantine_without_bucket(run_app):
    at = run_app(PAGE)
    datasets, runs = (d.value for d in at.dataframe)
    assert datasets["Status"].tolist() == ["✅ Loaded", "⚠️ Quarantined", "✅ Loaded"]
    assert runs["Run"].tolist() == ["#5", "#4", "#3", "#2", "#1"]
    assert runs["Duration"].str.fullmatch(r"\d+:\d{2}").all()
    assert "missing-dst-port.csv" in at.warning[0].value and "run #5" in at.warning[0].value
    assert not [b for b in at.button if b.label == "View report"]
    assert "Once a contract for this file is merged and deployed, the deployment loads the file." in captions(at)

@pytest.mark.db
def test_pipeline_quarantine_with_bucket(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    bucket.put_text(DRAFT, "name: broken\n", "application/yaml")
    at = run_app(PAGE)
    assert [b.label for b in at.button].count("View report") == 1
    assert at.get("download_button")[-1].label == "Download draft contract"

@pytest.mark.db
def test_pipeline_quarantine_draft_missing(run_app, bucket, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "cicnids-test")
    assert "The draft contract could not be read." in captions(run_app(PAGE))
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement the queries and `storage.py`.** `read_text` wraps `pipeline.storage.Bucket(get_settings().s3_bucket)`.

- [ ] **Step 4: Implement the page.** Under the four tiles: card "Datasets" (`One row per source; a contract maps each source to the canonical fields`): Dataset `{display name} ({files} file[s])`, Contract `{name} v{version}` or "no match", Rows (`compact`), Last run (`stamp_label`), Status (badge). Card "Recent ingestion runs" (`Newest first`): Run `#{id}`, File (`basename`), Started, Duration (`mmss`, "—" while running), Loaded, Rejected (thousands separators), Status. Card "Quarantined files" (`Files that did not match any data contract`, `csv=False`): per row `st.warning("**{basename}** · run #{run_id}\n\n{message}")`; with a bucket, the "View report" button opens `@st.dialog("Quarantine report")` showing the report as Markdown, or `st.warning("The report could not be read.")`; "Download draft contract" (`st.download_button`, `file_name="draft-contract.yaml"`) when the draft reads, else the caption "The draft contract could not be read."; then the caption "Once a contract for this file is merged and deployed, the deployment loads the file." With nothing quarantined: `st.info("No file is quarantined.")`. The page still ignores the filters, and its tables take no row selection (design section 5.4 leaves the jump to the Overview optional; it is left out).

- [ ] **Step 5: Run the tests and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 6: Commit** — `Show datasets, runs and quarantined files on the Pipeline page`.

### Task 13: Ship pull request 5 — Pipeline

Title `M3: the rest of the Pipeline page`; IDs UI-07, UI-11.

- [ ] **Step 1–6.** Look for: in staging, the baseline's ten files under one dataset and the last 20 runs; if staging holds a quarantined file, its warning and no `s3_read_failed` in the logs (the task role reads its own bucket).

### Task 14: Data quality page (UI-06)

Branch `feat/m3-data-quality`.

**Files:**
- Modify: `app/data/queries.py`, `app/views/data_quality.py`, `tests/db/test_queries.py`, `tests/app/test_page_states.py`
- Create: `tests/app/test_data_quality_page.py`

**Interfaces:**
- Consumes: `dataset_files` (Task 6), `STEPS` (`pipeline.clean`).
- Produces in `queries.py`:
  - `cleaning_steps(dataset_id: str) -> [step, rows_affected]`, summed over the latest loaded run of each file, in `STEPS` order
  - `column_issues(dataset_id: str) -> [column_name, nulls, infinite, action]`, summed per column over the same runs; `constant, hidden` only when every one of them says so, else `infinite set to null` when any does, else `kept as null`; ordered by nulls plus infinite descending, then name

- [ ] **Step 1: Write the failing query tests**

```python
@pytest.mark.db
def test_quality_queries(use_seeded_db):
    assert cleaning_steps("cse-cic-ids2018").values.tolist() == [["duplicates_removed", 100],
        ["infinite_set_to_null", 20], ["missing_kept_as_null", 7], ["repeated_headers_dropped", 1], ["labels_trimmed", 0]]
    assert column_issues("cse-cic-ids2018").values.tolist() == [
        ["flow_bytes_per_s", 7, 20, "infinite set to null"], ["bwd_psh_flags", 0, 0, "constant, hidden"]]
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement the queries.**

- [ ] **Step 4: Write the failing page tests**

```python
# tests/app/test_data_quality_page.py — PAGE = "views/data_quality.py"; every test is @pytest.mark.db
def test_data_quality_labelled(run_app):
    at = run_app(PAGE)
    assert tiles(at) == {"Rows read": "7.3 k", "Rows rejected": "45", "Duplicates removed": "100",
                         "Infinite values replaced": "20"}
    assert {"2 files", "0 quarantined files", "1.4 % of rows read", "1 column"} <= set(captions(at))
    assert at.caption[0].value.endswith("· ingestion runs #1 to #3 · uses only the Dataset filter")
    assert at.warning[0].value == ("1 column holds one value in every row and is hidden from the "
                                   "Feature explorer: bwd_psh_flags.")
    assert at.dataframe[-1].value["Columns"].tolist() == ["15", "15"]

def test_data_quality_ignores_dates_and_categories(run_app):
    assert tiles(run_app(PAGE, {"filter_categories": ["DDoS"]}))["Rows read"] == "7.3 k"

def test_data_quality_unlabelled(run_app):
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert at.dataframe[-1].value["Columns"].tolist() == ["10 (2 new, kept)"]
```

Append `"data_quality"` to `PAGES`.

- [ ] **Step 5: Run them to see them fail.** Expected: FAIL.

- [ ] **Step 6: Implement the page.** Caption `What the cleaning step changed in {display name} · ingestion runs #{lowest} to #{highest} · uses only the Dataset filter`. Tiles: Rows read (`{n} files`), Rows rejected (`{n} quarantined files`, from `dataset_files` statuses), Duplicates removed (`{percent} of rows read`), Infinite values replaced (`{n} column[s]`, the columns with infinite values). Card "Rows changed by each cleaning step" (`Log scale`): `bars` in `PRIMARY`, log axis, with these labels: `duplicates_removed` "Duplicate rows removed", `infinite_set_to_null` "Infinite values set to null", `missing_kept_as_null` "Missing values kept as null", `repeated_headers_dropped` "Repeated headers dropped", `labels_trimmed` "Label values trimmed". Card "Columns needing attention" (`Before cleaning, all {n} files`). The constant-column `st.warning` in the singular or plural form, names joined by ", ". Card "Files in this dataset" (`Latest run of each file`): File (`basename`), Rows (`rows_read`, thousands separators), Columns (`len(source_columns)`, plus ` ({n} new, kept)` when the run reported new columns; ingestion does not store known extras per run), Status (badge).

- [ ] **Step 7: Run the tests and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 8: Commit** — `Build the Data quality page`.

### Task 15: Ship pull request 6 — Data quality

Title `M3: Data quality page`; IDs UI-06, UI-11.

- [ ] **Step 1–6.** Look for: in staging, the baseline's duplicate and infinite counts, and the constant-column warning.

### Task 16: Feature explorer page (UI-05), and the end of the placeholders

Branch `feat/m3-feature-explorer`.

**Files:**
- Modify: `app/data/fields.py`, `app/data/queries.py`, `app/views/feature_explorer.py`, `app/components/layout.py`, `tests/db/test_queries.py`, `tests/app/test_page_states.py`
- Create: `tests/app/test_feature_explorer_page.py`

**Interfaces:**
- Consumes: `column_issues` (Task 14), `flows_by_category` and `kpi_totals` (Task 6), `box_from_stats`, `histogram_from_bins`, `with_unit`.
- Produces in `fields.py`: `NUMERIC_FIELDS: dict[str, tuple[str, str]]` = flow_duration_us ("Flow duration", "µs"), fwd_packets ("Forward packets", "pkt"), bwd_packets ("Backward packets", "pkt"), fwd_bytes ("Forward bytes", "B"), bwd_bytes ("Backward bytes", "B"), flow_bytes_per_s ("Bytes per second", "B/s"), flow_packets_per_s ("Packets per second", "pkt/s").
- Produces in `queries.py`:
  - `numeric_extras(f) -> [field]`: extras of the dataset whose sampled values are JSON numbers, less the columns `column_issues` marks constant, by name
  - `field_stats(f, field: str, positive_only: bool) -> [attack_category, samples, p5, q1, median, q3, p95, mean]` from `flow_sample`, in `ATTACK_CATEGORIES` order (one row with a None category without a label)
  - `field_histogram(f, field: str, log: bool, bins: int = 30) -> [attack_category, bin_start, bin_end, samples]`; log bins are evenly spaced in log10 over values above 0
  - both raise `ValueError("unknown field ...")` before running SQL unless `field` is in `NUMERIC_FIELDS` and in `f.fields` (used as a column) or in `f.extra_fields` (used as `(extras ->> :field)::double precision`, with `jsonb_typeof(extras -> :field) = 'number'`)
- Removes `coming_soon` from `layout.py`.

- [ ] **Step 1: Write the failing query tests**

```python
@pytest.mark.db
def test_field_stats(filters_for):
    stats = field_stats(filters_for(), "flow_duration_us", positive_only=False).set_index("attack_category")
    assert stats.loc["Benign", ["samples", "median", "mean"]].tolist() == [5, 30000, 30000]
    assert stats.index.tolist() == list(ATTACK_CATEGORIES)

@pytest.mark.db
def test_field_stats_positive_only(filters_for):                 # Review Focus 3
    def median(positive):
        return field_stats(filters_for(), "bwd_packets", positive).set_index("attack_category").loc["Benign", "median"]
    assert (median(False), median(True)) == (1.0, 2.0)

@pytest.mark.db
def test_text_extras_not_offered(filters_for):                   # Review Focus 5
    assert numeric_extras(filters_for())["field"].tolist() == ["fwd_pkt_len_max"]   # bwd_psh_flags is constant
    assert numeric_extras(filters_for(UNLABELLED))["field"].tolist() == ["pkt_entropy"]
    assert field_stats(filters_for(UNLABELLED), "pkt_entropy", False)["median"].tolist() == [3.0]

@pytest.mark.db
def test_unknown_field_rejected(filters_for):                    # Review Focus 5
    for field in ("flow_duration_us; DROP TABLE datasets", "geo_country_x", "label"):
        with pytest.raises(ValueError, match="unknown field"):
            field_stats(filters_for(), field, False)

@pytest.mark.db
def test_field_histogram(filters_for):
    bins = field_histogram(filters_for(), "flow_duration_us", log=True)
    assert bins.groupby("attack_category")["samples"].sum().eq(5).all()
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement the fields and the queries.**

- [ ] **Step 4: Write the failing page tests**

```python
# tests/app/test_feature_explorer_page.py — PAGE = "views/feature_explorer.py"; every test is @pytest.mark.db
def test_feature_explorer_labelled(run_app):
    at = run_app(PAGE)
    options = at.selectbox(key="fx_field").options
    assert "Flow duration (µs)" in options and "fwd_pkt_len_max" in options and "bwd_psh_flags" not in options
    assert at.info[0].value == "Fields kept as extras: bwd_psh_flags, fwd_pkt_len_max."
    summary = at.dataframe[0].value
    assert summary["Category"].tolist() == list(ATTACK_CATEGORIES) and summary["Median"].iloc[0] == "30 ms"

def test_log_scale_caption_mentions_left_out_values(run_app):    # Review Focus 3
    at = run_app(PAGE)
    assert any("values of 0 or less left out" in c for c in captions(at))
    at.toggle(key="fx_log").set_value(False).run()
    assert not any("left out" in c for c in captions(at))

def test_histogram_and_unlabelled(run_app):
    at = run_app(PAGE)
    at.selectbox(key="fx_chart").select("Histogram").run()
    assert not at.exception and len(at.get("plotly_chart")) == 1
    at = run_app(PAGE, {"filter_dataset": "simulated-real-traffic-01"})
    assert "pkt_entropy" in at.selectbox(key="fx_field").options
    assert "geo_country" not in at.selectbox(key="fx_field").options
    assert at.dataframe[0].value["Category"].tolist() == ["All traffic"]
```

Append `"feature_explorer"` to `PAGES`.

- [ ] **Step 5: Run them to see them fail.** Expected: FAIL.

- [ ] **Step 6: Implement the page and drop `coming_soon`.** Caption "Compare any numeric field across attack categories", or "Compare any numeric field across all traffic". Controls in `st.columns(3)`: Field (`key="fx_field"`; the canonical fields of `NUMERIC_FIELDS` the dataset has, shown as `{label} ({unit})`, then `numeric_extras` by name), Chart (`key="fx_chart"`, "Box plot" or "Histogram"), Log scale (`st.toggle`, `key="fx_log"`, on). `st.info("Fields kept as extras: {names}.")` when the dataset has extras. Card "{label} by category", or "{label} across all traffic" (`needs=(field,)`): the box plot from `field_stats(f, field, positive_only=log)` with the caption `Log scale · box = 25th to 75th percentile, white line = median, whiskers = 5th to 95th percentile · values of 0 or less left out`, or without the first and last parts when the scale is linear; the histogram from `field_histogram` with `Log scale · log-spaced bins · values of 0 or less left out`, or `Linear bins`. Card "Summary statistics" (`{label} per category`): Category ("All traffic" without a label), Flows (`flows_by_category`, or `kpi_totals` flows without a label), Median, 95th percentile and Mean through `with_unit`, from `field_stats(f, field, positive_only=False)`. Delete `coming_soon` and its test, since no view calls it any more.

- [ ] **Step 7: Run the whole suite and the linters.** Expected: PASS; ruff clean.

- [ ] **Step 8: Commit** — `Build the Feature explorer page and retire the placeholders`.

### Task 17: Ship pull request 7 and close the milestone

Title `M3: Feature explorer page`; IDs UI-05, UI-08, UI-11.

- [ ] **Step 1: README.** Status line: "Milestone 3 (dashboard pages) is live: all six pages read real data in the Material theme." Commit on the branch: `Mark milestone 3 live in the README`.
- [ ] **Step 2–7: Ship** (steps 1 to 6 of "Shipping a pull request"). Look for: in staging, the baseline's flow durations by category on a log axis; with the simulated dataset, `pkt_entropy` in the field list.
- [ ] **Step 8: Page speed (NFR-01).** In staging, open each of the six pages twice with headless Edge, then `aws logs filter-log-events --log-group-name /cicnids/staging --filter-pattern '{ $.event = "page_render" }' --start-time <ms>`. Expected: every `duration_ms` under 3,000. Record the numbers in the ledger; if a page is slower, tell the user which one and by how much instead of closing the milestone.
- [ ] **Step 9: Close out.** Update the project memory (M3 live, next is build design step 4); report the cost so far from Cost Explorer.
