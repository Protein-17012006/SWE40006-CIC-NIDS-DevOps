# M2 Data Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any CSV that lands in an environment's `raw/` folder is matched to a data contract, cleaned, validated and loaded as aggregates and a sample into PostgreSQL, or quarantined with a readable report and a draft contract; the full CSE-CIC-IDS2018 baseline is loaded into staging and production, and the M1 rollback drill is done on this release.

**Architecture:** The `pipeline` package gains one module per step (contracts, clean, accumulate, storage, draft, load, ingest) and two CLI commands, `ingest --key` and `reconcile`, run as the existing job task. An EventBridge rule in each environment stack starts the job task on every Object Created event under `raw/`. A file is read in 100,000-row text chunks, so memory stays bounded for the 4 GB day file; only aggregates, quality counts and a stratified sample reach RDS, while cleaned rows go to S3 as Parquet.

**Tech Stack:** M1's stack plus pandera, pyarrow, boto3, PyYAML and pydantic; moto for S3 in tests; EventBridge to ECS RunTask.

**Spec:** `docs/design/2026-10-31-build-design.md` sections 5, 6 and 10 step 2, on top of the Design and Requirements Report (sections 2.1 and 4) and the requirements document (ING-01 to ING-09). M1's plan `docs/plans/2026-10-31-m1-walking-skeleton.md` and its ledger record what already exists.

## Global Constraints

- Every M1 global constraint still holds (Python 3.12 venv at `C:\Users\huyho\.venvs\cicnids`, `==` pins, JSON log lines without secrets, names, region us-east-1, tags `Project=cic-nids`, LF endings, the commit trailer).
- Work on branch `feat/m2-ingestion`; main is protected, so the code reaches main through one pull request with green CI (Task 13).
- Every AWS command from the laptop runs with `AWS_PROFILE=hoang` (account 551169294418). Before the first write of a session, `aws sts get-caller-identity` must show that account. Never use the default profile.
- Only canonical field names (report section 4.1) appear outside `contracts/`, the ingestion modules and tests. Extra columns are stored under their normalised names, never their source spelling.
- Chunk size 100,000 rows; sample 2,000 rows per attack category and capture day; top 50 ports per day, category and protocol, the rest summed under `dst_port = -1`; a file with more than 20% rejected rows is quarantined; duplicates are exact rows within one file.
- S3 layout: `raw/<dataset>/<file>.csv` or `raw/<file>.csv` (never edited); `processed/<dataset>/<file>/part-NNNN.parquet`; `quarantine/<dataset>/<file>/report.md` and `draft-contract.yaml`.
- Status values: `datasets.status` is `loaded` or `quarantined`; `ingestion_runs.status` is `running`, `loaded`, `quarantined` or `failed`.
- Quality step names, exactly: `duplicates_removed`, `infinite_set_to_null`, `missing_kept_as_null`, `repeated_headers_dropped`, `labels_trimmed`. Column actions, exactly: `constant, hidden`, `infinite set to null`, `kept as null`.
- Migrations only add (expand, then contract later), so a rollback to an older image keeps working against the newer schema.
- `contracts/` holds only `cse-cic-ids2018.yaml` until the demo: acceptance checklist items 2 to 5 merge the simulated contract live. The finished simulated contract lives in `tests/fixtures/contracts/` for tests and the development rehearsal.
- Ledger: `.superpowers/sdd/2026-10-31-m2-data-ingestion/progress.md` (git-ignored), same format as M1's.
- Test command: `TEST_ADMIN_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres C:\Users\huyho\.venvs\cicnids\Scripts\python.exe -m pytest` with `docker compose up -d db` running (start Docker Desktop first). CI keeps `--cov=pipeline --cov-fail-under=80`.

## Review Focus

1. **Baseline quirks.** The real day files contain repeated header rows mid-file, `Infinity` and `NaN` strings in numeric columns, and occasional out-of-range values. The file still loads: header rows are dropped, infinities become null, bad rows are rejected and counted. Pinned by Task 4 (`test_repeated_header_rows_are_dropped`, `test_infinite_values_become_null`, `test_invalid_rows_rejected`).
2. **Label strings the contract does not know** (stray whitespace, a typo, a new attack). Whitespace is trimmed and the label still maps; unknown labels are rejected, counted and named in the run message; when they push rejections over 20%, the file is quarantined and the report lists them. Pinned by Task 4 (`test_unknown_labels_rejected_and_counted`) and Task 9 (`test_ingest_mostly_unknown_labels_quarantined`).
3. **The same file ingested twice.** EventBridge delivers at least once, people re-upload under the same key, and reconcile re-ingests. The second run replaces that file's rows and Parquet parts; totals do not double. Pinned by Task 6 (`test_loading_same_file_twice_replaces_rows`) and Task 9 (`test_ingest_twice_replaces_rows`, `test_reingest_deletes_stale_parts`).
4. **Odd object keys.** EventBridge may deliver keys with spaces as `+` or `%20`, people upload `My Capture.CSV`, and folder markers or `.txt` files land in `raw/`. Keys resolve to the real object; non-CSV keys are skipped without a run. Pinned by Task 7 (`test_resolve_key_decodes_event_keys`, `test_parse_raw_key_ignores_non_csv_and_outside_raw`), Task 9 (`test_ingest_skips_non_csv_key`) and live in Task 13 step 4 (a key with a space).
5. **Reconcile re-ingesting on every deployment.** A file quarantined for too many rejections under an unchanged contract, a file loaded by a contract that a later image no longer has (development back on main after the rehearsal), and a raw object deleted by hand are all skipped. Pinned by Task 10 (`test_reconcile_skips_quarantine_with_same_contract`, `test_reconcile_skips_when_contract_is_gone`, `test_reconcile_skips_missing_raw_object`).

---

### Task 1: Dependencies, canonical fields and the contract model

**Files:**
- Modify: `requirements.txt`, `requirements-dev.txt`
- Create: `app/data/fields.py`, `pipeline/contracts.py`, `tests/unit/test_contract_model.py` (not `test_contracts.py`: the test folders have no `__init__.py`, so a second file of that name in `tests/contracts/` would clash)

**Interfaces:**
- Produces: `app.data.fields.Field(name: str, kind: Literal["datetime", "integer", "float", "text"], required: bool)` (frozen dataclass); `CANONICAL_FIELDS: tuple[Field, ...]` in report 4.1 order: timestamp (datetime), dst_port, protocol (integer, required), flow_duration_us (float, required), fwd_packets, bwd_packets (integer, required), fwd_bytes, bwd_bytes (float, required), flow_bytes_per_s, flow_packets_per_s (float), src_ip, dst_ip, label (text); `FIELD_NAMES: frozenset[str]`; `REQUIRED_FIELDS: frozenset[str]`; `ATTACK_CATEGORIES = ("Benign", "DoS", "DDoS", "Brute force", "Web attack", "Botnet", "Infiltration")`.
- Produces in `pipeline/contracts.py`: `normalise(column: str) -> str`; `normalise_header(columns: Sequence[str]) -> list[str]` (repeats get `_2`, `_3`); `ContractError(ValueError)`; pydantic `FieldSource(column: str, scale: float = 1.0)`; pydantic `Contract(name: str, version: int, timestamp_format: str | None = None, fields: dict[str, FieldSource], known_extras: list[str] = [], label_map: dict[str, str] = {})` where a field value in YAML is either a column name or `{column, scale}`, with property `has_label: bool`; `CONTRACTS_DIR = <repo>/contracts`; `load_contracts(directory: Path = CONTRACTS_DIR) -> list[Contract]` (sorted by name); frozen dataclass `Match(contract: Contract, mapping: dict[str, str], extras: list[str], new_columns: list[str])` (mapping is canonical field to normalised column; extras and new_columns are normalised names in header order); `match_contract(header: Sequence[str], contracts: Sequence[Contract]) -> Match | None`; `missing_fields(header: Sequence[str], contract: Contract) -> list[str]` (canonical order); `closest_contract(header: Sequence[str], contracts: Sequence[Contract]) -> Contract | None` (fewest missing required fields, ties by name).

- [ ] **Step 1: Pin the new dependencies.** Look up the latest releases with `python -m pip index versions <name>`. `requirements.txt` adds `pandera`, `pyarrow`, `boto3`, `pyyaml`, `pydantic`; `requirements-dev.txt` adds `moto[s3]`. Install both files. Expected: `python -c "import pandera.pandas, pyarrow, boto3, yaml, pydantic, moto"` exits 0. If the latest pandera does not support pandas 3.1, pin pandas to the newest version it supports and record the ruling in the ledger.

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_contract_model.py
def test_normalise():
    assert normalise(" Flow Byts/s ") == "flow_byts_s"
    assert normalise("\ufeffDst Port") == "dst_port"
    assert normalise("Down/Up Ratio") == "down_up_ratio"
    assert normalise("Fwd Header Length.1") == "fwd_header_length_1"

