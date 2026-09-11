"""floating bar 아키타입과 새 레시피 필드.

순수 함수(프레임 구성 / 밴드 좌표 / 라벨 포맷)와 레시피 검증은 Origin 없이 돈다.
그래프를 실제로 만드는 것만 `@pytest.mark.origin` 이다.
"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import decorate  # noqa: E402
from build import (build_graph, category_x_range, floating_frame,  # noqa: E402
                   is_floating, load_recipe, spec_ycols)
from originsession import origin_session  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
CSV = "molecule,e_red,e_ox\nM1,-1.25,5.55\nM2,-0.58,5.61\n"

BASE = """output: t
style: house
graphs:
  - id: esw
    donor: floating_bar
    data: {data}
    x: molecule
    y_low: {low}
    y_high: e_ox
    y_range: [-2, 7]
"""


def _write(tmp_path, extra="", low="e_red"):
    data = tmp_path / "d.csv"
    data.write_text(CSV, encoding="utf-8")
    p = tmp_path / "r.yaml"
    p.write_text(BASE.format(data=data.as_posix(), low=low) + extra, encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# 순수 함수
# --------------------------------------------------------------------------

def test_floating_frame_splits_one_pair_per_category():
    f = floating_frame("mol", ["A", "B", "C"], [-1, 0, 1], [4, 5, 6])
    assert list(f.columns) == ["mol", "lo_1", "hi_1", "lo_2", "hi_2", "lo_3", "hi_3"]
    assert list(f["mol"]) == ["A", "B", "C"]
    # 각 쌍은 자기 행에만 값이 있다 — 그래야 막대마다 독립된 plot이 생긴다.
    assert f["lo_2"].tolist()[1] == 0.0
    assert math.isnan(f["lo_2"].tolist()[0])
    assert math.isnan(f["hi_2"].tolist()[2])


def test_floating_frame_applies_two_line_x_labels():
    f = floating_frame("mol", ["A", "B"], [0, 0], [1, 1], {"A": "A\n(first)"})
    assert list(f["mol"]) == ["A\n(first)", "B"]


def test_spec_ycols_rejects_mixing_y_and_the_pair():
    with pytest.raises(ValueError, match="mutually exclusive"):
        spec_ycols({"y": "a", "y_low": "b", "y_high": "c"})


def test_spec_ycols_rejects_a_half_pair():
    with pytest.raises(ValueError, match="must be given together"):
        spec_ycols({"y_low": "b"})


def test_spec_ycols_rejects_no_y_at_all():
    with pytest.raises(ValueError, match="either y or y_low"):
        spec_ycols({"x": "a"})


def test_is_floating():
    assert is_floating({"y_low": "a", "y_high": "b"})
    assert not is_floating({"y": "a"})


def test_band_rect_geometry():
    xc, yc, dx, dy = decorate.band_rect({"from": 3.0, "to": 4.3}, 0.5, 2.5)
    assert (xc, yc) == (1.5, 3.65)
    assert dx == 2.0
    assert dy == pytest.approx(1.3)


def test_band_rect_rejects_reversed_range():
    """실패해야 정상: from > to 는 높이가 음수인 사각형이라 조용히 그리면 안 된다."""
    with pytest.raises(ValueError, match="needs from < to"):
        decorate.band_rect({"from": 4.3, "to": 3.0}, 0.5, 2.5)


def test_band_rect_rejects_equal_bounds():
    with pytest.raises(ValueError, match="needs from < to"):
        decorate.band_rect({"from": 3.0, "to": 3.0}, 0.5, 2.5)


def test_validate_band_rejects_bad_side_and_alpha():
    with pytest.raises(ValueError, match="label_side"):
        decorate.validate_band({"from": 1, "to": 2, "label_side": "up"}, "bands[0]")
    with pytest.raises(ValueError, match="alpha"):
        decorate.validate_band({"from": 1, "to": 2, "alpha": 3}, "bands[0]")


def test_transparency_is_the_complement_of_alpha():
    assert decorate.transparency_of(0.35) == 65.0
    assert decorate.transparency_of(1.0) == 0.0
    assert decorate.transparency_of(None) == 0.0


def test_format_value_label():
    assert decorate.format_value_label("Eox {v:.2f} V", 5.55) == "Eox 5.55 V"
    assert decorate.format_value_label(None, 5.5) == "5.5"
    assert decorate.format_value_label(None, 5.0) == "5"


def test_format_value_label_rejects_a_format_that_drops_the_value():
    """실패해야 정상: {v} 를 안 쓰는 포맷은 값을 잃어버린 것이다."""
    with pytest.raises(ValueError, match="does not reference"):
        decorate.format_value_label("Eox V", 5.55)


def test_format_value_label_rejects_a_broken_spec():
    with pytest.raises(ValueError, match="invalid value label format"):
        decorate.format_value_label("{v:.2q}", 5.55)


def test_category_x_range_follows_the_category_count():
    """donor에는 자기 범주 수(2개)에 맞는 [0.5, 2.5]가 구워져 있다.

    범주가 3개 이상인데 그대로 두면 뒤쪽 막대가 축 밖으로 나가 잘린다.
    """
    assert category_x_range(2) == (0.5, 2.5)      # donor 원본과 같아야 한다
    assert category_x_range(3) == (0.5, 3.5)
    assert category_x_range(4) == (0.5, 4.5)


def test_category_x_range_rejects_an_empty_frame():
    with pytest.raises(ValueError, match="at least one category"):
        category_x_range(0)


# ------------------------------------------- 빈 셀이 섞인 범위 막대 (NaN)

class _FakeGraphObjects:
    def __init__(self):
        self.made = []

    def Add(self, kind):
        obj = _FakeObj(f"Rect{len(self.made) + 1}")
        self.made.append(obj)
        return obj


class _FakeObj:
    def __init__(self, name):
        self.Name = name

    def SetNumProp(self, key, value):
        return True


class _FakeLayer:
    def __init__(self):
        self.objects = _FakeGraphObjects()
        self.obj = type("Holder", (), {"GraphObjects": self.objects})()


class _FakeOp:
    def __init__(self):
        self.cmds = []

    def lt_exec(self, cmd):
        self.cmds.append(cmd)
        return True


def test_floating_bars_skip_rows_with_a_blank_cell():
    """실패해야 정상(수정 전): 빈 셀이 `dy = nan` 인 Rect로 나가 그래프가 통째로 죽었다."""
    op, layer = _FakeOp(), _FakeLayer()
    series = {"A": {"line": "#000000", "fill": "#ffffff"},
              "B": {"line": "#000000", "fill": "#ffffff"}}
    made = decorate.draw_floating_bars(
        op, layer, [1, 2], [1.0, float("nan")], [2.0, 5.0], ["A", "B"], series)

    assert len(made) == 1, "빈 셀 행에도 막대를 그렸다"
    assert not [c for c in op.cmds if "nan" in c.lower()], op.cmds


def test_floating_bars_skip_a_blank_upper_end_too():
    op, layer = _FakeOp(), _FakeLayer()
    series = {"A": {"line": "#000000"}}
    made = decorate.draw_floating_bars(
        op, layer, [1], [1.0], [float("nan")], ["A"], series)
    assert made == []
    assert not [c for c in op.cmds if "nan" in c.lower()], op.cmds


def test_floating_bars_still_draw_when_the_data_is_complete():
    """항진명제 방지: 전부 건너뛰는 구현이면 위 테스트는 무의미하다."""
    op, layer = _FakeOp(), _FakeLayer()
    series = {"A": {"line": "#000000"}, "B": {"line": "#000000"}}
    made = decorate.draw_floating_bars(
        op, layer, [1, 2], [1.0, 2.0], [3.0, 4.0], ["A", "B"], series)
    assert len(made) == 2


def test_anchor_keywords():
    assert decorate.is_anchor("top_center")
    assert not decorate.is_anchor("beta-CD")
    assert decorate.anchor_x("top_center", 0.5, 2.5) == 1.5
    assert decorate.anchor_x("top_left", 0.0, 10.0) == 1.5
    assert decorate.anchor_x("top_right", 0.0, 10.0) == 8.5
    with pytest.raises(ValueError, match="not a position keyword"):
        decorate.anchor_x("middle", 0, 1)


# --------------------------------------------------------------------------
# 레시피 검증 — 전부 "실패해야 정상"
# --------------------------------------------------------------------------

def test_recipe_rejects_a_missing_y_low_column(tmp_path):
    with pytest.raises(ValueError, match="column 'nope' not found"):
        load_recipe(_write(tmp_path, low="nope"))


def test_recipe_rejects_an_unknown_x_label_category(tmp_path):
    extra = '    x_labels:\n      M3: "M3\\n(none)"\n'
    with pytest.raises(ValueError, match="x_labels"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_rejects_an_unknown_series_category(tmp_path):
    extra = ('    colors:\n      series:\n'
             '        M3: {line: "#000000", fill: "#ffffff"}\n')
    with pytest.raises(ValueError, match="colors.series"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_rejects_a_reversed_band(tmp_path):
    extra = "    bands:\n      - from: 4.3\n        to: 3.0\n"
    with pytest.raises(ValueError, match=r"bands\[0\] needs from < to"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_rejects_a_missing_value_label_source(tmp_path):
    extra = '    value_labels:\n      top: {source: nope, format: "{v}"}\n'
    with pytest.raises(ValueError, match="value_labels.top.source"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_rejects_a_value_label_format_without_the_value(tmp_path):
    extra = '    value_labels:\n      top: {source: e_ox, format: "Eox"}\n'
    with pytest.raises(ValueError, match="does not reference"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_rejects_an_unknown_value_label_slot(tmp_path):
    extra = '    value_labels:\n      middle: {source: e_ox}\n'
    with pytest.raises(ValueError, match="'top' or 'bottom'"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_still_rejects_an_unknown_annotation_category(tmp_path):
    """위치 키워드를 허용해도 오타 범주는 여전히 잡아야 한다."""
    extra = '    annotation:\n      text: "x"\n      at: "M9"\n'
    with pytest.raises(ValueError, match="annotation.at"):
        load_recipe(_write(tmp_path, extra))


def test_recipe_accepts_a_position_keyword_for_the_annotation(tmp_path):
    extra = '    annotation:\n      text: "x"\n      at: top_center\n'
    spec = load_recipe(_write(tmp_path, extra))["graphs"][0]
    assert spec["annotation"]["at"] == "top_center"


def test_floating_donor_is_inferred_from_the_column_pair(tmp_path):
    p = _write(tmp_path)
    text = p.read_text(encoding="utf-8").replace("    donor: floating_bar\n", "")
    p.write_text(text, encoding="utf-8")
    spec = load_recipe(p)["graphs"][0]
    assert spec["donor"] == "floating_bar"
    assert spec["donor_inferred"] is True


# ------------------------- floating 전용 필드를 일반 donor에 적었을 때 (거부)

BAR = """output: t
style: house
graphs:
  - id: g
    donor: bar_labeled
    data: {data}
    x: sample
    y: val
