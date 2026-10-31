"""Entry point: page setup, sidebar, navigation and banner, then the selected page."""

import streamlit as st

from app import telemetry
from app.components import layout
from app.config import get_settings

# (file, title, Material icon, slug used in page_render logs). The folder is views/, not pages/:
# Streamlit would serve a pages/ folder as an old-style multipage app and skip this shell.
PAGES: list[tuple[str, str, str, str]] = [
    ("views/overview.py", "Overview", ":material/dashboard:", "overview"),
    ("views/timeline.py", "Timeline", ":material/timeline:", "timeline"),
    ("views/targets.py", "Targets", ":material/my_location:", "targets"),
    ("views/feature_explorer.py", "Feature explorer", ":material/query_stats:", "feature_explorer"),
    ("views/data_quality.py", "Data quality", ":material/rule:", "data_quality"),
    ("views/pipeline.py", "Pipeline", ":material/account_tree:", "pipeline"),
]

st.set_page_config(page_title="CIC-NIDS Dashboard", page_icon=":material/shield:", layout="wide")

try:
    settings = get_settings()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

layout.sidebar_brand()
navigation = st.navigation(
    [
        st.Page(file, title=title, icon=icon, default=index == 0)
        for index, (file, title, icon, _) in enumerate(PAGES)
    ]
)
layout.env_banner(settings)
layout.sidebar_footer(settings)

slugs = {title: slug for _, title, _, slug in PAGES}
with telemetry.page_render(slugs.get(navigation.title, navigation.title)):
    navigation.run()
