# Design: the dashboard pages in the Material theme

Agreed on 2 November 2026; section 1 lists what was decided then.

This design covers step 3 of the build order in the [build design](2026-10-31-build-design.md): the six dashboard pages. It starts from the Design and Requirements Report (section 2.2 for UI-01 to UI-11, section 4.4 for the query rules, section 5 for each page, section 6.3 for the definition of done) and the Figma draft (file `ZtSHTCLNwzC8AYPR6xyMyO`, frames 01 to 07). Neither is in this repository. Section 3 lists where this design departs from them; elsewhere the report holds. Everything outside section 1 is a proposal the builder may change on review.

## 1. Decisions already taken

| Decision | Date |
| --- | --- |
| The report's UI design and the Figma draft are a starting point, not a contract. A page may add or change things where that serves it. The Figma file is not updated to match the app. | 2 Nov |
| Build from what already exists rather than hand-drawn components: Streamlit's bundled theme and dashboard patterns. The course grades deployment; the site must be tidy and fit its purpose, and looking good is a bonus. | 2 Nov |
| The look is Streamlit's bundled `material-ui` theme (Material Design 3: Roboto, primary `#6750A4`, 16 px radius, borderless widgets, light only). It was picked from side-by-side mockups over `dense-dashboard` (light and dark) and `shadcn`. It replaces the slate theme in report section 5.1. | 2 Nov |
| All six pages are built in this milestone and read real data from PostgreSQL. | 2 Nov |
| One pull request per page, through the existing CI and CD, so each page reaches the cloud on its own and a problem points to one page. | 2 Nov |

## 2. Goals, non-goals and anti-goals

**Goal.** Each of the six pages answers its question with real data in all four environments, in the Material theme, and each arrived through its own pull request. Together they meet UI-01 to UI-10, and UI-11 as well (section 3).

**Non-goals.**

- Dark mode, or a theme switch for viewers.
- Updating the Figma file or the report. The team updates the final report from this design later.
- The Re-ingest button (report section 5.8). Reconcile already loads a quarantined file after the deployment that brings its contract (build design section 5.3), which meets ING-09 and the acceptance checklist without a button.
- The upload card (ING-10, a Could item).
- Changes to ingestion, contracts or the schema, apart from an index a page needs to stay fast.

**Anti-goals.** These count as failures even if the pages work:

- Custom CSS, `unsafe_allow_html` styling or a third-party component library. They break on Streamlit upgrades and add packages for Trivy to scan.
- Any new runtime dependency other than `plotly`.
- A page that raises an exception when the database is unreachable or empty, or when the dataset lacks a field a chart needs.
- SQL outside `app/data/queries.py`, or a source column name in code outside `contracts/` (report section 6.3). Showing the column names that ingestion stored, as the Data quality page does, is data and is fine.
- Colour as the only way to tell categories apart.
- One pull request that carries several pages.

## 3. Changes from the report

| Report | This design | Why |
| --- | --- | --- |
| 5.1: slate theme from the Figma read-me | Streamlit's `material-ui` theme | Decided on 2 Nov |
| 5.1: single-measure charts in slate `#2E3A59` | Single-measure charts in the theme primary, `#6750A4` | Follows the theme |
| 5.8: Re-ingest button | Left out; the quarantine card says that the deployment of a matching contract loads the file | Section 2, non-goals |
| 6.1: CSV download (UI-11) as a late Could item | Every card offers its data as CSV from the start | The card helper makes it one argument per card |
| 3.2 and 5.9: `pages/` folder | `app/views/`, as today | A `pages/` folder makes Streamlit skip the navigation shell (comment in `app/main.py`) |

Everything else in report sections 4.4, 5 and 6.3 stands, including the category colours.

## 4. Look and shared parts

### 4.1 Theme

Replace the `[theme]` table in `.streamlit/config.toml` with the `material-ui` template that ships with Streamlit 1.66.1, at `streamlit/.agents/skills/developing-with-streamlit/assets/templates/themes/configs/material-ui.toml` inside the installed package. Copy it unchanged except `chartCategoricalColors` (section 4.2). Keep the `[browser]` and `[client]` tables.

The template loads Roboto and Roboto Mono from Google Fonts in the viewer's browser, through its `font = "'Roboto':<url>"` lines; no font files go into the image.

### 4.2 Category colours (UI-09)

The colours of report section 5.1 stay, because they were checked for colour-blind separation:

| Category | Colour |
| --- | --- |
| Benign | `#8F8D86` |
| DoS | `#2A78D6` |
| DDoS | `#EB6834` |
| Brute force | `#1BAF7A` |
| Web attack | `#EDA100` |
| Botnet | `#E87BA4` |
| Infiltration | `#008300` |

