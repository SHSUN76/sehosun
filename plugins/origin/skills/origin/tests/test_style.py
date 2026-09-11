import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from originsession import origin_session  # noqa: E402
from style import (apply_house_style, clipped_values, compute_range,  # noqa: E402
                   load_house_style)

DONOR = ROOT / "donors" / "bar_labeled.opj"


def test_load_house_style():
    s = load_house_style()
    assert s["axis_title_pt"] == 32
    assert s["tick_bitmask"]["in"] == 5


def test_compute_range_pads_and_rounds():
    lo, hi = compute_range([1.15, 2.72, 2.04])
    assert lo == 0.0
    assert hi >= 2.72
    assert hi == pytest.approx(3.0)


def test_compute_range_handles_negative():
    lo, hi = compute_range([-5.0, 3.0])
    assert lo < -5.0
    assert hi > 3.0


def test_compute_range_rejects_empty():
    """실패해야 정상: 빈 데이터로 축 범위를 만들지 않는다."""
    with pytest.raises(ValueError, match="empty"):
        compute_range([])


def test_compute_range_never_clips_data():
    """어떤 입력에도 최대/최소를 자르지 않아야 한다."""
    for vals in ([0.1, 0.2], [1e-3, 5e-3], [14.5, 1.85, 23.2], [999.9], [-0.5, -0.1]):
        lo, hi = compute_range(vals)
        assert lo <= min(vals) and hi >= max(vals), f"clipped {vals} -> ({lo}, {hi})"


def test_compute_range_anchors_zero_for_all_negative_data():
    """실패해야 정상(수정 전): 전부 음수면 축이 0을 안 물어 막대 길이가 무의미해진다."""
    lo, hi = compute_range([-5.0, -3.0])
    assert hi == 0.0, f"axis {lo}..{hi} does not reach the 0 baseline"
    assert lo <= -5.0


def test_compute_range_still_anchors_zero_for_all_positive_data():
    lo, hi = compute_range([3.0, 5.0])
    assert lo == 0.0
    assert hi >= 5.0


def test_compute_range_does_not_anchor_zero_for_mixed_data():
    """0을 이미 포함하므로 양끝을 데이터에 맞춘다 — 한쪽을 0으로 눌러붙이면 안 된다."""
    lo, hi = compute_range([-5.0, 3.0])
    assert lo < -5.0 and hi > 3.0


def test_compute_range_can_turn_the_zero_anchor_off():
    """범위 막대처럼 바닥이 0이 아닌 축은 0을 강제하면 창만 좁아진다."""
    lo, hi = compute_range([-5.0, -3.0], anchor_zero=False)
    assert hi < 0.0
    assert lo <= -5.0 and hi >= -3.0


def test_compute_range_ignores_missing_cells():
    """빈 셀(NaN)이 섞여도 축은 나머지 값으로 계산된다."""
    lo, hi = compute_range([1.0, float("nan"), 3.0])
    assert (lo, hi) == pytest.approx(compute_range([1.0, 3.0]))


def test_clipped_values_finds_what_falls_outside():
    assert clipped_values(0.0, 3.0, [1.0, 2.9]) == []
    assert clipped_values(0.0, 3.0, [1.0, 3.4, -0.2]) == [3.4, -0.2]
    assert clipped_values(0.0, 3.0, [float("nan"), 1.0]) == []


@pytest.mark.origin
def test_house_style_forces_bold_tick_labels():
    """bold는 house style 요구사항인데 YAML만 읽는 단언으로는 아무것도 증명하지 못한다.

    donor(bar_labeled)는 이미 bold=1이라 그냥 재보면 항진명제다. 먼저 0으로 꺼서
    '발동해야 정상인' 상태를 만든 뒤 적용하고 다시 잰다.
    """
    with origin_session() as op:
        assert op.open(str(DONOR.resolve()), readonly=False)
        g = op.graph_list()[0]
        op.lt_exec(f"win -a {g.name};")

        assert op.lt_exec("layer.x.label.bold = 0; layer.y.label.bold = 0; doc -uw;")
        assert op.lt_float("layer.x.label.bold") == 0.0, "테스트 전제가 안 잡혔다"
        assert op.lt_float("layer.y.label.bold") == 0.0, "테스트 전제가 안 잡혔다"

        apply_house_style(op)

        assert load_house_style()["tick_label_bold"] is True
        assert op.lt_float("layer.x.label.bold") == 1.0
        assert op.lt_float("layer.y.label.bold") == 1.0


@pytest.mark.origin
def test_house_style_actually_lands():
    """적용 후 재측정 — 값이 정말 찍혔는지 확인한다 (픽셀 비교 아님)."""
    with origin_session() as op:
        assert op.open(str(DONOR.resolve()), readonly=False)
        g = op.graph_list()[0]
        op.lt_exec(f"win -a {g.name};")

        apply_house_style(op)

        assert op.lt_float("layer.x.label.pt") == 24.0
        assert op.lt_float("layer.y.label.pt") == 24.0
        assert op.lt_float("layer.x.thickness") == 4.0
        assert op.lt_float("layer.y.thickness") == 4.0
        assert op.lt_float("layer.y.ticks") == 5.0
        assert op.lt_float("YL.fsize") == 32.0