def test_normalise_header_numbers_repeats():
    assert normalise_header(["Flow Byts/s", "Flow Byts s", "Label"]) == ["flow_byts_s", "flow_byts_s_2", "label"]

def test_field_source_accepts_name_or_scale():
    c = Contract.model_validate(_contract(flow_duration_us={"column": "Flow Duration (ms)", "scale": 1000}))
    assert c.fields["flow_duration_us"] == FieldSource(column="Flow Duration (ms)", scale=1000)
    assert c.fields["dst_port"].scale == 1.0

def test_contract_rejects_missing_required_field():
    with pytest.raises(ValidationError, match="dst_port"):
        Contract.model_validate(_contract(dst_port=None))      # helper drops None entries

def test_contract_rejects_unknown_field_category_and_todo():
    for bad, word in [(dict(foo="Foo"), "foo"), (dict(label_map={"Worm": "Worm"}), "Worm"),
                      (dict(protocol="TODO"), "TODO")]:
        with pytest.raises(ValidationError, match=word):
            Contract.model_validate(_contract(**bad))

def test_timestamp_needs_format_and_label_needs_map():
    with pytest.raises(ValidationError, match="timestamp_format"):
        Contract.model_validate(_contract(timestamp_format=None))
    with pytest.raises(ValidationError, match="label_map"):
        Contract.model_validate(_contract(label_map={}))

def test_load_contracts_names_the_bad_file(tmp_path):
    (tmp_path / "broken.yaml").write_text("name: other\nversion: 1\n")
    with pytest.raises(ContractError, match="broken.yaml"):
        load_contracts(tmp_path)

def test_match_needs_every_required_field_and_prefers_most_columns():
    small, big = _contract_obj(name="small"), _contract_obj(name="big", known_extras=["Fwd Pkt Len Max"])
    header = HEADER + ["Fwd Pkt Len Max"]
    assert match_contract(header, [small, big]).contract.name == "big"
    assert match_contract([h for h in HEADER if h != "Dst Port"], [small, big]) is None

def test_match_reports_extras_and_new_columns_in_header_order():
    m = match_contract(HEADER + ["Fwd Pkt Len Max", "pkt_entropy", "Geo Country"], [_contract_obj(known_extras=["Fwd Pkt Len Max"])])
    assert m.extras == ["fwd_pkt_len_max", "pkt_entropy", "geo_country"]
    assert m.new_columns == ["pkt_entropy", "geo_country"]

def test_missing_fields_and_closest_contract():
    header = [h for h in HEADER if h not in ("Dst Port", "Tot Fwd Pkts")]
    assert missing_fields(header, _contract_obj()) == ["dst_port", "fwd_packets"]
    assert closest_contract(header, [_contract_obj()]).name == "test"
```

`_contract(**overrides)` builds a valid dict (name `test`, version 1, all thirteen fields with CSE-CIC-IDS2018 column names, a two-entry label map); `HEADER` is its source columns.

- [ ] **Step 3: Run the tests to see them fail.** Run: `python -m pytest tests/unit/test_contract_model.py`. Expected: FAIL, `ModuleNotFoundError: No module named 'pipeline.contracts'`.

- [ ] **Step 4: Implement `app/data/fields.py` and `pipeline/contracts.py`.** `normalise`: strip a BOM and whitespace, lower-case, every run of characters outside `a-z0-9` becomes one `_`, trim `_`. Validators: field keys within `FIELD_NAMES`, every required field present, no value equal to `TODO`, label map values within `ATTACK_CATEGORIES`, `timestamp_format` set exactly when `timestamp` is mapped, `label_map` non-empty exactly when `label` is mapped, `name` matches `^[a-z0-9-]+$` and equals the file stem when loaded. Matching compares normalised names on both sides; the score is mapped fields plus known extras present.

- [ ] **Step 5: Run the tests and linters.** Run: `python -m pytest tests/unit/test_contract_model.py; python -m ruff check .; python -m ruff format --check .`. Expected: all pass, no findings.

- [ ] **Step 6: Commit** — message `Add canonical fields and the data contract model`.

### Task 2: The baseline contract and its sample files

**Files:**
- Create: `contracts/cse-cic-ids2018.yaml`, `tests/contracts/cse-cic-ids2018/wednesday-14-02-2018.csv`, `tests/contracts/cse-cic-ids2018/thuesday-20-02-2018.csv`, `tests/contracts/broken/missing-dst-port.csv`, `tests/contracts/broken/expected.yaml`, `tests/contracts/test_contracts.py`

**Interfaces:**
- Consumes: `load_contracts`, `match_contract`, `missing_fields`, `closest_contract` (Task 1).
- Produces: the contract `cse-cic-ids2018` v1; sample files later tasks ingest; `tests/contracts/broken/expected.yaml` mapping each broken file to `{missing: [canonical fields], closest: <contract name>}`.

- [ ] **Step 1: Cut the samples from the public bucket.** For each of the two day files, `aws s3api get-object --no-sign-request --region us-east-1 --bucket cse-cic-ids2018 --key "Processed Traffic Data for ML Algorithms/<Day>_TrafficForML_CICFlowMeter.csv" --range bytes=0-262143 <scratch>/head.csv`, then keep the header and 200 data rows (`head -n 201`). `missing-dst-port.csv` is the Wednesday sample without the `Dst Port` column. Expected: 80 columns in the Wednesday sample, 84 in the Thuesday sample (Flow ID, Src IP, Src Port, Dst IP first), 79 in the broken one.

- [ ] **Step 2: Write the failing tests**

```python
# tests/contracts/test_contracts.py
@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: f"{p.parent.name}/{p.name}")  # every */*.csv except broken/
def test_sample_matches_its_contract(sample):
    m = match_contract(read_header(sample), load_contracts())
    assert m is not None and m.contract.name == sample.parent.name and m.new_columns == []

@pytest.mark.parametrize("name", sorted(EXPECTED))   # keys of broken/expected.yaml
def test_broken_file_matches_no_contract(name):
    header = read_header(BROKEN / name)
    assert match_contract(header, load_contracts()) is None
    closest = closest_contract(header, load_contracts())
    assert closest.name == EXPECTED[name]["closest"]
    assert missing_fields(header, closest) == EXPECTED[name]["missing"]

def test_every_contract_has_samples():
    for c in load_contracts():
        assert list((HERE / c.name).glob("*.csv")), c.name

def test_baseline_label_map_covers_the_sample_labels():
    labels = {row[-1].strip() for s in SAMPLES for row in csv_rows(s)}
    assert labels <= set(load_contracts()[0].label_map)
```

`read_header` is a three-line helper in the test module (`csv.reader`, first row, BOM stripped); Task 4's `clean.read_header` replaces it. `expected.yaml` starts with `missing-dst-port.csv: {missing: [dst_port], closest: cse-cic-ids2018}`.

- [ ] **Step 3: Run them to see them fail.** Run: `python -m pytest tests/contracts`. Expected: FAIL, no contract named `cse-cic-ids2018` (`load_contracts()` is empty).

- [ ] **Step 4: Write `contracts/cse-cic-ids2018.yaml`.** `timestamp_format: "%d/%m/%Y %H:%M:%S"`. `fields`: timestamp `Timestamp`, dst_port `Dst Port`, protocol `Protocol`, flow_duration_us `Flow Duration`, fwd_packets `Tot Fwd Pkts`, bwd_packets `Tot Bwd Pkts`, fwd_bytes `TotLen Fwd Pkts`, bwd_bytes `TotLen Bwd Pkts`, flow_bytes_per_s `Flow Byts/s`, flow_packets_per_s `Flow Pkts/s`, src_ip `Src IP`, dst_ip `Dst IP`, label `Label`. `known_extras`: every other column of the two headers, 71 names (the 69 shared ones plus `Flow ID` and `Src Port`). `label_map`, all fifteen labels:

```yaml
label_map:
  Benign: Benign
  Bot: Botnet
  Brute Force -Web: Web attack
  Brute Force -XSS: Web attack
  SQL Injection: Web attack
  DDOS attack-HOIC: DDoS
  DDOS attack-LOIC-UDP: DDoS
  DDoS attacks-LOIC-HTTP: DDoS
  DoS attacks-GoldenEye: DoS
  DoS attacks-Hulk: DoS
  DoS attacks-SlowHTTPTest: DoS
  DoS attacks-Slowloris: DoS
  FTP-BruteForce: Brute force
  SSH-Bruteforce: Brute force
  Infilteration: Infiltration