They live once, as `CATEGORY_COLORS` in `app/data/fields.py` next to `ATTACK_CATEGORIES`, and the theme's `chartCategoricalColors` lists them in the same order, so Streamlit's own charts agree. Brute force, Web attack and Botnet have under 3:1 contrast on white, so every chart that uses them carries value labels or sits beside a table.

### 4.3 Page frame

Every page follows report section 5.1:

1. The environment banner outside production (exists, UI-10).
2. A header: `st.title`, then one caption line naming the dataset, flows, capture days and last load time.
3. A row of four KPI tiles on pages that have one: the existing `kpi_tile` (a bordered `st.metric` with a caption line) in `st.columns(4)`.
4. Cards: a new `card(title, caption, data=None)` helper in `app/components/layout.py` returns `st.container(border=True)` holding a bold title and a caption line; the chart or table goes inside. When `data` is a DataFrame, the card shows a small tertiary "CSV" `st.download_button` with it (UI-11). Two cards side by side use `st.columns(2)`.
5. Hidden cards (UI-08): the same card, with the caption "Hidden: this chart needs the label field." (or the field it lacks) and no body.
6. Tables: `st.dataframe(hide_index=True)` with `column_config` for number formats. Status shows as badge text, as report section 4.4 gives it: ✅ Loaded, ⚠️ Quarantined, ❌ Failed, ⏳ Running.
7. Callouts: `st.info` for explanations, `st.warning` for problems.

`coming_soon` goes away with the last placeholder. Every page stays usable at 1366 × 768 without horizontal scrolling (NFR-07).

### 4.4 Charts

Plotly through `st.plotly_chart`, as report section 2.5 fixes; `plotly` joins `requirements.txt` in the first pull request. Streamlit's Plotly theme applies the Material fonts and colours. Helpers in `app/components/charts.py` cover what the pages need: horizontal bars on a linear or log axis with value labels, stacked bars (counts or 100 %), hourly bars, and a box plot from precomputed statistics. One height constant, `CHART_HEIGHT = 300`, for every chart.

### 4.5 Guard (UI-08)

`app/components/guard.py` decides whether a chart can be drawn. Each chart names the fields it needs (`label`, `timestamp`, `dst_port`, `protocol`, or a Feature explorer field); the guard checks them against the selected dataset's `fields`, `extra_fields` and `has_label`, and draws the hidden card when one is missing. Every chart goes through it.

### 4.6 Sidebar filters (UI-01)

The filters are drawn in `app/main.py` through `app/components/filters.py`, so every page shares them; widgets in the entrypoint keep their state across pages. As report section 5.1 gives them:

- A "FILTERS" caption.
- **Dataset**: `st.selectbox` over the datasets whose status is `loaded`, baseline (CSE-CIC-IDS2018) first, shown by `display_name`.
- **Date range**: `st.date_input` with a start and an end, bounded by the dataset's first and last day; the whole span by default. While a viewer has picked only the start, treat the range as that one day.
- **Attack categories**: `st.multiselect` over the six attack categories, all selected by default; disabled with a one-line caption for a dataset without a label.

`current_filters()` returns a frozen `Filters(dataset_id, date_from, date_to, categories, fields, extra_fields, has_label)` that every query takes. When no dataset is loaded, the filters are not drawn. Pipeline ignores the filters, and Data quality uses only the dataset; both say so in their caption.

### 4.7 Queries

- One function per visual in `app/data/queries.py`, as today: parameterised SQL through `sa.text`, `@st.cache_data(ttl=300)`, a DataFrame back. Arguments are plain values (dataset id, dates, a tuple of categories) so the cache works.
- The rules of report section 4.4 hold: filters are bound parameters; Benign is always kept; null hours are kept, so datasets without timestamps are not filtered out; queries that do not need the label skip the category filter when `has_label` is false; `dst_port = -1` is the "other" bucket of capped ports; percentiles come from `flow_sample`, while flow counts always come from `agg_hourly`.
- A dataset's figures are sums over its files (`file_key`).
- `hour`, `day` and `ts` are capture times without a time zone and are shown unchanged. Load times (`loaded_at`, `started_at`) are shown in UTC.
- A query that raises is logged with `log_event("query_failed", ...)`, as the Pipeline page does, and its card shows `st.warning` instead of the visual; the rest of the page still renders. One small helper does this so pages do not repeat the try/except.

### 4.8 States every page handles

| State | What the page shows |
| --- | --- |
| Database unreachable | The header, then `st.error` saying the database cannot be reached. Pipeline keeps its tiles. |
| Migrated, nothing loaded | `st.info` saying no dataset is loaded yet, pointing to the runbook's "Load data" section. |
| Dataset lacks a field | Hidden cards for the charts that need it (section 4.5). |
| Filters match no flows | `st.info`: no flows match the filters. |

For the unlabelled simulated file:

