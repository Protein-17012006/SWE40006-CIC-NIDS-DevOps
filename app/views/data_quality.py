"""Data quality (UI-06): which problems in the data could mislead an analyst.

The page describes the dataset's files, so it reads the latest run of each file and uses only
the Dataset filter.
"""

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.filters import page_filters
from app.components.format import basename, compact, percent, plural, status_badge
from app.components.layout import chart_card, kpi_tile, load_or_warn, page_header
from app.data import queries

STEP_LABELS = {
    "duplicates_removed": "Duplicate rows removed",
    "infinite_set_to_null": "Infinite values set to null",
    "missing_kept_as_null": "Missing values kept as null",
    "repeated_headers_dropped": "Repeated headers dropped",
    "labels_trimmed": "Label values trimmed",
}


def steps_chart(df: pd.DataFrame) -> None:
    named = df.assign(step=df["step"].map(STEP_LABELS))
    charts.show(charts.bars(named, "rows_affected", "step", log=True))


def changed_steps(dataset_id: str) -> pd.DataFrame:
    """The step counts, or none at all when cleaning changed nothing (a log axis has no 0)."""
    steps = queries.cleaning_steps(dataset_id)
    return steps if steps["rows_affected"].sum() > 0 else steps.iloc[0:0]


def columns_table(df: pd.DataFrame) -> None:
    table = pd.DataFrame(
        {
            "Column": df["column_name"],
            "Nulls": df["nulls"].map(lambda n: f"{n:,}"),
            "Infinite": df["infinite"].map(lambda n: f"{n:,}"),
            "Action": df["action"],
        }
    )
    st.dataframe(table, hide_index=True)


def column_count(sources: object, new: object) -> str:
    count = str(len(sources or ()))
    added = len(new or ())
    return f"{count} ({added} new, kept)" if added else count


def files_table(df: pd.DataFrame) -> None:
    table = pd.DataFrame(
        {
            "File": df["file_key"].map(basename),
            "Rows": df["rows_read"].map(lambda n: f"{n:,}"),
            "Columns": [
                column_count(s, n)
                for s, n in zip(df["source_columns"], df["new_columns"], strict=True)
            ],
            "Status": df["status"].map(status_badge),
        }
    )
    st.dataframe(table, hide_index=True)


page_header("Data quality")
f = page_filters()
files = load_or_warn("Files", lambda: queries.dataset_files(f.dataset_id))
steps = load_or_warn("Cleaning steps", lambda: queries.cleaning_steps(f.dataset_id))
issues = load_or_warn("Columns", lambda: queries.column_issues(f.dataset_id))
if files is None or steps is None or issues is None:
    st.stop()

runs = sorted(files["run_id"].tolist())
span = f"ingestion runs #{runs[0]} to #{runs[-1]}" if len(runs) > 1 else f"ingestion run #{runs[0]}"
st.caption(
    f"What the cleaning step changed in {f.display_name} · {span} · uses only the Dataset filter"
)

rows_read = int(files["rows_read"].sum())
step_rows = dict(zip(steps["step"], steps["rows_affected"], strict=True))
duplicates = int(step_rows.get("duplicates_removed", 0))
quarantined = int((files["status"] == "quarantined").sum())
infinite_columns = int((issues["infinite"] > 0).sum())
tiles = [
    ("Rows read", compact(rows_read), plural(len(files), "file")),
    (
        "Rows rejected",
        compact(int(files["rows_rejected"].sum())),
        f"{plural(quarantined, 'quarantined file')}",
    ),
    (
        "Duplicates removed",
        compact(duplicates),
        f"{percent(duplicates / rows_read) if rows_read else '—'} of rows read",
    ),
    (
        "Infinite values replaced",
        compact(int(step_rows.get("infinite_set_to_null", 0))),
        plural(infinite_columns, "column"),
    ),
]
for column, (label, value, caption) in zip(st.columns(4), tiles, strict=True):
    with column:
        kpi_tile(label, value, caption)

left, right = st.columns(2)
with left:
    chart_card(
        "Rows changed by each cleaning step",
        "Log scale",
        lambda: changed_steps(f.dataset_id),
        steps_chart,
        empty="The cleaning step changed no rows.",
    )
with right:
    chart_card(
        "Columns needing attention",
        f"Before cleaning, all {plural(len(files), 'file')}",
        lambda: queries.column_issues(f.dataset_id),
        columns_table,
        empty="No column needed attention.",
    )

constant = issues.loc[issues["action"] == "constant, hidden", "column_name"].tolist()
if constant:
    one = len(constant) == 1
    st.warning(
        f"{plural(len(constant), 'column')} {'holds' if one else 'hold'} one value in every row "
        f"and {'is' if one else 'are'} hidden from the Feature explorer: {', '.join(constant)}."
    )

chart_card(
    "Files in this dataset",
    "Latest run of each file",
    lambda: queries.dataset_files(f.dataset_id),
    files_table,
)