```

- [ ] **Step 5: Run the tests.** Run: `python -m pytest tests/contracts`. Expected: PASS.

- [ ] **Step 6: Commit** — message `Add the CSE-CIC-IDS2018 contract and its sample files`.

### Task 3: The simulated real-traffic generator

**Files:**
- Create: `scripts/__init__.py`, `scripts/make_simulated.py`, `tests/unit/test_make_simulated.py`, `tests/contracts/broken/simulated-real-traffic-01.csv`
- Modify: `tests/contracts/broken/expected.yaml`

**Interfaces:**
- Produces: `make_simulated(source: Path, out: Path, rows: int = 100_000, seed: int = 7) -> int` (rows written; `ValueError` when the source has fewer rows); `RENAMES: dict[str, str]`; command line `python -m scripts.make_simulated SOURCE OUT [--rows N] [--seed S]`.

- [ ] **Step 1: Write the failing tests**

```python
WED = Path("tests/contracts/cse-cic-ids2018/wednesday-14-02-2018.csv")

def test_renames_drops_label_and_adds_two_columns(tmp_path):
    out = tmp_path / "sim.csv"
    assert make_simulated(WED, out, rows=50) == 50
    df = pd.read_csv(out, dtype=str)
    assert len(df) == 50 and "Label" not in [c.strip() for c in df.columns]
    assert {" Destination Port", " Total Fwd Packets", " pkt_entropy", " geo_country"} <= set(df.columns)
    assert df.columns[0] == df.columns[0].lstrip()           # CIC-IDS2017 style: leading spaces after the first

def test_rewrites_timestamps_in_iso_order(tmp_path):
    make_simulated(WED, tmp_path / "sim.csv", rows=50)
    ts = pd.read_csv(tmp_path / "sim.csv", dtype=str)[" Timestamp"]
    assert ts.str.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}").all() and ts.is_monotonic_increasing

def test_is_deterministic_and_refuses_too_many_rows(tmp_path):
    make_simulated(WED, tmp_path / "a.csv", rows=30); make_simulated(WED, tmp_path / "b.csv", rows=30)
    assert (tmp_path / "a.csv").read_bytes() == (tmp_path / "b.csv").read_bytes()
    with pytest.raises(ValueError, match="200"):
        make_simulated(WED, tmp_path / "c.csv", rows=500)
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'scripts.make_simulated'`.

- [ ] **Step 3: Implement `scripts/make_simulated.py`.** `RENAMES`: Dst Port → Destination Port, Tot Fwd Pkts → Total Fwd Packets, Tot Bwd Pkts → Total Backward Packets, TotLen Fwd Pkts → Total Length of Fwd Packets, TotLen Bwd Pkts → Total Length of Bwd Packets, Flow Byts/s → Flow Bytes/s, Flow Pkts/s → Flow Packets/s, Fwd Pkt Len Max → Fwd Packet Length Max, Fwd Pkt Len Min → Fwd Packet Length Min, Bwd Pkt Len Max → Bwd Packet Length Max, Bwd Pkt Len Min → Bwd Packet Length Min, Init Fwd Win Byts → Init_Win_bytes_forward, Init Bwd Win Byts → Init_Win_bytes_backward. Uniform sample of `rows` rows without replacement (`numpy.random.default_rng(seed)`), read in chunks so a 350 MB day file fits; drop `Label`; `pkt_entropy` uniform in [0, 8] with 4 decimals; `geo_country` from `("US", "DE", "FR", "GB", "NL", "VN", "SG", "JP", "BR", "AU")`; timestamps re-written as `%Y-%m-%d %H:%M:%S` and rows sorted by them; every column except the first gets one leading space.

- [ ] **Step 4: Generate the committed 500-row sample.** Download `Friday-16-02-2018_TrafficForML_CICFlowMeter.csv` with `aws s3 cp --no-sign-request` into the session scratchpad (never into the repo), then `python -m scripts.make_simulated <scratch>/friday-16.csv tests/contracts/broken/simulated-real-traffic-01.csv --rows 500`. Add to `expected.yaml`: `simulated-real-traffic-01.csv: {missing: [dst_port, fwd_packets, bwd_packets, fwd_bytes, bwd_bytes], closest: cse-cic-ids2018}`.

- [ ] **Step 5: Run the tests.** Run: `python -m pytest tests/unit/test_make_simulated.py tests/contracts`. Expected: PASS.

- [ ] **Step 6: Commit** — message `Add the simulated real-traffic generator and its sample`.

### Task 4: Reading and cleaning one chunk

**Files:**
- Create: `pipeline/clean.py`, `tests/unit/test_clean.py`
- Modify: `tests/contracts/test_contracts.py` (use `clean.read_header`)

**Interfaces:**
- Consumes: `Contract`, `Match`, `normalise_header` (Task 1); `CANONICAL_FIELDS`, `ATTACK_CATEGORIES`.
- Produces: `CHUNK_ROWS = 100_000`; `STEPS: tuple[str, ...]` (the five step names in Global Constraints); `read_header(path: Path) -> list[str]` (source spelling, BOM stripped); `read_chunks(path: Path, chunk_rows: int = CHUNK_ROWS) -> Iterator[pd.DataFrame]` (every value as text, empty cells as `""`, columns normalised); `infer_extra_kinds(chunk: pd.DataFrame, extras: Sequence[str]) -> dict[str, Literal["numeric", "text"]]` (numeric when every non-empty value of the first chunk parses as a number, `inf` and `nan` included; the decision holds for the rest of the file); `build_schema(contract: Contract) -> pandera.pandas.DataFrameSchema`; dataclass `CleanChunk(frame: pd.DataFrame, rows_in: int, rejected: int, steps: Counter[str], unknown_labels: Counter[str], nulls: Counter[str], infinite: Counter[str])`; `clean_chunk(chunk: pd.DataFrame, match: Match, extra_kinds: Mapping[str, str]) -> CleanChunk`. The output frame holds the mapped canonical fields (integer → `Int64`, float → `Float64`, datetime → `datetime64[ns]`, text → `string`), `attack_category` when the contract has a label, and every extra under its normalised name (numeric → `Float64`, text → `string`).

- [ ] **Step 1: Write the failing tests**

```python
# rows are built from tests/contracts/cse-cic-ids2018/wednesday-14-02-2018.csv with overrides by source name
def test_repeated_header_rows_are_dropped():
    out = clean(rows(3) + [HEADER_ROW])
    assert (len(out.frame), out.rows_in, out.steps["repeated_headers_dropped"]) == (3, 4, 1)

def test_infinite_values_become_null():
    out = clean([row(**{"Flow Byts/s": "Infinity", "Flow Pkts/s": "inf"}), row(**{"Flow Byts/s": "-Infinity"})])
    assert out.frame["flow_bytes_per_s"].isna().all() and out.steps["infinite_set_to_null"] == 2
    assert out.infinite == Counter({"flow_bytes_per_s": 2, "flow_packets_per_s": 1}) and out.rejected == 0

def test_missing_values_are_kept_as_null():
    out = clean([row(**{"Flow Byts/s": "NaN"}), row(**{"Fwd Pkt Len Max": ""}), row()])
    assert out.steps["missing_kept_as_null"] == 2
    assert out.nulls == Counter({"flow_bytes_per_s": 1, "fwd_pkt_len_max": 1})

def test_labels_are_trimmed_and_mapped():
    out = clean([row(Label=" Benign "), row(Label="DDOS attack-HOIC")])
    assert list(out.frame["label"]) == ["Benign", "DDOS attack-HOIC"]
    assert list(out.frame["attack_category"]) == ["Benign", "DDoS"] and out.steps["labels_trimmed"] == 1

def test_unknown_labels_rejected_and_counted():
    out = clean([row(Label="Worm"), row(Label="Worm"), row()])
    assert (out.rejected, out.unknown_labels, len(out.frame)) == (2, Counter({"Worm": 2}), 1)

def test_invalid_rows_rejected():
    out = clean([row(**{"Dst Port": "70000"}), row(Protocol="x"), row(**{"Flow Duration": "-5"}),
                 row(Timestamp="yesterday"), row(**{"Dst Port": "80.5"}), row()])
    assert (out.rejected, len(out.frame)) == (5, 1)

def test_unit_scale_and_timestamp_format():
    out = clean([row(**{"Flow Duration": "2.5"})], contract=scaled(flow_duration_us=1000))
    assert out.frame["flow_duration_us"].iloc[0] == 2500.0
    assert out.frame["timestamp"].iloc[0] == pd.Timestamp("2018-02-14 08:31:01")