| Page | What changes |
| --- | --- |
| Overview | The unlabelled layout of section 5.1. |
| Timeline | "Attack flows per capture day" is hidden. The day picker lists every capture day, the hourly chart shows all traffic in the primary colour, and "Busiest hours" drops its Main category column. |
| Targets | Ports and protocols cover all traffic and the captions say so. "Main port per attack category" is hidden. |
| Feature explorer | One box and one table row, "All traffic". |
| Data quality, Pipeline | Nothing; neither needs the label. |

### 4.9 Fixtures

`tests/fixtures/seed.py` (`python -m tests.fixtures.seed`) loads the two fixtures of report section 6.2 into a migrated database: a labelled dataset covering all seven categories over two capture days, and a one-day unlabelled file with two extra fields. It fills every table a page reads, `quality_*` and `ingestion_runs` included, with one quarantined run. Page tests and local development both use it.

## 5. Pages

Pages ship in the report's order (section 6.1). Element lists, data sources and captions follow report section 5; what follows is the summary plus what this design adds or settles.

### 5.1 Overview (UI-02, UI-08, UI-09)

"How much traffic is malicious, and which attacks are common or rare." Frame 01.

- Tiles: Flows (caption: capture days), Attack share (caption: attack flows), Attack types (distinct attack labels; caption: categories), Capture days (caption: first to last day).
- Card "Flows by category": horizontal bars, log axis, value labels, every category including Benign.
- Card "Top attack labels": the top 8 labels with Category, Flows and Share of attack flows.
- Card "Attack mix": one 100 % stacked bar of attack flows by category, Benign left out, share labels on segments of 10 % or more, a legend beneath.

**Unlabelled dataset**, frame 07 and report section 5.3: Attack share and Attack types show "—" with the caption "no label column"; the fourth tile becomes New columns (count, names as caption) when the latest run reported new columns. An `st.info` says: "This file has no label column, so the attack-category charts are hidden. Traffic charts still work, and the <n> new columns appear in the Feature explorer." The first row holds "Flows per hour" and "Top destination ports" (all traffic, primary colour, linear scale); hidden cards for "Flows by category" and "Attack mix" sit below.

### 5.2 Timeline (UI-03)

"When attacks happen, and whether they come in bursts." Frame 02; no KPI row.

- Card "Attack flows per capture day": bars per day stacked by attack category, Benign left out, value labels on top, the selected day shaded.
- Day picker: `st.selectbox` of capture days, defaulting to the day with the most attack flows. A bar click may also set it through `st.plotly_chart(on_select="rerun")`.
- Card "Flows per hour on <day>": bars for 00:00 to 23:00, Benign and the day's attack categories stacked. The caption names the peak hour and its main label, for example "HOIC sent 686 k flows between 14:00 and 15:00".
- Card "Busiest hours": the top 5 hours over all days, with Day, Hour, Flows and Main category.

### 5.3 Targets (UI-04)

"Which ports and protocols each attack aims at." Frame 03.

- `st.info`: ports outside the top 50 per day, category and protocol are counted together as "other". Frame 03 has a callout whose text cannot be read; this one is proposed.
- Card "Top 10 destination ports": horizontal bars of attack flows in the primary colour, linear scale, labels like "80 · HTTP". The "other" bucket (`dst_port = -1`) never ranks. Leaving only DDoS in the category filter shows DDoS's own top ports (the UI-04 acceptance check).
- Card "Protocol mix by category": 100 % stacked horizontal bars per category, TCP, UDP and ICMP in that order (protocol numbers 6, 17 and 1); anything else is "Other".
- Card "Main port per attack category": Category, Main port, Share of its flows, Next port with its share.
- Service names come from a small static map in `app/data/ports.py`: 0 no port, 21 FTP, 22 SSH, 25 SMTP, 53 DNS, 80 HTTP, 123 NTP, 139 NetBIOS, 443 HTTPS, 445 SMB, 3389 RDP, 8080 HTTP alt. Other ports show the number alone.

### 5.4 Pipeline, the rest (UI-07)

"Which datasets are loaded, under which contract, which files were rejected, and which version is running." Frame 06. The four tiles exist.

- Card "Datasets": Dataset, Contract ("cse-cic-ids2018 v1" or "no match"), Rows, Last run, Status.
- Card "Recent ingestion runs": the last 20, newest first: Run, File, Started, Duration (m:ss), Loaded, Rejected, Status.
- Card "Quarantined files": one `st.warning` per file whose latest run was quarantined, with the file, the run number and the run's one-line `message`. Two buttons: "View report" opens an `st.dialog` showing the report read from `report_key`; "Download draft contract" is an `st.download_button` with the YAML read from `draft_contract_key`. Under them, one line: once a contract for this file is merged and deployed, the deployment loads it. With no bucket configured (a laptop), the buttons are left out. With nothing quarantined, the card says so in one line.
- A row selected in the Datasets table may set the Dataset filter and switch to the Overview (`st.switch_page`), as frame 06 links to frame 07.

