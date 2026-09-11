import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build import build_graph, load_recipe  # noqa: E402
from originsession import origin_session  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
DONOR = ROOT / "donors" / "bar_labeled.opj"


def _recipe(tmp_path, style):
    p = tmp_path / "recipe.yaml"
    p.write_text(
        f"""
output: golden
style: {style}
graphs:
  - id: pugh
    donor: bar_labeled
    data: {(FIX / 'pugh.csv').as_posix()}
    x: sample
    y: pugh_ratio
    y_title: "Pugh's Ratio (B/G)"
    y_range: inherit
""",
        encoding="utf-8",
    )
    return p


def test_load_recipe_rejects_unknown_donor(tmp_path):
    """실패해야 정상: 없는 donor를 조용히 넘기지 않는다."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: no_such_donor\n"
        "    data: x.csv\n    x: a\n    y: b\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown donor"):
        load_recipe(p)


def test_load_recipe_rejects_missing_column(tmp_path):
    """실패해야 정상: 데이터에 없는 컬럼명은 즉시 중단."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: bar_labeled\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: nope\n    y: pugh_ratio\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="column 'nope' not found"):
        load_recipe(p)


def test_load_recipe_rejects_bad_style(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        f"output: x\nstyle: fancy\ngraphs:\n  - id: a\n    donor: bar_labeled\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: sample\n    y: pugh_ratio\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="style must be"):
        load_recipe(p)


# ------------------------------------------------------------------ y_range

def _y_range_recipe(tmp_path, y_range: str):
    p = tmp_path / "yr.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: bar_labeled\n"
        f"    data: {(FIX / 'pugh.csv').as_posix()}\n    x: sample\n"
        f"    y: pugh_ratio\n    y_range: {y_range}\n",
        encoding="utf-8",
    )
    return p


@pytest.mark.parametrize("y_range", ["auto", "inherit", "[0, 3]", "[-2.5, 7]"])
def test_load_recipe_accepts_the_documented_y_ranges(tmp_path, y_range):
    load_recipe(_y_range_recipe(tmp_path, y_range))


@pytest.mark.parametrize("y_range", ["atuo", "Auto", "donor", "none", "true"])
def test_load_recipe_rejects_an_unknown_y_range_keyword(tmp_path, y_range):
    """실패해야 정상: 오타가 조용히 'donor 범위 유지'로 흘러가면 원인을 못 찾는다.

    `style` 은 화이트리스트 검증을 하는데 `y_range` 만 안 하던 비대칭을 막는다.
    """
    with pytest.raises(ValueError, match="y_range must be"):
        load_recipe(_y_range_recipe(tmp_path, y_range))


@pytest.mark.parametrize("y_range,msg", [
    ("[1]", "exactly 2"),
    ("[1, 2, 3]", "exactly 2"),
    ("[a, b]", "must be numbers"),
    ("[3, 3]", "two different values"),
])
def test_load_recipe_rejects_a_malformed_y_range_list(tmp_path, y_range, msg):
    with pytest.raises(ValueError, match=msg):
        load_recipe(_y_range_recipe(tmp_path, y_range))


@pytest.mark.origin
def test_golden_inherit_matches_donor(tmp_path):
    """style: inherit + 원본 데이터 -> donor 원본과 픽셀 동일해야 한다."""
    from PIL import Image, ImageChops

    recipe = load_recipe(_recipe(tmp_path, "inherit"))
    spec = recipe["graphs"][0]

    with origin_session() as op:
        assert op.open(str(DONOR.resolve()), readonly=False)
        gname = op.graph_list()[0].name
        ref = str((tmp_path / "ref.png").resolve()).replace("\\", "/")
        op.find_graph(gname).save_fig(ref, width=800)

        got_page = build_graph(op, spec, style_mode="inherit")
        got = str((tmp_path / "got.png").resolve()).replace("\\", "/")
        op.find_graph(got_page).save_fig(got, width=800)

    a = Image.open(ref).convert("RGB")
    b = Image.open(got).convert("RGB")
    if a.size != b.size or ImageChops.difference(a, b).getbbox() is not None:
        debug = ROOT / "tests" / "_debug"
        debug.mkdir(parents=True, exist_ok=True)
        a.save(debug / "ref.png")
        b.save(debug / "got.png")
    assert a.size == b.size
    assert ImageChops.difference(a, b).getbbox() is None, "golden image drift"


@pytest.mark.origin
def test_house_mode_lands_style(tmp_path):
    """style: house -> 픽셀 비교가 아니라 속성 재측정으로 검증한다."""
    recipe = load_recipe(_recipe(tmp_path, "house"))
    spec = recipe["graphs"][0]
    with origin_session() as op:
        page = build_graph(op, spec, style_mode="house")
        op.lt_exec(f"win -a {page};")
        assert op.lt_float("layer.x.thickness") == 4.0
        assert op.lt_float("layer.y.ticks") == 5.0
        assert op.lt_float("YL.fsize") == 32.0


@pytest.mark.origin
def test_new_data_actually_reaches_the_graph(tmp_path):
    """실패해야 정상: 데이터를 안 갈아끼워도 통과하는 테스트가 되면 안 된다.
    donor 원본과 다른 값을 넣고, 워크시트에서 그 값이 읽히는지 확인한다."""
    csv = tmp_path / "other.csv"
    csv.write_text("sample,val\nA,9.1\nB,4.4\nC,7.7\n", encoding="utf-8")
    p = tmp_path / "r.yaml"
    p.write_text(
        f"output: x\nstyle: house\ngraphs:\n  - id: a\n    donor: bar_labeled\n"
        f"    data: {csv.as_posix()}\n    x: sample\n    y: val\n    y_range: auto\n",
        encoding="utf-8",
    )
    spec = load_recipe(p)["graphs"][0]
    with origin_session() as op:
        build_graph(op, spec, style_mode="house")
        wks = None
        for book in ("Book1", "Book2", "Book3"):
            wks = op.find_sheet("w", book)
            if wks is not None:
                break
        assert wks is not None
        df = wks.to_df()
        vals = sorted(float(v) for v in df.iloc[:, -1].dropna())
        assert vals == [4.4, 7.7, 9.1], f"data did not reach the worksheet: {vals}"