def test_extras_keep_normalised_names_and_kinds():
    out = clean([row(), row()], extra_header={"geo_country": "VN"})
    assert out.frame["fwd_pkt_len_max"].dtype == "Float64" and out.frame["geo_country"].dtype == "string"

def test_columns_in_any_order_give_the_same_frame():
    assert_frame_equal(clean(rows(5)).frame, clean(rows(5), shuffle_columns=True).frame, check_like=True)

def test_unlabelled_contract_has_no_category():
    assert "attack_category" not in clean(rows(2), contract=without_label()).frame
```

- [ ] **Step 2: Run them to see them fail.** Run: `python -m pytest tests/unit/test_clean.py`. Expected: `ModuleNotFoundError: No module named 'pipeline.clean'`.

- [ ] **Step 3: Implement `pipeline/clean.py`.** A row is a repeated header when at least half its values, normalised, equal their column's normalised name. Order per chunk: drop repeated headers; trim labels; count infinities (`inf`, `-inf`, `infinity`, `-infinity`, any case) and missing cells (`""`, `nan`, any case) per column and per row; coerce and scale; map labels, marking unknown ones; validate with `build_schema(...).validate(frame, lazy=True)` and drop the indices in `SchemaErrors.failure_cases["index"]`. The schema: dst_port 0 to 65535, protocol 0 to 255, both integral; flow_duration_us, packets and bytes not negative; every required field, plus timestamp and label when mapped, non-null; attack_category within `ATTACK_CATEGORIES`. An unknown label counts once, in `unknown_labels`, and once in `rejected`.

- [ ] **Step 4: Run the tests.** Expected: PASS; `python -m pytest tests/contracts` still passes on `clean.read_header`.

- [ ] **Step 5: Commit** — message `Clean and validate CSV chunks against a contract`.

### Task 5: Duplicates, aggregates, the sample and quality counts

**Files:**
- Create: `pipeline/accumulate.py`, `tests/unit/test_accumulate.py`

**Interfaces:**
- Consumes: `CleanChunk`, `STEPS` (Task 4).
- Produces: `Deduplicator().drop(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]` (64-bit hashes from `pd.util.hash_pandas_object(frame, index=False)` kept in a set; duplicates within and across chunks); `Aggregates(sample_per_group: int = 2000, top_ports: int = 50, seed: int = 0)` with `add(frame)`, `rows: int`, `first_ts`, `last_ts` (`datetime | None`), `hourly() -> DataFrame[hour, label, attack_category, flows]`, `ports() -> DataFrame[day, attack_category, protocol, dst_port, flows]`, `sample() -> DataFrame` (the `flow_sample` columns of migration 0001 except ids and keys, with `ts` from timestamp and `extras` a JSON-safe dict per row); dataclass `ColumnIssue(column_name: str, nulls: int, infinite: int, action: str)`; `Quality()` with `add(chunk: CleanChunk, kept: pd.DataFrame, duplicates: int)`, `steps() -> dict[str, int]` (all five keys, zeros included), `columns() -> list[ColumnIssue]` (only columns with an issue; `constant, hidden` wins over `infinite set to null`, which wins over `kept as null`).

- [ ] **Step 1: Write the failing tests**

```python
def test_dedup_within_and_across_chunks():
    d = Deduplicator()
    a, n1 = d.drop(frame([1, 2, 2])); b, n2 = d.drop(frame([2, 3]))
    assert (len(a), n1, len(b), n2) == (2, 1, 1, 1)

def test_hourly_counts_split_by_label():
    agg = Aggregates(); agg.add(flows(("08:10", "Benign"), ("08:50", "Benign"), ("09:05", "Bot")))
    assert agg.hourly().to_dict("records") == [
        {"hour": T("08:00"), "label": "Benign", "attack_category": "Benign", "flows": 2},
        {"hour": T("09:00"), "label": "Bot", "attack_category": "Botnet", "flows": 1}]
    assert (agg.rows, agg.first_ts, agg.last_ts) == (3, T("08:10"), T("09:05"))

def test_rows_without_timestamp_have_null_hour_and_day():
    agg = Aggregates(); agg.add(flows_without_timestamp(4))
    assert agg.hourly()["hour"].isna().all() and agg.ports()["day"].isna().all()

def test_ports_keep_top_n_and_sum_the_rest():
    agg = Aggregates(top_ports=2); agg.add(ports(80, 80, 80, 80, 80, 443, 443, 443, 22, 21))
    assert sorted(agg.ports()[["dst_port", "flows"]].itertuples(index=False)) == [(-1, 2), (80, 5), (443, 3)]

def test_sample_caps_common_classes_and_keeps_rare_ones_across_chunks():
    agg = Aggregates(sample_per_group=10)
    for _ in range(5): agg.add(flows_of("Benign", 100))
    agg.add(flows_of("Bot", 3))
    assert agg.sample()["attack_category"].value_counts().to_dict() == {"Benign": 10, "Botnet": 3}

def test_sample_is_deterministic_for_a_seed():
    assert_frame_equal(sampled(seed=1), sampled(seed=1))

def test_sample_extras_are_json_safe():
    agg = Aggregates(); agg.add(flows_with_extras({"pkt_entropy": float("nan"), "geo_country": "VN"}))
    json.dumps(agg.sample()["extras"].iloc[0], allow_nan=False)   # no NaN reaches JSONB

