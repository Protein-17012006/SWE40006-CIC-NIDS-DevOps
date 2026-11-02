import tomllib
from pathlib import Path

from app.data.fields import ATTACK_CATEGORIES, CATEGORY_COLORS


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
    assert CATEGORY_COLORS == {
        "Benign": "#8F8D86",
        "DoS": "#2A78D6",
        "DDoS": "#EB6834",
        "Brute force": "#1BAF7A",
        "Web attack": "#EDA100",
        "Botnet": "#E87BA4",
        "Infiltration": "#008300",
    }


def test_quality_steps_match_ingestion():
    """The dashboard orders cleaning steps itself, to avoid importing pandera at start-up."""
    from app.data.fields import QUALITY_STEPS
    from pipeline.clean import STEPS

    assert QUALITY_STEPS == STEPS
