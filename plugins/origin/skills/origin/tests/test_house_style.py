from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_house_style_has_required_keys():
    style = yaml.safe_load((ROOT / "data" / "house_style.yaml").read_text(encoding="utf-8"))
    assert style["axis_title_pt"] == 32
    assert style["tick_label_pt"] == 24
    assert style["axis_thickness"] == 4
    assert style["tick_direction"] == "in"
    assert style["tick_label_bold"] is True


def test_tick_direction_maps_to_bitmask():
    style = yaml.safe_load((ROOT / "data" / "house_style.yaml").read_text(encoding="utf-8"))
    assert style["tick_bitmask"] == {"none": 0, "in": 5, "out": 10, "both": 15}