def test_quality_steps_and_columns():
    q = Quality(); q.add(chunk_with(infinite={"flow_bytes_per_s": 2}, nulls={"x": 1}), kept=constant_in("bwd_psh_flags"), duplicates=3)
    assert q.steps() == {"duplicates_removed": 3, "infinite_set_to_null": 2, "missing_kept_as_null": 1,
                         "repeated_headers_dropped": 0, "labels_trimmed": 0}
    assert {c.column_name: c.action for c in q.columns()} == {
        "flow_bytes_per_s": "infinite set to null", "x": "kept as null", "bwd_psh_flags": "constant, hidden"}
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'pipeline.accumulate'`.

- [ ] **Step 3: Implement `pipeline/accumulate.py`.** Hourly and port counts accumulate as grouped counts merged per chunk (`groupby(..., dropna=False)`). The sample is bottom-k: each row gets a key from `numpy.random.default_rng(seed)`, and after each chunk only the `sample_per_group` smallest keys per (attack_category, day) survive. Constant columns are found from running per-column minimum and maximum (numeric) or the first value plus a "differs" flag (text); an all-null column is constant.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** — message `Accumulate aggregates, a stratified sample and quality counts`.

### Task 6: Migration 0002 and the database writes

**Files:**
- Create: `migrations/versions/0002_run_time_span.py`, `pipeline/load.py`, `tests/db/test_load.py`
- Modify: `tests/db/test_migrations.py`

**Interfaces:**
- Consumes: `ColumnIssue` (Task 5); the tables of migration 0001; fixtures `migrated_db_url`, `empty_db_url`.
- Produces: revision `0002_run_time_span` (adds nullable `ingestion_runs.first_ts` and `ingestion_runs.last_ts`, `DateTime` without time zone, like `datasets.first_ts`); dataclass `RunRecord(status: str, message: str, contract_name: str | None = None, contract_version: int | None = None, rows_read: int = 0, rows_loaded: int = 0, rows_rejected: int = 0, source_columns: list[str] = [], new_columns: list[str] = [], report_key: str | None = None, draft_contract_key: str | None = None, first_ts: datetime | None = None, last_ts: datetime | None = None)`; dataclass `FileData(hourly: pd.DataFrame, ports: pd.DataFrame, sample: pd.DataFrame, steps: dict[str, int], columns: list[ColumnIssue], fields: list[str], extra_fields: list[str], has_label: bool)`; `start_run(engine, dataset_id: str, file_key: str, commit_sha: str) -> int`; `finish_run(engine, run_id: int, record: RunRecord, data: FileData | None = None) -> None`; dataclass `LatestRun(run_id, dataset_id, file_key, status, contract_name, contract_version, source_columns)`; `latest_runs(engine) -> list[LatestRun]` (newest run per file_key); `mark_stale_runs(engine, older_than: timedelta = timedelta(hours=2)) -> int`; `dataset_summary(engine) -> list[dict[str, object]]` (dataset_id, status, contract, row_count, files); `table_sizes(engine) -> dict[str, int]` (bytes per table, `pg_total_relation_size`).

`finish_run` runs one transaction under `pg_advisory_xact_lock(hashtext(dataset_id))`. With `data` (a loaded run): delete the file's rows from `agg_hourly`, `agg_ports` and `flow_sample`, insert the new ones, insert the run's `quality_steps` and `quality_columns`. In every case: update the run (status, counts, keys, message, `ended_at = now()`). For `loaded` and `quarantined`, upsert the dataset: `row_count` = sum of `agg_hourly.flows`; `status` = `loaded` when the dataset has any aggregate row, else `quarantined`; `first_ts`/`last_ts` = min/max over the latest loaded run per file; `fields` and `extra_fields` = the union of what is stored and this file's; `has_label` = stored or this file's; contract and `loaded_at` from the latest loaded run. A quarantined run never deletes an earlier load of the same file. A failed run touches only its own row.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.db
def test_migration_0002_adds_and_removes_time_span(empty_db_url):
    upgrade(empty_db_url)
    assert {"first_ts", "last_ts"} <= run_columns(empty_db_url)
    downgrade(empty_db_url, "0001_initial_schema")
    assert not {"first_ts", "last_ts"} & run_columns(empty_db_url)

@pytest.mark.db
def test_finish_loaded_inserts_aggregates_and_dataset(engine):
    run = start_run(engine, "d", "raw/d/a.csv", "abc1234")
    finish_run(engine, run, loaded_record(), file_data(flows=7, first="2018-02-14 08:00", last="2018-02-14 10:00"))
    ds = dataset(engine, "d")
    assert (ds.status, ds.row_count, ds.has_label, ds.first_ts.hour, ds.last_ts.hour) == ("loaded", 7, True, 8, 10)
    assert run_row(engine, run).status == "loaded" and quality_steps(engine, run)["duplicates_removed"] == 0

@pytest.mark.db
def test_loading_same_file_twice_replaces_rows(engine):
    for _ in range(2):
        finish_run(engine, start_run(engine, "d", "raw/d/a.csv", "abc1234"), loaded_record(), file_data(flows=7))
    assert (dataset(engine, "d").row_count, count(engine, "flow_sample"), count(engine, "ingestion_runs")) == (7, SAMPLE_ROWS, 2)

@pytest.mark.db
def test_two_files_add_up(engine): ...          # row_count 7 + 5; first_ts is the earlier file's, last_ts the later's

@pytest.mark.db
def test_quarantine_keeps_an_earlier_load(engine): ...   # loaded, then quarantined: aggregates stay, status loaded

@pytest.mark.db
def test_quarantine_of_a_new_dataset(engine): ...        # status quarantined, contract_name None, row_count 0

@pytest.mark.db
def test_latest_runs_and_stale_runs(engine): ...         # one LatestRun per file; a running run started 3 h ago becomes failed with "stopped before"
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL (`No module named 'pipeline.load'`; the migration test fails on missing columns).

- [ ] **Step 3: Implement the migration and `pipeline/load.py`.** Use lightweight `sa.table()` constructs and executemany inserts; `extras` goes in as JSONB.

- [ ] **Step 4: Run the db tests.** Run: `python -m pytest tests/db`. Expected: PASS, including M1's `test_upgrade_twice_is_a_no_op`.

- [ ] **Step 5: Commit** — message `Record runs and load a file's aggregates in one locked transaction`.

### Task 7: S3 keys and the bucket

**Files:**
- Create: `pipeline/storage.py`, `tests/unit/test_storage.py`
- Modify: `tests/conftest.py` (fixture `bucket`)

**Interfaces:**
- Produces: frozen dataclass `RawFile(key: str, dataset_id: str, name: str)` with properties `processed_prefix` (`processed/<dataset_id>/<name>/`), `report_key` (`quarantine/<dataset_id>/<name>/report.md`), `draft_key` (`quarantine/<dataset_id>/<name>/draft-contract.yaml`); `parse_raw_key(key: str) -> RawFile | None` (None outside `raw/`, for folder markers and for anything not ending in `.csv`, any case; `dataset_id` is the first folder under `raw/`, or the file stem for a file directly in `raw/`, lower-cased with every run of characters outside `a-z0-9` turned into `-`; `name` is the rest of the path without `.csv`); `class Bucket(name: str, client: S3Client | None = None)` with `exists(key) -> bool`, `resolve_key(key) -> str` (the key itself, else `urllib.parse.unquote_plus(key)`, else `FileNotFoundError`), `download(key, path)`, `upload(path, key)`, `put_text(key, text, content_type)`, `delete_prefix(prefix) -> int`. Fixture `bucket` in `tests/conftest.py`: dummy AWS credentials via monkeypatch, `moto.mock_aws`, bucket `cicnids-test` in us-east-1, yields a `Bucket`.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_raw_key_dataset_folder():
    f = parse_raw_key("raw/cse-cic-ids2018/Wednesday-14-02-2018.csv")
    assert (f.dataset_id, f.name) == ("cse-cic-ids2018", "Wednesday-14-02-2018")
    assert f.processed_prefix == "processed/cse-cic-ids2018/Wednesday-14-02-2018/"
    assert f.draft_key == "quarantine/cse-cic-ids2018/Wednesday-14-02-2018/draft-contract.yaml"

def test_parse_raw_key_file_directly_in_raw_and_odd_names():
    assert parse_raw_key("raw/simulated-real-traffic-01.csv").dataset_id == "simulated-real-traffic-01"
    f = parse_raw_key("raw/My Capture/day 1.CSV")
    assert (f.dataset_id, f.name) == ("my-capture", "day 1")

def test_parse_raw_key_ignores_non_csv_and_outside_raw():
    assert [parse_raw_key(k) for k in ("raw/readme.txt", "processed/x.csv", "raw/folder/", "raw/")] == [None] * 4

def test_resolve_key_decodes_event_keys(bucket):
    bucket.put_text("raw/my capture.csv", "a\n", "text/csv")
    assert bucket.resolve_key("raw/my capture.csv") == "raw/my capture.csv"
    assert bucket.resolve_key("raw/my+capture.csv") == "raw/my capture.csv"
    assert bucket.resolve_key("raw/my%20capture.csv") == "raw/my capture.csv"
    with pytest.raises(FileNotFoundError):
        bucket.resolve_key("raw/other.csv")

def test_delete_prefix_removes_only_that_prefix(bucket):
    for k in ("processed/d/a/part-0000.parquet", "processed/d/a/part-0001.parquet", "processed/d/ab/part-0000.parquet"):
        bucket.put_text(k, "x", "application/octet-stream")
    assert bucket.delete_prefix("processed/d/a/") == 2 and bucket.exists("processed/d/ab/part-0000.parquet")
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'pipeline.storage'`.

- [ ] **Step 3: Implement `pipeline/storage.py`.** `client` defaults to `boto3.client("s3", region_name=get_settings().aws_region)`; downloads use `download_file` (multipart, so the 4 GB file streams to disk).

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** — message `Parse raw keys and wrap the environment bucket`.

### Task 8: Draft contracts and quarantine reports

**Files:**
- Create: `pipeline/draft.py`, `tests/unit/test_draft.py`, `tests/fixtures/contracts/simulated-real-traffic.yaml`

**Interfaces:**
- Consumes: `Contract`, `normalise`, `missing_fields`, `closest_contract` (Task 1); `RawFile` (Task 7).
- Produces: `SYNONYMS: dict[str, tuple[str, ...]]`; `TIMESTAMP_FORMATS = ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%d/%m/%Y %I:%M:%S %p")`; `propose_mapping(header: Sequence[str], contracts: Sequence[Contract]) -> dict[str, str | None]` (canonical field to the header's own spelling); `guess_timestamp_format(values: Sequence[str]) -> str | None` (the first format that parses every value); `draft_contract(dataset_id: str, header: Sequence[str], contracts: Sequence[Contract], first_chunk: pd.DataFrame) -> str` (YAML text); `quarantine_report(raw: RawFile, run_id: int, reason: str, header: Sequence[str], contracts: Sequence[Contract], unknown_labels: Mapping[str, int] | None = None) -> str` (Markdown).

Mapping order per canonical field: an exact normalised match against the field's own name or any contract's source column for it; then `SYNONYMS`; then the best `difflib.SequenceMatcher` ratio of at least 0.8 over the same candidates, each header column used once. `SYNONYMS` (CICFlowMeter and CIC-IDS2017 spellings): timestamp (Timestamp), dst_port (Destination Port, Dst Port, DstPort), protocol (Protocol, Proto), flow_duration_us (Flow Duration), fwd_packets (Total Fwd Packets, Tot Fwd Pkts), bwd_packets (Total Backward Packets, Tot Bwd Pkts), fwd_bytes (Total Length of Fwd Packets, TotLen Fwd Pkts), bwd_bytes (Total Length of Bwd Packets, TotLen Bwd Pkts), flow_bytes_per_s (Flow Bytes/s, Flow Byts/s), flow_packets_per_s (Flow Packets/s, Flow Pkts/s), src_ip (Source IP, Src IP), dst_ip (Destination IP, Dst IP), label (Label).

