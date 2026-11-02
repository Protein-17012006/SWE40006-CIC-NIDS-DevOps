"""Entry point: page setup, sidebar, navigation and banner, then the selected page."""

import streamlit as st

from app import telemetry
from app.components import filters, layout
from app.config import get_settings

# (file, title, Material icon, slug for the URL and the page_render logs). The folder is views/,
# not pages/: Streamlit would serve a pages/ folder as an old-style multipage app and skip this
# shell. The Pipeline view is pipeline_page.py: a view named pipeline would shadow the pipeline
# package whenever a page script's folder is first on sys.path.
PAGES: list[tuple[str, str, str, str]] = [
    ("views/overview.py", "Overview", ":material/dashboard:", "overview"),
    ("views/timeline.py", "Timeline", ":material/timeline:", "timeline"),
    ("views/targets.py", "Targets", ":material/my_location:", "targets"),
    ("views/feature_explorer.py", "Feature explorer", ":material/query_stats:", "feature_explorer"),
    ("views/data_quality.py", "Data quality", ":material/rule:", "data_quality"),
    ("views/pipeline_page.py", "Pipeline", ":material/account_tree:", "pipeline"),
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
        # The default page lives at /, so only the others take their slug as a URL path
        st.Page(
            file, title=title, icon=icon, default=index == 0, url_path=None if index == 0 else slug
        )
        for index, (file, title, icon, slug) in enumerate(PAGES)
    ]
)
filters.sidebar_filters()
layout.env_banner(settings)
layout.sidebar_footer(settings)

slugs = {title: slug for _, title, _, slug in PAGES}
with telemetry.page_render(slugs.get(navigation.title, navigation.title)):
    navigation.run()