### 5.5 Data quality (UI-06)

"Which problems could mislead an analyst." Frame 05. The page reads the latest run of each file in the selected dataset and uses only the Dataset filter.

- Tiles: Rows read (caption: files), Rows rejected (caption: quarantined files), Duplicates removed (caption: % of rows read), Infinite values replaced (caption: columns).
- Card "Rows changed by each cleaning step": horizontal bars in the primary colour, log scale. Stored step names map to labels: `duplicates_removed` "Duplicate rows removed", `infinite_set_to_null` "Infinite values set to null", `missing_kept_as_null` "Missing values kept as null", `repeated_headers_dropped` "Repeated headers dropped", `labels_trimmed` "Label values trimmed".
- Card "Columns needing attention": Column, Nulls, Infinite, Action, from `quality_columns`.
- `st.warning`: how many columns hold one value in every row and are hidden from the Feature explorer.
- Card "Files in this dataset": File, Rows, Columns (such as "84 (4 extra, kept)"), Status.

### 5.6 Feature explorer (UI-05)

"Which flow features separate attacks from normal traffic, including newly detected columns." Frame 04.

- Controls: Field, an `st.selectbox` of numeric fields with units, such as "Flow duration (µs)": the numeric canonical fields in the dataset's `fields`, plus the numeric `extra_fields`, minus the columns Data quality reports as constant. A new column therefore appears after ingestion (the UI-05 acceptance check). Chart, an `st.selectbox` of Box plot or Histogram. Log scale, an `st.toggle`, on by default.
- `st.info` naming the fields kept as extras.
- Card "<Field> by category": a box plot from precomputed statistics, `go.Box(q1, median, q3, lowerfence=p5, upperfence=p95)`, one box per category in its colour, or a histogram with log-spaced bins per category. The caption says "box = 25th to 75th percentile, white line = median, whiskers = 5th to 95th percentile". Without a label, one box for all traffic.
- Card "Summary statistics": Category, Flows (from `agg_hourly`), Median, 95th percentile and Mean (from the sample), in the field's units.
- Extras live in `flow_sample.extras` (JSONB). A field counts as numeric when its sampled values are JSON numbers. The builder checks how ingestion names extras and constant columns, so the two lists can be matched.

## 6. Shipping

### 6.1 Pull requests

| Pull request | Content |
| --- | --- |
| 1. Theme and shared parts | `config.toml`, `plotly`, colours, `card()` with CSV download, chart helpers, guard, sidebar filters, the states of section 4.8, the seed fixtures. The placeholders stay, now in the new theme; the Pipeline tiles restyle without code changes. |
| 2. Overview | Both layouts |
| 3. Timeline | |
| 4. Targets | |
| 5. Pipeline, the rest | |
| 6. Data quality | |
| 7. Feature explorer | Also removes `coming_soon` |

Each one: a branch `feat/m3-<page>`, the pull request template with its requirement IDs, green CI, merge. CD then takes it through development, test and staging, and production after approval. Before approving production, open the page in development (port 8082) and staging (port 8080). Development holds 100,000 rows of one day; staging should hold the full baseline. The Ingest workflow's `status` target shows what each environment holds.

### 6.2 Tests

- **Page tests** with AppTest, as in `tests/app/test_pipeline_page.py`, for each page in four states: database unreachable, migrated and empty, the labelled fixture, the unlabelled fixture. They assert that nothing raises and check the key outputs: tile labels and values, card titles, the hidden cards.
- **Query tests** against PostgreSQL in `tests/db/test_queries.py`, on the seeded fixtures: sums across files, the date and category filters, Benign always kept, null hours kept, the "other" port bucket.
- **Unit tests** for the guard and the formatting helpers.
- Coverage stays gated on `pipeline/` only (build design section 7). These tests cover `app/` without a gate.

### 6.3 Done when

Each pull request meets report section 6.3, adjusted to this design:

- The page follows section 5 and the Material theme, and is usable at 1366 × 768.
- Every chart goes through the guard and has a hidden state.
- AppTest passes in the four states of section 6.2.
- No SQL outside `app/data/queries.py`, and no source column names in code outside `contracts/`.
- The page logs a `page_render` event, and logs hold no secrets or row data.
- CI is green, and after merge the page runs in development, test and staging, then production after approval.

When the last page is live: every page renders in under 3 seconds on staging with the full baseline (NFR-01, the page-render metric), and the README's status line names milestone 3.

## 7. Left to the builder

- The SQL, any index, and cache settings.
- Chart details: axis formats, tooltips, the histogram's bins.
- Wording of captions and callouts beyond what this document and the report fix.
- Whether KPI tiles carry sparklines (`st.metric` `chart_data`).
- How the helpers split into modules, within the homes report section 5.9 gives.
