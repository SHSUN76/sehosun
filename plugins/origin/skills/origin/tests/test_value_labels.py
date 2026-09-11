"""값 라벨이 막대를 덮는 결함에 대한 회귀 테스트.

donor(bar_labeled)의 2번째 점은 값 라벨이 '막대 위'가 아니라 '막대 top 아래'에
붙어 있다 (donor 원본 렌더에서도 1.61 라벨이 막대 안에 있다). 데이터/축 범위와
무관하게 점 인덱스에 따라붙는 결함이므로, 렌더된 픽셀로 직접 확인한다.

발동해야 정상인 테스트다: 수정 전에는 반드시 실패해야 한다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import decorate  # noqa: E402
from build import build_graph  # noqa: E402
from originsession import origin_session  # noqa: E402


def _bar_mask(a):
    """막대 픽셀(채도 있는 색 또는 중간 회색). 검정 글자/흰 배경은 제외된다."""
    mx, mn = a.max(axis=2), a.min(axis=2)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    colored = (mx - mn) > 25
    grayish = (abs(r - 128) < 30) & (abs(g - 128) < 30) & (abs(b - 128) < 30)
    return colored | grayish


def _runs(flags, max_gap=40, min_width=40):
    """True 구간을 찾되, 글자 획 사이의 작은 틈은 메워서 하나로 본다."""
    idx = [i for i, v in enumerate(flags) if v]
    if not idx:
        return []
    out, s, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > max_gap:
            out.append((s, prev))
            s = i
        prev = i
    out.append((s, prev))
    return [(a, b) for a, b in out if b - a >= min_width]


def measure_bars_and_labels(png: Path):
    """(막대 top, 값 라벨 bbox) 목록을 픽셀에서 읽는다.

    막대 top은 막대 '왼쪽 가장자리 안쪽' 세로 띠에서 찾는다 — 가운데는 값 라벨이
    덮을 수 있어서 top을 잘못 읽는다 (안티에일리어싱된 글자가 회색으로 잡힌다).
    """
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    mask = _bar_mask(a)
    # 축 아래 눈금 라벨의 안티에일리어싱 회색도 mask에 잡힌다. 막대가 있는 행은
    # 채워진 픽셀이 훨씬 많으므로 그 기준으로 바닥(=y축 0선)을 찾는다.
    rows_any = np.where(mask.sum(axis=1) >= 100)[0]
    if len(rows_any) == 0:
        return []
    bottom = int(rows_any.max())

    probe = mask[bottom - 4]
    bars = _runs(list(probe))

    dark = a.sum(axis=2) < 200
    out = []
    for (x0, x1) in bars:
        strip = mask[:, x0 + 6:x0 + 14]
        full = np.where(strip.all(axis=1))[0]
        top = int(full.min()) if len(full) else bottom

        sub = dark[: bottom - 8, x0 + 18:x1 - 18]
        rows = sub.any(axis=1)
        groups, s = [], None
        for y, v in enumerate(rows):
            if v and s is None:
                s = y
            elif not v and s is not None:
                groups.append((s, y - 1))
                s = None
        if s is not None:
            groups.append((s, len(rows) - 1))
        cand = [gp for gp in groups if 12 <= gp[1] - gp[0] <= 70]
        label = min(cand, key=lambda gp: abs((gp[0] + gp[1]) / 2 - top)) if cand else None
        out.append({"x0": x0, "x1": x1, "top": top, "label": label})
    return out


@pytest.mark.origin
def test_short_bar_value_label_is_not_swallowed(tmp_path):
    """짧은 막대(전체 범위의 10% 미만)가 섞여도 모든 값 라벨이 막대 top 위에 있어야 한다."""
    csv = tmp_path / "short.csv"
    csv.write_text("sample,val\nA,14.5\nB,1.85\nC,23.2\n", encoding="utf-8")
    spec = {
        "id": "short", "donor": "bar_labeled", "data": str(csv),
        "x": "sample", "y": "val", "y_title": "g / 100 mL", "y_range": "auto",
    }
    png = tmp_path / "short.png"
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        op.find_graph(page).save_fig(str(png.resolve()).replace("\\", "/"), width=1000)

    bars = measure_bars_and_labels(png)
    assert len(bars) == 3, f"expected 3 bars, measured {len(bars)}"

    # 짧은 막대가 실제로 짧은지(테스트 전제) 먼저 확인한다.
    heights = [b["top"] for b in bars]
    assert min(heights) != max(heights)

    for i, b in enumerate(bars):
        assert b["label"] is not None, f"bar {i}: value label not found"
        lb_bottom = b["label"][1]
        assert lb_bottom < b["top"], (
            f"bar {i}: value label bottom={lb_bottom} is not above bar top={b['top']} "
            f"(label overlaps the bar)"
        )


# --------------------------------------------------------- 빈 셀 (NaN)

def test_format_value_refuses_a_missing_value():
    """실패해야 정상(수정 전): int(nan) 이 'cannot convert float NaN to integer' 로
    죽으면서 그래프 전체가 중단됐다. 이제는 어느 값이 문제인지 말해 준다."""
    with pytest.raises(ValueError, match="missing value"):
        decorate.format_value(float("nan"))
    with pytest.raises(ValueError, match="missing value"):
        decorate.format_value(None)
    with pytest.raises(ValueError, match="missing value"):
        decorate.format_value_label("{v:.2f}", float("nan"))


def test_is_missing_only_catches_unusable_values():
    assert decorate.is_missing(float("nan"))
    assert decorate.is_missing(float("inf"))
    assert decorate.is_missing(None)
    assert not decorate.is_missing(0.0)
    assert not decorate.is_missing(-3.5)


@pytest.mark.origin
def test_a_blank_cell_skips_its_label_instead_of_killing_the_graph(tmp_path):
    """회귀: 빈 셀 하나가 그래프 전체를 무너뜨리면 안 된다.

    `compute_range` 는 NaN을 명시적으로 허용하는데 값 라벨에서만 죽었다. 빈 칸은
    라벨을 건너뛰고, 나머지 값의 라벨은 전부 그려져야 한다.
    """
    csv = tmp_path / "gap.csv"
    csv.write_text("sample,val\nA,14.5\nB,\nC,23.2\n", encoding="utf-8")
    spec = {
        "id": "gap", "donor": "bar_labeled", "data": str(csv),
        "x": "sample", "y": "val", "y_title": "g / 100 mL", "y_range": "auto",
    }
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")   # 예외 없이 완주해야 한다
        texts = [o.Text or "" for o in op.find_graph(page)[0].obj.GraphObjects]

    joined = "\n".join(texts)
    assert "14.5" in joined
    assert "23.2" in joined
    assert "nan" not in joined.lower(), f"NaN이 라벨로 새어 나왔다: {texts}"


# ------------------------------------------------------ 음수 막대의 라벨 방향

def test_value_label_goes_above_a_positive_bar():
    assert decorate.value_label_center(10.0, 2.0) > 10.0


def test_value_label_goes_below_a_negative_bar():
    """실패해야 정상(수정 전): 항상 +y로 올려서 음수 막대는 라벨이 막대 안에 그려졌다."""
    assert decorate.value_label_center(-10.0, 2.0) < -10.0


def test_value_label_offset_is_symmetric():
    up = decorate.value_label_center(10.0, 2.0) - 10.0
    down = -10.0 - decorate.value_label_center(-10.0, 2.0)
    assert up == pytest.approx(down)


@pytest.mark.origin
def test_negative_bars_keep_their_labels_outside_the_bar(tmp_path):
    """음수 데이터로 실제 그래프를 만들고, 라벨 객체의 y가 막대 끝 바깥인지 잰다."""
    csv = tmp_path / "neg.csv"
    csv.write_text("sample,val\nA,-14.5\nB,-1.85\nC,-23.2\n", encoding="utf-8")
    spec = {
        "id": "neg", "donor": "bar_labeled", "data": str(csv),
        "x": "sample", "y": "val", "y_title": "eV", "y_range": "auto",
    }
    wanted = {"-14.5": -14.5, "-1.85": -1.85, "-23.2": -23.2}
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        placed = {}
        for o in op.find_graph(page)[0].obj.GraphObjects:
            text = (o.Text or "").strip()
            for label, value in wanted.items():
                if label in text:
                    placed[label] = o.GetNumProp("y")
        y_from, y_to = op.lt_float("layer.y.from"), op.lt_float("layer.y.to")

    assert set(placed) == set(wanted), f"라벨을 다 못 찾았다: {placed}"
    for label, value in wanted.items():
        assert placed[label] < value, (
            f"{label}: 라벨 중심 y={placed[label]} 이 막대 끝 {value} 위에 있다 "
            f"(음수 막대 안쪽)")

    # 축이 0을 물어야 막대 길이가 크기를 나타낸다 (compute_range 의 0 앵커).
    assert y_to == 0.0, f"axis {y_from}..{y_to} does not reach the 0 baseline"
