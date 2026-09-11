"""레시피 선택 필드(title / colors / annotation)와 donor 자동 추론."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build import build_graph, load_recipe  # noqa: E402
from originsession import origin_session  # noqa: E402

CSV = "cyclodextrin,solubility\nalpha-CD,14.5\nbeta-CD,1.85\ngamma-CD,23.2\n"


def _write(tmp_path, extra="", donor='    donor: bar_labeled\n'):
    data = tmp_path / "d.csv"
    data.write_text(CSV, encoding="utf-8")
    p = tmp_path / "r.yaml"
    p.write_text(
        "output: t\nstyle: house\ngraphs:\n  - id: g\n"
        f"{donor}"
        f"    data: {data.as_posix()}\n"
        "    x: cyclodextrin\n    y: solubility\n"
        '    y_title: "g / 100 mL"\n    y_range: auto\n' + extra,
        encoding="utf-8",
    )
    return p


def test_recipe_without_new_fields_is_unchanged(tmp_path):
    spec = load_recipe(_write(tmp_path))["graphs"][0]
    assert "title" not in spec
    assert "colors" not in spec
    assert "annotation" not in spec
    assert not spec.get("donor_inferred")


def test_donor_is_inferred_when_absent(tmp_path):
    spec = load_recipe(_write(tmp_path, donor=""))["graphs"][0]
    assert spec["donor"] == "bar_labeled"
    assert spec["donor_inferred"] is True


def test_duplicate_graph_ids_are_refused(tmp_path):
    """실패해야 정상(수정 전): id가 개별 `.opju` 이름이라 뒤엣것이 앞엣것을 덮어썼다.

    덱에는 같은 그래프가 두 번 박히고, 하나는 통째로 사라진다.
    """
    data = tmp_path / "d.csv"
    data.write_text(CSV, encoding="utf-8")
    p = tmp_path / "dup.yaml"
    body = (f"    donor: bar_labeled\n    data: {data.as_posix()}\n"
            "    x: cyclodextrin\n    y: solubility\n")
    p.write_text("output: t\nstyle: house\ngraphs:\n"
                 f"  - id: same\n{body}  - id: same\n{body}", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate graph id 'same'"):
        load_recipe(p)


def test_different_ids_are_fine(tmp_path):
    """항진명제 방지: 서로 다른 id는 그대로 통과해야 한다."""
    data = tmp_path / "d.csv"
    data.write_text(CSV, encoding="utf-8")
    p = tmp_path / "two.yaml"
    body = (f"    donor: bar_labeled\n    data: {data.as_posix()}\n"
            "    x: cyclodextrin\n    y: solubility\n")
    p.write_text("output: t\nstyle: house\ngraphs:\n"
                 f"  - id: a\n{body}  - id: b\n{body}", encoding="utf-8")
    assert [g["id"] for g in load_recipe(p)["graphs"]] == ["a", "b"]


def test_highlight_category_must_exist(tmp_path):
    """실패해야 정상: 없는 범주를 강조하라는 요청을 조용히 무시하지 않는다."""
    extra = ('    colors:\n      base: "#808080"\n      highlight:\n'
             '        category: "delta-CD"\n        color: "#B22222"\n')
    with pytest.raises(ValueError, match="colors.highlight.category"):
        load_recipe(_write(tmp_path, extra))


def test_annotation_at_must_exist(tmp_path):
    """실패해야 정상: 없는 범주를 가리키는 주석도 즉시 중단."""
    extra = ('    annotation:\n      text: "x"\n      at: "delta-CD"\n')
    with pytest.raises(ValueError, match="annotation.at"):
        load_recipe(_write(tmp_path, extra))


def test_existing_category_passes_validation(tmp_path):
    extra = ('    colors:\n      base: "#808080"\n      highlight:\n'
             '        category: "beta-CD"\n        color: "#B22222"\n'
             '    annotation:\n      text: "x"\n      at: "beta-CD"\n')
    spec = load_recipe(_write(tmp_path, extra))["graphs"][0]
    assert spec["colors"]["highlight"]["category"] == "beta-CD"


@pytest.mark.origin
def test_title_becomes_a_text_object(tmp_path):
    spec = load_recipe(_write(tmp_path, '    title: "Water solubility"\n'))["graphs"][0]
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        texts = [o.Text or "" for o in op.find_graph(page)[0].obj.GraphObjects]
    # 굵게는 `\b(...)` 이스케이프로 들어가므로 완전일치가 아니라 포함으로 본다.
    assert any("Water solubility" in t for t in texts), texts


@pytest.mark.origin
def test_colors_land_on_the_plots(tmp_path):
    extra = ('    colors:\n      base: "#808080"\n      highlight:\n'
             '        category: "beta-CD"\n        color: "#B22222"\n')
    spec = load_recipe(_write(tmp_path, extra))["graphs"][0]
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        plots = op.find_graph(page)[0].plot_list()
        colors = [p.color for p in plots]
    assert len(plots) == 2, "highlight should add an overlay plot"
    assert colors[0] == (128, 128, 128)
    assert colors[1] == (178, 34, 34)


@pytest.mark.origin
def test_annotation_becomes_a_text_object(tmp_path):
    extra = ('    annotation:\n      text: "lowest"\n      at: "beta-CD"\n'
             '      color: "#B22222"\n')
    spec = load_recipe(_write(tmp_path, extra))["graphs"][0]
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        texts = [o.Text or "" for o in op.find_graph(page)[0].obj.GraphObjects]
    assert any("lowest" in t for t in texts), texts
