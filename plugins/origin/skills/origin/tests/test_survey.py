import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from survey import PROPS, survey_project  # noqa: E402

DONOR_DIR = ROOT / "donors" / "_unused"
PUGH = DONOR_DIR / "oleObject17.opj"


def test_props_include_calibrated_tick_property():
    assert "layer.x.ticks" in PROPS
    assert "layer.y.ticks" in PROPS


@pytest.mark.origin
@pytest.mark.skipif(not PUGH.exists(), reason="run recover.py first")
def test_survey_reproduces_known_values():
    """Pugh donor의 실측값을 재현해야 한다 (2026-07-28 측정)."""
    m = survey_project(PUGH)
    assert m["graph"] == "Graph1"
    assert m["measured"]["layer.x.label.pt"] == 24.0
    assert m["measured"]["layer.y.label.pt"] == 24.0
    assert m["measured"]["layer.x.thickness"] == 3.0
    assert m["measured"]["YL.fsize"] == 22.0
    assert m["measured"]["layer.y.ticks"] == 5.0
    assert m["measured"]["layer.x.ticks"] == 0.0
    assert m["measured"]["page.nLayers"] == 1.0


@pytest.mark.origin
@pytest.mark.skipif(not PUGH.exists(), reason="run recover.py first")
def test_missing_axis_title_is_none_not_nan():
    """축 제목이 없는 축은 nan이 아니라 None으로 기록돼야 YAML이 깨지지 않는다."""
    m = survey_project(PUGH)
    assert m["measured"]["XB.fsize"] is None


@pytest.mark.origin
def test_corrupt_project_raises(tmp_path):
    """실패해야 정상: 손상된 .opj는 조용히 빈 결과를 내지 않는다."""
    bad = tmp_path / "bad.opj"
    bad.write_bytes(b"CPYA garbage that is not a real project")
    with pytest.raises(RuntimeError, match="could not open|no graph"):
        survey_project(bad)