The draft: `name` = dataset_id without a trailing `-<digits>`; `version: 1`; `timestamp_format` guessed from the first chunk; unmapped fields as `TODO`; `known_extras` = every other column; `label_map` (only when label is mapped) = each distinct label of the first chunk with its category from any contract's map, else `TODO`. A header comment says to save it as `contracts/<name>.yaml` and open a pull request. The report holds the run number, the reason, each missing required field with the column the closest contract expects (`dst_port: expected "Dst Port" (cse-cic-ids2018 v1)`), the columns no contract knows, unknown labels with counts when given, and the next steps.

- [ ] **Step 1: Write the failing tests**

```python
SIM = Path("tests/contracts/broken/simulated-real-traffic-01.csv")

def test_propose_mapping_for_the_simulated_file():
    m = propose_mapping(read_header(SIM), load_contracts())
    assert m["dst_port"] == " Destination Port" and m["fwd_bytes"] == " Total Length of Fwd Packets"
    assert all(m[f] for f in REQUIRED_FIELDS) and m["label"] is None

def test_similarity_fallback_and_todo():
    m = propose_mapping(["Dest Port", "Protocol", "Weird"], load_contracts())
    assert m["dst_port"] == "Dest Port" and m["fwd_packets"] is None

def test_draft_for_the_simulated_file_is_a_valid_contract():
    text = draft_contract("simulated-real-traffic-01", read_header(SIM), load_contracts(), first_chunk(SIM))
    c = Contract.model_validate(yaml.safe_load(text))
    assert (c.name, c.timestamp_format, c.has_label) == ("simulated-real-traffic", "%Y-%m-%d %H:%M:%S", False)
    assert match_contract(read_header(SIM), [c]).new_columns == []

def test_draft_with_unmapped_fields_is_rejected_until_edited():
    text = draft_contract("x", ["Protocol", "Flow Duration"], load_contracts(), pd.DataFrame())
    assert "dst_port: TODO" in text
    with pytest.raises(ValidationError, match="TODO"):
        Contract.model_validate(yaml.safe_load(text))

def test_report_names_the_missing_field_and_its_expected_column():
    raw = parse_raw_key("raw/broken/missing-dst-port.csv")
    text = quarantine_report(raw, 12, "No contract matches", read_header(BROKEN / "missing-dst-port.csv"), load_contracts())
    assert "#12" in text and 'dst_port: expected "Dst Port" (cse-cic-ids2018 v1)' in text

def test_report_lists_unknown_labels():
    raw = parse_raw_key("raw/cse-cic-ids2018/odd-day.csv")
    text = quarantine_report(raw, 3, "reason", HEADER, load_contracts(), unknown_labels={"Worm": 40})
    assert "Worm" in text and "40" in text
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'pipeline.draft'`.

- [ ] **Step 3: Implement `pipeline/draft.py`.**

- [ ] **Step 4: Save the finished simulated contract.** Write the draft for the simulated sample to `tests/fixtures/contracts/simulated-real-traffic.yaml` (it validates as it is, because every required field maps). It is the contract the demo merges into `contracts/`; it must not go there now.

- [ ] **Step 5: Run the tests.** Expected: PASS.

- [ ] **Step 6: Commit** — message `Draft contracts and quarantine reports for unmatched files`.

### Task 9: Ingest one file, and the `ingest` command

**Files:**
- Create: `pipeline/ingest.py`, `tests/db/test_ingest.py`
- Modify: `pipeline/cli.py`, `tests/unit/test_cli.py`, `Dockerfile`

**Interfaces:**
- Consumes: Tasks 1 to 8.
- Produces: `REJECT_THRESHOLD = 0.20`; `ingest_file(key: str, *, engine: sa.Engine, bucket: Bucket, contracts: Sequence[Contract], commit_sha: str, workdir: Path, chunk_rows: int = CHUNK_ROWS) -> RunRecord | None` (None when `parse_raw_key` rejects the key; it then logs `ingest_skipped` and records no run). Every run logs one `ingestion_run` event with `run_id`, `dataset_id`, `file_key`, `contract` (`"<name> v<version>"` or null), `status`, `rows_read`, `rows_loaded`, `rows_rejected`, `new_columns` (a count) and `duration_s`. An exception marks the run `failed` with message `Failed: <type>: <first line>`, logs the event at ERROR, and re-raises. CLI: each command takes the parsed `argparse.Namespace`; `ingest --key KEY` (required) prints the run's message; quarantined and skipped runs exit 0, failures exit 1.

Flow: resolve the key; parse it; start the run (`source_columns` = the header as written, BOM stripped); download into `workdir`; match. No match → put the report and draft, finish as quarantined (`No contract matches: missing <fields> (closest: <name> v<version>).`). Otherwise stream the chunks (extra kinds decided on the first), clean, drop duplicates, feed `Aggregates` (seed from `zlib.crc32` of the key, so a re-ingest draws the same sample) and `Quality`, and write each non-empty cleaned chunk to `workdir/part-NNNN.parquet`. Zero data rows → quarantined, `The file has no data rows.` More than 20% rejected → report (with unknown labels) and draft, quarantined, `<pct>% of rows failed validation with <name> v<version>.` with one decimal. Otherwise delete the old `processed_prefix`, upload the parts, finish as loaded: `Loaded <n> of <m> rows with <name> v<version>.`, then ` Rejected <k> rows: unknown label <L> (<count>), failed checks (<count>).` when rows were rejected, then ` <j> new columns: <a>, <b>.` when there are new columns; numbers with thousands separators. Invariant: `rows_read = rows_loaded + rows_rejected + duplicates_removed + repeated_headers_dropped`.

- [ ] **Step 1: Write the failing tests** (db and moto; `ingest` is a fixture calling `ingest_file` with `load_contracts()`, the test engine, the `bucket` fixture and `tmp_path`)

```python
@pytest.mark.db
def test_ingest_baseline_sample_loads(ingest, bucket, engine, capsys):
    upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv")
    r = ingest("raw/cse-cic-ids2018/wed.csv")
    assert r.status == "loaded" and r.rows_read == 200 and r.message.startswith("Loaded ")
    assert r.rows_read == r.rows_loaded + r.rows_rejected + steps(engine)["duplicates_removed"] + steps(engine)["repeated_headers_dropped"]
    assert bucket.exists("processed/cse-cic-ids2018/wed/part-0000.parquet")
    assert dataset(engine, "cse-cic-ids2018").status == "loaded"
    event = last_event(capsys, "ingestion_run")
    assert (event["status"], event["contract"], event["rows_read"]) == ("loaded", "cse-cic-ids2018 v1", 200)

@pytest.mark.db
def test_ingest_columns_in_a_different_order_loads(ingest, bucket): ...                 # ING-02

@pytest.mark.db
def test_ingest_flags_two_new_columns(ingest, bucket):                                   # ING-07
    r = ingest(upload_with_extra_columns(bucket, {"pkt_entropy": "3.2", "geo_country": "VN"}))
    assert r.status == "loaded" and r.new_columns == ["pkt_entropy", "geo_country"]
    assert "2 new columns: pkt_entropy, geo_country." in r.message

@pytest.mark.db
@pytest.mark.parametrize("name", sorted(EXPECTED))                                      # tests/contracts/broken/
def test_broken_files_are_quarantined_for_the_expected_reason(ingest, bucket, name):     # ING-03, ING-08
    r = ingest(upload(bucket, BROKEN / name, f"raw/broken/{name}"))
    assert r.status == "quarantined" and r.message.startswith("No contract matches: missing " + ", ".join(EXPECTED[name]["missing"]))
    assert bucket.exists(r.report_key) and bucket.exists(r.draft_contract_key)
    assert not bucket.exists(f"processed/broken/{Path(name).stem}/part-0000.parquet")

@pytest.mark.db
def test_ingest_mostly_unknown_labels_quarantined(ingest, bucket):
    r = ingest(upload_with_labels(bucket, worm_share=0.3))
    assert r.status == "quarantined" and "failed validation" in r.message and "Worm" in report_text(bucket, r)

@pytest.mark.db
def test_ingest_header_only_file_is_quarantined(ingest, bucket): ...                     # "The file has no data rows."

@pytest.mark.db
def test_ingest_twice_replaces_rows(ingest, bucket, engine): ...                         # same totals, two runs

@pytest.mark.db
def test_reingest_deletes_stale_parts(ingest, bucket):                                   # chunk_rows=50 → 4 parts; then default → 1 part

@pytest.mark.db
def test_ingest_failure_marks_run_failed_and_raises(ingest, bucket, engine, monkeypatch): ...  # Bucket.download raises OSError

def test_ingest_skips_non_csv_key(ingest_without_db): assert ingest_without_db("raw/readme.txt") is None

def test_cli_ingest_requires_key():
    with pytest.raises(SystemExit) as e: main(["ingest"])
    assert e.value.code == 2
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: No module named 'pipeline.ingest'`.

