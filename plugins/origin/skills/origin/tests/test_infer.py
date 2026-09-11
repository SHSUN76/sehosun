import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build import infer_donor  # noqa: E402


def test_categorical_x_single_y_is_bar_labeled():
    df = pd.DataFrame({"sample": ["A", "B"], "val": [1.0, 2.0]})
    assert infer_donor(df, "sample", ["val"]) == "bar_labeled"


def test_categorical_x_multi_y_is_bar_grouped():
    df = pd.DataFrame({"sample": ["A", "B"], "dft": [1.0, 2.0], "md": [3.0, 4.0]})
    assert infer_donor(df, "sample", ["dft", "md"]) == "bar_grouped"


def test_numeric_x_multi_y_is_line_symbol():
    df = pd.DataFrame({"z": [1.0, 2.0, 3.0], "cde": [1, 2, 3], "gide": [4, 5, 6]})
    assert infer_donor(df, "z", ["cde", "gide"]) == "line_symbol"


def test_wide_dynamic_range_is_log_axis():
    df = pd.DataFrame({"freq": [0.01, 1.0, 100000.0], "g": [1.0, 2.0, 3.0]})
    assert infer_donor(df, "freq", ["g"]) == "log_axis"


def test_error_column_is_errorbar():
    df = pd.DataFrame({"s": ["A", "B"], "cv": [0.5, 0.6], "cv_err": [0.05, 0.04]})
    assert infer_donor(df, "s", ["cv", "cv_err"]) == "errorbar"


def test_infer_never_returns_unknown_donor():
    donors = {p.stem for p in (ROOT / "donors").glob("*.opj")}
    df = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    assert infer_donor(df, "x", ["y"]) in donors
