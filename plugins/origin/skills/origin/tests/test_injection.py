"""워크시트 주입의 계약: 남는 donor 컬럼, 워크시트 없는 donor, 잘리는 데이터."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build import (AxisClipWarning, build_graph, buildable_donors,  # noqa: E402
                   donor_has_worksheet, load_recipe)
from originsession import origin_session  # noqa: E402


class _Untouchable:
    """Origin 핸들 자리에 놓는다. 건드리는 순간 실패한다."""

    def __getattr__(self, name):
        raise AssertionError(f"Origin을 건드렸다: op.{name}")

DONORS = ROOT / "donors"
FIX = Path(__file__).resolve().parent / "fixtures"

# 워크시트가 통째로 없는 donor (실측 2026-07-29: op.pages('w') 가 비어 있다).
NO_WORKSHEET = ("log_axis", "errorbar")


# ------------------------------------------------ 워크시트 없는 donor (C6)

@pytest.mark.parametrize("name", NO_WORKSHEET)
def test_manifest_records_the_missing_worksheet(name):
    """manifest는 '읽기 실패'가 아니라 '워크시트 없음'이라고 정직하게 적어야 한다."""
    m = yaml.safe_load((DONORS / f"{name}.yaml").read_text(encoding="utf-8"))
    assert m["data_shape"]["has_worksheet"] is False
    assert m["data_shape"]["x_type"] == "none"
    assert not donor_has_worksheet(name)


@pytest.mark.parametrize("name", ["bar_labeled", "bar_grouped", "floating_bar",
                                  "line_symbol", "waterfall", "annotated",
                                  "double_y", "broken_axis"])
def test_the_other_donors_do_have_a_worksheet(name):
    assert donor_has_worksheet(name)
    assert name in buildable_donors()


@pytest.mark.parametrize("name", NO_WORKSHEET)
def test_a_recipe_naming_a_worksheetless_donor_fails_before_origin_starts(tmp_path, name):
    """실패해야 정상: 전에는 `RuntimeError: no worksheet` 가 런타임에 터졌다.

    이제는 Origin을 띄우기도 전에, 왜 안 되는지와 무엇을 쓸 수 있는지를 말해 준다.
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: {name}\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: sample\n"
        f"    y: pugh_ratio\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="has no worksheet"):
        load_recipe(p)


def test_naming_a_worksheetless_donor_says_the_user_requested_it(tmp_path):
    """명시와 추론은 메시지로 구분된다 — 사용자가 고른 것과 우리가 고른 것은 다르다."""
    p = tmp_path / "r.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: log_axis\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: sample\n"
        f"    y: pugh_ratio\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requested donor"):
        load_recipe(p)


# ----------------------------- 추론이 빌드 불가 donor에 도달했을 때 (부분 실패)

def _inferred_log_axis(tmp_path, extra_graph=""):
    """donor를 적지 않고, x가 3자릿수 이상 퍼진 데이터 → 추론이 log_axis 로 간다."""
    csv = tmp_path / "sweep.csv"
    csv.write_text("freq,z\n1,10\n100,20\n100000,30\n", encoding="utf-8")
    good = tmp_path / "cats.csv"
    good.write_text("sample,val\nA,1.0\nB,2.0\nC,3.0\n", encoding="utf-8")
    p = tmp_path / "r.yaml"
    p.write_text(
        "output: x\nstyle: house\ngraphs:\n"
        "  - id: eis\n"
        f"    data: {csv.as_posix()}\n    x: freq\n    y: z\n"
        + extra_graph.format(good=good.as_posix()),
        encoding="utf-8",
    )
    return p


def test_an_inferred_dead_end_does_not_kill_the_whole_recipe(tmp_path):
    """실패해야 정상(수정 전): 추론이 log_axis 에 닿으면 `load_recipe` 가 통째로
    죽어서, 같은 레시피의 멀쩡한 그래프까지 하나도 못 만들었다.

    `paste.py` 가 세운 '부분 실패는 건너뛰고 n/total로 보고한다' 계약과 정면 충돌한다.
    """
    other = ("  - id: fine\n    donor: bar_labeled\n"
             "    data: {good}\n    x: sample\n    y: val\n")
    recipe = load_recipe(_inferred_log_axis(tmp_path, other))    # 죽지 않는다

    bad, fine = recipe["graphs"]
    assert bad["donor"] == "log_axis" and bad["donor_inferred"] is True
    assert "has no worksheet" in bad["build_error"]
    assert "inferred donor" in bad["build_error"]
    assert not fine.get("build_error"), "멀쩡한 그래프까지 실패로 표시됐다"


def test_the_deferred_failure_lands_when_that_graph_is_built(tmp_path):
    """미뤄 둔 실패는 반드시 터져야 한다 — 조용히 통과하면 빈 그래프가 덱에 박힌다.

    Origin은 띄우지도 않는다 (핸들을 건드리면 `_Untouchable` 이 잡는다).
    """
    spec = load_recipe(_inferred_log_axis(tmp_path))["graphs"][0]
    with pytest.raises(RuntimeError, match="has no worksheet"):
        build_graph(_Untouchable(), spec, style_mode="house")