- [ ] **Step 3: Implement `pipeline/ingest.py` and the CLI command.** The CLI builds the engine with `sa.create_engine(settings.database_url)`, `Bucket(settings.s3_bucket)` (a clear error when either is unset) and a `tempfile.TemporaryDirectory()` work directory; `commit_sha` is `settings.app_version`.

- [ ] **Step 4: Copy the contracts into the image.** Dockerfile: `COPY contracts/ contracts/` after `COPY pipeline/`.

- [ ] **Step 5: Run the tests and check the image.** Run the full test command, then `docker build -t cicnids:local .` and `docker run --rm cicnids:local python -c "from pipeline.contracts import load_contracts; print([c.name for c in load_contracts()])"`. Expected: all tests pass, coverage of `pipeline/` at least 80%, the image prints `['cse-cic-ids2018']`.

- [ ] **Step 6: Commit** — message `Ingest one raw file end to end`.

### Task 10: Reconcile and status

**Files:**
- Modify: `pipeline/ingest.py`, `pipeline/cli.py`, `tests/db/test_ingest.py`, `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `ingest_file` (Task 9); `latest_runs`, `mark_stale_runs`, `dataset_summary`, `table_sizes` (Task 6).
- Produces: dataclass `ReconcileSummary(reingested: list[str], skipped: int, stale_failed: int, missing: list[str])`; `reconcile(*, engine, bucket, contracts, commit_sha, workdir) -> ReconcileSummary`; CLI `reconcile` (logs a `reconcile` event with the summary; exit 1 if any re-ingest raised, after trying the rest) and `status` (one `dataset_status` event per dataset from `dataset_summary`, one `table_sizes` event; prints `<n> datasets`).

Rule: first `mark_stale_runs`. Then for each latest run with status `loaded` or `quarantined`, `candidate = match_contract(run.source_columns, contracts)`; re-ingest the file when the candidate exists and its (name, version) differs from (run.contract_name, run.contract_version). A raw object that no longer exists is logged and listed in `missing`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.db
def test_reconcile_loads_a_quarantined_file_once_its_contract_exists(ingest, reconcile_with, bucket, engine):  # ING-09
    ingest(upload(bucket, SIM, "raw/simulated-real-traffic-01.csv"))
    s = reconcile_with(load_contracts() + [SIMULATED])          # SIMULATED = tests/fixtures/contracts/simulated-real-traffic.yaml
    assert s.reingested == ["raw/simulated-real-traffic-01.csv"]
    assert dataset(engine, "simulated-real-traffic-01").status == "loaded" and not dataset(engine, "simulated-real-traffic-01").has_label

@pytest.mark.db
def test_reconcile_reingests_after_a_version_bump_and_then_stops(ingest, reconcile_with, bucket):
    ingest(upload(bucket, WED, "raw/cse-cic-ids2018/wed.csv"))
    assert reconcile_with([baseline(version=2)]).reingested == ["raw/cse-cic-ids2018/wed.csv"]
    assert reconcile_with([baseline(version=2)]).reingested == []

@pytest.mark.db
def test_reconcile_skips_quarantine_with_same_contract(...): ...   # the 30% unknown-label file stays put

@pytest.mark.db
def test_reconcile_skips_when_contract_is_gone(...): ...           # loaded by SIMULATED, reconcile with the baseline only

@pytest.mark.db
def test_reconcile_skips_missing_raw_object(...): ...              # object deleted → missing == [key]

@pytest.mark.db
def test_reconcile_fails_stale_running_runs(...): ...              # stale_failed == 1

@pytest.mark.db
def test_cli_status_logs_each_dataset(...): ...                    # dataset_status events, a table_sizes event, exit 0
```

- [ ] **Step 2: Run them to see them fail.** Expected: `ImportError: cannot import name 'reconcile'`.

- [ ] **Step 3: Implement `reconcile` and the two commands.**

- [ ] **Step 4: Run the tests.** Expected: PASS; coverage of `pipeline/` still at least 80%.

- [ ] **Step 5: Commit** — message `Reconcile files with the contracts in the image`.

### Task 11: The upload trigger and stack changes

**Files:**
- Modify: `infra/environment.yaml`, `infra/databases.yaml`
- Create: `tests/unit/test_environment_template.py`

**Interfaces:**
- Consumes: `JobTaskDefinition`, `ExecutionRole`, `TaskRole`, `TaskSecurityGroup`, `Bucket`, parameter `ClusterName`, export `${PlatformStack}-PublicSubnetIds` (comma-joined).
- Produces: role `cicnids-<env>-events`; rule `cicnids-<env>-ingest`; output `IngestRuleName`.

- [ ] **Step 1: Write the failing test**

```python
# loads the template with cfnlint.decode.cfn_yaml.load
def test_ingest_rule_runs_the_job_with_the_object_key():
    rule = resources()["IngestRule"]["Properties"]
    assert rule["EventPattern"]["detail"]["object"]["key"] == [{"prefix": "raw/"}]
    target = rule["Targets"][0]
    template = target["InputTransformer"]["InputTemplate"].replace("<key>", "raw/my capture.csv")
    assert json.loads(template) == {"containerOverrides": [{"name": "job",
        "command": ["python", "-m", "pipeline", "ingest", "--key", "raw/my capture.csv"]}]}
    assert target["EcsParameters"]["NetworkConfiguration"]["AwsVpcConfiguration"]["AssignPublicIp"] == "ENABLED"

def test_task_role_may_delete_only_processed_objects():
    statements = policy(resources()["TaskRole"], "own-bucket")
    assert any(s["Action"] == "s3:DeleteObject" and s["Resource"] == {"Fn::Sub": "${Bucket.Arn}/processed/*"} for s in statements)
```

- [ ] **Step 2: Run it to see it fail.** Expected: `KeyError: 'IngestRule'`.