"""


def _bar_recipe(tmp_path, extra=""):
    data = tmp_path / "bar.csv"
    data.write_text("sample,val,other\nA,1.0,9\nB,2.0,8\nC,3.0,7\n", encoding="utf-8")
    p = tmp_path / "bar.yaml"
    p.write_text(BAR.format(data=data.as_posix()) + extra, encoding="utf-8")
    return p


@pytest.mark.parametrize("field,extra", [
    ("subtitle", '    subtitle: "sub"\n'),
    ("bands", "    bands:\n      - from: 1.0\n        to: 2.0\n"),
    ("value_labels", '    value_labels:\n      top: {source: other}\n'),
    ("x_labels", '    x_labels:\n      A: "A\\n(first)"\n'),
    ("colors.series", '    colors:\n      series:\n'
                      '        A: {line: "#000000", fill: "#ffffff"}\n'),
])
def test_floating_only_fields_are_refused_on_a_normal_donor(tmp_path, field, extra):
    """실패해야 정상(수정 전): 검증만 통과하고 렌더에서 **조용히 사라졌다.**

    그리는 코드가 floating 경로에만 있는데 SKILL.md는 범용 필드로 소개했다.
    구현하지 않을 것이면 받지도 말아야 한다.
    """
    with pytest.raises(ValueError, match="floating bar path"):
        load_recipe(_bar_recipe(tmp_path, extra))


def test_the_refusal_names_the_offending_field(tmp_path):
    with pytest.raises(ValueError) as e:
        load_recipe(_bar_recipe(tmp_path, '    subtitle: "sub"\n'))
    assert "subtitle" in str(e.value)


def test_a_normal_donor_still_takes_the_fields_it_implements(tmp_path):
    """항진명제 방지: title/colors/annotation 은 일반 donor에서도 동작한다."""
    extra = ('    title: "T"\n'
             '    colors:\n      base: "#808080"\n'
             '    annotation:\n      text: "x"\n      at: "A"\n')
    spec = load_recipe(_bar_recipe(tmp_path, extra))["graphs"][0]
    assert spec["title"] == "T"


def test_floating_recipes_still_accept_those_fields(tmp_path):
    """거부가 floating 경로까지 막으면 esw 레시피가 통째로 죽는다."""
    extra = ('    subtitle: "sub"\n'
             '    x_labels:\n      M1: "M1\\n(unit)"\n'
             '    bands:\n      - from: 3.0\n        to: 4.3\n'
             '    value_labels:\n      top: {source: e_ox}\n')
    spec = load_recipe(_write(tmp_path, extra))["graphs"][0]
    assert spec["subtitle"] == "sub"


def test_the_full_esw_recipe_loads():
    recipe = load_recipe(FIX / "esw_window.yaml")
    spec = recipe["graphs"][0]
    assert spec["donor"] == "floating_bar"
    assert spec["y_low"] == "e_red" and spec["y_high"] == "e_ox"
    assert not spec.get("donor_inferred")


# --------------------------------------------------------------------------
# Origin 필요
# --------------------------------------------------------------------------

@pytest.mark.origin
def test_esw_graph_carries_every_requested_element(tmp_path):
    spec = load_recipe(FIX / "esw_window.yaml")["graphs"][0]
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        layer = op.find_graph(page)[0]
        colors = [p.color for p in layer.plot_list()]
        names = [o.Name for o in layer.obj.GraphObjects]
        texts = [o.Text or "" for o in layer.obj.GraphObjects]
        y_from, y_to = op.lt_float("layer.y.from"), op.lt_float("layer.y.to")

    # 범주 2개 = 쌍 2개 = plot 4개, 각 쌍이 자기 채움색을 갖는다.
    assert len(colors) == 4, colors
    assert colors[0] == colors[1] == (191, 211, 236)
    assert colors[2] == colors[3] == (242, 198, 194)

    # 막대 테두리 2개 + 밴드 1개 = 사각형 3개
    assert len([n for n in names if n.startswith("Rect")]) == 3, names

    joined = "\n".join(texts)
    for wanted in ("Eox 5.55 V", "Ered -1.25 V", "Eox 5.61 V", "Ered -0.58 V",
                   "cathode", "B3LYP-D3BJ", "Electrochemical stability window",
                   "crosslinking raises"):
        assert wanted in joined, f"{wanted!r} missing from {texts}"

    assert (y_from, y_to) == (-2.0, 7.0)


FOUR = ("molecule,e_red,e_ox\n"
        "M1,-1.25,5.55\nM2,-0.58,5.61\nM3,-0.90,4.80\nM4,-1.60,6.20\n")

FOUR_RECIPE = """output: t
style: house
graphs:
  - id: four
    donor: floating_bar
    data: {data}
    x: molecule
    y_low: e_red
    y_high: e_ox
    y_range: [-2, 7]