def test_a_healthy_spec_carries_no_deferred_failure(tmp_path):
    """항진명제 방지: build_error 가 아무 데나 붙으면 위 테스트가 무의미하다."""
    p = tmp_path / "r.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: sample\n"
        f"    y: pugh_ratio\n",
        encoding="utf-8",
    )
    spec = load_recipe(p)["graphs"][0]
    assert spec["donor"] == "bar_labeled"
    assert "build_error" not in spec


def test_the_error_names_a_donor_that_actually_works(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: log_axis\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: sample\n"
        f"    y: pugh_ratio\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as e:
        load_recipe(p)
    assert "bar_labeled" in str(e.value)
    for name in NO_WORKSHEET:
        assert f"'{name}'," not in str(e.value).split("usable donors:")[-1]


# ------------------------------------------------------- 잘리는 데이터 (C8)

def _recipe(tmp_path, y_range: str, values="2.38\n1.61\n1.97"):
    csv = tmp_path / "d.csv"
    rows = "\n".join(f"S{i},{v}" for i, v in enumerate(values.split("\n")))
    csv.write_text(f"sample,val\n{rows}\n", encoding="utf-8")
    p = tmp_path / "r.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: clipme\n    donor: bar_labeled\n"
        f"    data: {csv.as_posix()}\n    x: sample\n    y: val\n"
        f"    y_range: {y_range}\n",
        encoding="utf-8",
    )
    return load_recipe(p)["graphs"][0]


@pytest.mark.origin
def test_inherit_warns_when_the_new_data_escapes_the_donor_axis(tmp_path):
    """donor 축(0..3)을 넘는 데이터를 상속 범위에 밀어 넣으면 조용히 잘린다."""
    spec = _recipe(tmp_path, "inherit", values="2.38\n1.61\n9.9")
    with origin_session() as op:
        with pytest.warns(AxisClipWarning, match="clipped"):
            build_graph(op, spec, style_mode="house")


@pytest.mark.origin
def test_inherit_is_silent_when_the_data_fits(tmp_path):
    """경고가 항상 나오면 아무 정보도 주지 못한다 — 맞는 데이터엔 조용해야 한다."""
    import warnings

    spec = _recipe(tmp_path, "inherit")
    with origin_session() as op:
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            build_graph(op, spec, style_mode="house")
    assert not [w for w in seen if issubclass(w.category, AxisClipWarning)]


@pytest.mark.origin
def test_a_fixed_range_that_cuts_the_data_also_warns(tmp_path):
    spec = _recipe(tmp_path, "[0, 2]", values="2.38\n1.61\n1.97")
    with origin_session() as op:
        with pytest.warns(AxisClipWarning, match="2.38"):
            build_graph(op, spec, style_mode="house")


# --------------------------------------------- donor의 남는 컬럼 (C5)

@pytest.mark.origin
def test_leftover_donor_columns_do_not_keep_drawing(tmp_path):
    """회귀: `from_df` 는 컬럼을 늘리기만 하고 줄이지 않는다.

    bar_grouped donor는 컬럼 3개(x + y 2개)에 plot 2개다. y 하나짜리 데이터를 넣으면
    수정 전에는 donor의 C 컬럼과 그것을 그리는 plot이 그대로 살아남아, 우리가 넣지도
    않은 계열이 그래프에 남았다.
    """
    csv = tmp_path / "one_y.csv"
    csv.write_text("sample,dft\nA,1.0\nB,2.0\nC,3.0\n", encoding="utf-8")
    spec = {
        "id": "trim", "donor": "bar_grouped", "data": str(csv),
        "x": "sample", "y": "dft", "y_range": "auto",
    }
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        plots = len(op.find_graph(page)[0].plot_list())
        from build import find_worksheet
        cols = int(find_worksheet(op).cols)

    assert cols == 2, f"워크시트에 남는 컬럼이 있다: {cols} (기대 2)"
    assert plots == 1, f"donor의 남는 plot이 계속 그리고 있다: {plots}개 (기대 1)"


@pytest.mark.origin
def test_trimming_does_not_touch_a_donor_that_already_fits(tmp_path):
    """컬럼 수가 같으면 아무것도 지우지 않는다 (골든 이미지 경로 보호)."""
    csv = tmp_path / "two.csv"
    csv.write_text("sample,val\nA,1.0\nB,2.0\nC,3.0\n", encoding="utf-8")
    spec = {
        "id": "fit", "donor": "bar_labeled", "data": str(csv),
        "x": "sample", "y": "val", "y_range": "auto",
    }
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        plots = len(op.find_graph(page)[0].plot_list())
        from build import find_worksheet
        cols = int(find_worksheet(op).cols)
    assert (cols, plots) == (2, 1)