- [ ] **Step 3: Edit the templates.**
  - `EventsRole` (`cicnids-${EnvName}-events`): trusted by `events.amazonaws.com`; `ecs:RunTask` on `task-definition/cicnids-${EnvName}-job:*` with condition `ArnEquals ecs:cluster` = the cluster ARN; `iam:PassRole` on the execution and task roles.
  - `IngestRule` (`cicnids-${EnvName}-ingest`, default bus): pattern `source: [aws.s3]`, `detail-type: [Object Created]`, `detail.bucket.name: [!Ref Bucket]`, `detail.object.key: [{prefix: raw/}]`. One ECS target: the cluster ARN, `EventsRole`, `TaskDefinitionArn: !Ref JobTaskDefinition`, `TaskCount: 1`, `LaunchType: FARGATE`, `PlatformVersion: LATEST`, public subnets via `Fn::Split`, `TaskSecurityGroup`, `AssignPublicIp: ENABLED`; `InputTransformer` with `InputPathsMap: {key: $.detail.object.key}` and the template `{"containerOverrides":[{"name":"job","command":["python","-m","pipeline","ingest","--key","<key>"]}]}`; `RetryPolicy: {MaximumRetryAttempts: 5, MaximumEventAgeInSeconds: 3600}`.
  - `TaskRole` policy `own-bucket`: add `s3:DeleteObject` on `${Bucket.Arn}/processed/*`.
  - `databases.yaml`: `BackupRetentionPeriod: 7` on both instances (the account is on the paid plan now; this reverses M1's free-plan ruling). The change modifies the instances in place, without replacement.

- [ ] **Step 4: Run the test and cfn-lint.** Run: `python -m pytest tests/unit/test_environment_template.py; C:\Users\huyho\.venvs\cicnids\Scripts\cfn-lint.exe infra/*.yaml`. Expected: PASS, no cfn-lint output.

- [ ] **Step 5: Commit** — message `Start ingestion on uploads to raw/`.

### Task 12: Pipeline scripts, the ingest workflow and the runbook

**Files:**
- Modify: `scripts/ci/run_task.sh`, `scripts/ci/deploy_env.sh`, `.github/workflows/infra.yml`, `tests/unit/test_ci_scripts.py`, `docs/runbook.md`
- Create: `scripts/ci/ingest.sh`, `.github/workflows/ingest.yml`, `scripts/load_baseline.sh`

**Interfaces:**
- Produces: `run_task.sh [--no-wait] ENV job|admin [COMMAND...]` (with `--no-wait`, print the task id and exit 0 once ECS accepts the task; the wait limit is `TASK_TIMEOUT_MINUTES`, default 30); `ingest.sh ENV TARGET` where TARGET is `reconcile`, `status` or a key starting with `raw/` (anything else exits 2 before any AWS call; it waits with `TASK_TIMEOUT_MINUTES` defaulting to 120); `load_baseline.sh ENV` for `development`, `staging` or `production`.

- [ ] **Step 1: Write the failing tests** (bash only, no jq; a fake `aws` first on `PATH` exits 99, so a test fails loudly if a script reaches AWS)

```python
@needs_bash
@pytest.mark.parametrize("target", ["foo", "processed/x.csv", "raw", ""])
def test_ingest_rejects_unknown_targets_before_aws(target, fake_aws_path):
    assert run("scripts/ci/ingest.sh", "staging", target, path=fake_aws_path).returncode == 2

@needs_bash
def test_run_task_rejects_bad_kind_with_no_wait(fake_aws_path):
    assert run("scripts/ci/run_task.sh", "--no-wait", "staging", "web", path=fake_aws_path).returncode == 2

@needs_bash
def test_load_baseline_rejects_unknown_environment(fake_aws_path):
    assert run("scripts/load_baseline.sh", "test", path=fake_aws_path).returncode == 2
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL (`ingest.sh` and `load_baseline.sh` missing; `--no-wait` read as the environment).

- [ ] **Step 3: Implement the scripts and the workflow.**
  - `deploy_env.sh`: after the smoke test, unless `--skip-migrations`, run `run_task.sh --no-wait "$env_name" job python -m pipeline reconcile`. Rollbacks never start reconcile: an older image may not have it.
  - `ingest.yml`: `workflow_dispatch` with `environment` (choice of the four) and `target` (string: an S3 key under `raw/`, `reconcile` or `status`); one job in that GitHub environment (production waits for approval), deploy-role credentials as in `deploy.yml`, concurrency group `ingest-<env>`; inputs reach the script through `env:`, never interpolated into `run:`.
  - `infra.yml`: drop `scripts/ci/lib.sh` from the `push` paths (M1's deferred minor: a lib.sh-only merge started a platform deployment that changed nothing); keep it in the `pull_request` paths.
  - `load_baseline.sh ENV`: bucket from `stack_output cicnids-$ENV BucketName`, so it fails in any account without the stack. staging and production: copy the ten day files from `s3://cse-cic-ids2018/Processed Traffic Data for ML Algorithms/` to `raw/cse-cic-ids2018/<Day>.csv` (`<Day>` = the name before `_TrafficForML`, "Thuesday" kept), smallest first and the 4 GB file last, one at a time: after each copy, wait up to 3 minutes for a running `cicnids-$ENV-job` task, then until none runs (`aws ecs list-tasks --family`, every 30 s, up to 120 minutes). If the server-side copy is refused, stream it instead (`aws s3 cp --no-sign-request SRC - | aws s3 cp - DST --expected-size SIZE`). development: the first 100,000 data rows of the Wednesday 14 February file, cut into a temporary file (check it has 100,001 lines) and uploaded to `raw/cse-cic-ids2018/Wednesday-14-02-2018.csv`.
  - `docs/runbook.md`: a "Load data" section (load_baseline, make_simulated, the Ingest workflow with its three targets, where reports and drafts land); a "Demo: merge the simulated contract" section (download the draft, save it as `contracts/simulated-real-traffic.yaml`, move `tests/contracts/broken/simulated-real-traffic-01.csv` to `tests/contracts/simulated-real-traffic/` and delete its `expected.yaml` entry, open a pull request; reconcile loads the file after each deployment); in "Roll back": rollbacks skip reconcile, and nothing should be uploaded to `raw/` while an environment runs an image older than M2.

- [ ] **Step 4: Run the tests and the linters.** Run: `python -m pytest tests/unit/test_ci_scripts.py`, `C:\Users\huyho\.venvs\cicnids\Scripts\actionlint.exe`, and shellcheck through `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable -x scripts/ci/*.sh scripts/load_baseline.sh`. Expected: PASS, no findings.

- [ ] **Step 5: Commit** — message `Add the ingest workflow, baseline loading and reconcile after deployments`.

### Task 13: Release M2, load the data and run the rollback drill

Live work in AWS account 551169294418. Approvals of `platform` and `production` are Hoàng's, in the GitHub UI: ask, then wait. Record each step's evidence (run ids, counts, timings) in the ledger.

- [ ] **Step 1: Pull request.** Push `feat/m2-ingestion`, open "M2: data ingestion" (PR template filled in). Expected: lint, test (coverage of `pipeline/` at least 80%), cfn-lint and image (Trivy) green; the Infrastructure preview shows only `BackupRetentionPeriod` 1 → 7 on the two instances.
- [ ] **Step 2: Merge.** Hoàng approves `platform` in the Infrastructure run; `cicnids-databases` updates. CD then deploys development, test and staging. Expected: each deploy log shows `migrate` reaching `0002_run_time_span` before the app update (OPS-04), the smoke test passing, and `reconcile` started. The new tag is `<M2>` below.
- [ ] **Step 3: Development, the upload path (ING-01).** `scripts/load_baseline.sh development`. Expected: EventBridge starts a job task within a minute; the Ingest workflow (`development`, `status`) shows `cse-cic-ids2018` loaded with 100,000 rows read; the Pipeline page's Last ingestion tile shows the run.
- [ ] **Step 4: Development, quarantine (ING-03, ING-08, Review Focus 4).** `aws s3 cp tests/contracts/broken/missing-dst-port.csv "s3://<dev bucket>/raw/broken/missing dst port.csv"`. Expected: a quarantined run; `quarantine/broken/missing dst port/report.md` names `dst_port: expected "Dst Port"`; `draft-contract.yaml` sits beside it.
- [ ] **Step 5: Staging, the full baseline (ING-05).** `scripts/load_baseline.sh staging` (about one to two hours). Expected: ten loaded runs, including the 4 GB Thuesday file inside one 2 vCPU, 8 GB task (no exit code 137); `status` shows the dataset's row count and table sizes well under 1 GB. Record the duration of each run.
- [ ] **Step 6: Staging, the simulated file.** Generate the full file: `python -m scripts.make_simulated <scratch>/friday-16.csv <scratch>/simulated-real-traffic-01.csv` (100,000 rows, outside the repository), then upload it to `raw/simulated-real-traffic-01.csv` in staging. Expected: quarantined, missing `dst_port, fwd_packets, bwd_packets, fwd_bytes, bwd_bytes`; its draft matches `tests/fixtures/contracts/simulated-real-traffic.yaml` apart from comments.
- [ ] **Step 7: Development, the re-ingest rehearsal (ING-09).** Upload the same file to development (quarantined). On a branch `rehearsal/simulated-contract`, apply the runbook's demo change, push it, and run CD by hand on that branch (development only). Expected: reconcile loads `simulated-real-traffic-01` with `has_label` false. Then run Rollback with `development` and `<M2>` (no approval needed), and the Ingest workflow with `development` and `reconcile`. Expected: the reconcile summary re-ingests nothing, because the image no longer has the simulated contract (Review Focus 5). Keep the branch unmerged, and open no pull request from it.
- [ ] **Step 8: Production.** Hoàng approves `production` in the CD run from Step 2 (approval 1). Expected: production runs `<M2>`, the parity table shows `<M2>` everywhere. Then `scripts/load_baseline.sh production`. Expected: the same ten loaded runs as staging.
- [ ] **Step 9: Rollback drill (M1 Task 15 step 12, OPS-05).** Run Rollback with `production` and `2a5a429`; Hoàng approves (approval 2). Expected: the time from approval to a passing smoke test is under 10 minutes; the Pipeline page shows `2a5a429` and its Last ingestion tile still reads the runs table on the `0002` schema. Upload nothing during the drill. Then run Rollback with `production` and `<M2>`; Hoàng approves (approval 3). Expected: production back on `<M2>`, parity table all `<M2>`.
- [ ] **Step 10: Close out.** Mark M1 Task 15 complete in the M1 ledger; update the runbook if a step differed; update the project memory (M2 done, data loaded, next is M3); report cost so far from Cost Explorer.