"""


def _four(tmp_path, csv=FOUR):
    data = tmp_path / "four.csv"
    data.write_text(csv, encoding="utf-8")
    p = tmp_path / "four.yaml"
    p.write_text(FOUR_RECIPE.format(data=data.as_posix()), encoding="utf-8")
    return load_recipe(p)["graphs"][0]


@pytest.mark.origin
def test_more_categories_widen_the_x_axis(tmp_path):
    """실패해야 정상(수정 전): donor에 구워진 [0.5, 2.5] 가 그대로 남아 3·4번째
    막대가 축 밖으로 나갔다. y축만 관리하고 x축은 방치돼 있었다."""
    spec = _four(tmp_path)
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        op.lt_exec(f"win -a {page};")
        x_from, x_to = op.lt_float("layer.x.from"), op.lt_float("layer.x.to")
        plots = len(op.find_graph(page)[0].plot_list())

    assert (x_from, x_to) == (0.5, 4.5), "4번째 막대가 축 밖이다"
    assert plots == 8, f"범주 4개 = plot 8개여야 한다: {plots}"


@pytest.mark.origin
def test_three_categories_also_fit(tmp_path):
    csv = "molecule,e_red,e_ox\nM1,-1.25,5.55\nM2,-0.58,5.61\nM3,-0.90,4.80\n"
    spec = _four(tmp_path, csv)
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        op.lt_exec(f"win -a {page};")
        assert (op.lt_float("layer.x.from"), op.lt_float("layer.x.to")) == (0.5, 3.5)


@pytest.mark.origin
def test_a_blank_cell_does_not_kill_the_floating_graph(tmp_path):
    """회귀: `y_low` 가 빈 셀이면 `dy = nan` 인 Rect가 나가 그래프 전체가 실패했다.

    빈 행은 막대를 그리지 않고 넘어가고, 나머지 막대는 정상적으로 나와야 한다.
    """
    data = tmp_path / "gap.csv"
    data.write_text("molecule,e_red,e_ox\nM1,-1.25,5.55\nM2,,5.61\n", encoding="utf-8")
    p = tmp_path / "gap.yaml"
    p.write_text(
        BASE.format(data=data.as_posix(), low="e_red")
        + ('    colors:\n      series:\n'
           '        M1: {line: "#2E5FA3", fill: "#BFD3EC"}\n'
           '        M2: {line: "#C0392B", fill: "#F2C6C2"}\n'),
        encoding="utf-8",
    )
    spec = load_recipe(p)["graphs"][0]

    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")   # 예외 없이 완주해야 한다
        layer = op.find_graph(page)[0]
        names = [o.Name for o in layer.obj.GraphObjects]
        texts = [o.Text or "" for o in layer.obj.GraphObjects]

    rects = [n for n in names if n.startswith("Rect")]
    assert len(rects) == 1, f"빈 셀 행에도 막대를 그렸다: {rects}"
    assert "nan" not in "\n".join(texts).lower(), texts


@pytest.mark.origin
def test_floating_without_optional_fields_draws_no_extra_objects(tmp_path):
    """요청하지 않은 것은 건드리지 않는다 — 사각형도 글자도 생기면 안 된다."""
    spec = load_recipe(_write(tmp_path))["graphs"][0]
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        layer = op.find_graph(page)[0]
        names = [o.Name for o in layer.obj.GraphObjects]
        plots = len(layer.plot_list())
    assert plots == 4
    assert not [n for n in names if n.startswith("Rect")], names
    assert not [n for n in names if n.startswith("Text")], names
