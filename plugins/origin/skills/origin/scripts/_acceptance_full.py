"""인수 산출물: title + colors + annotation 을 모두 쓴 레시피 하나를 끝까지 돌린다.

    python scripts/_acceptance_full.py

결과:
  tests/_acceptance/water_solubility_full.png   (width=1000)
  tests/_acceptance/water_solubility_full.opju  (op.save — 반환값 확인)

두 번째 단계로 **새 세션에서 .opju 를 다시 열어** 그래프·데이터·house style이
보존됐는지 재측정한다. 저장 시점의 메모리 상태가 아니라 디스크에 내려간 것이
살아 있는지를 확인하는 것이 목적이다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import build_graph, load_recipe  # noqa: E402
from originsession import origin_session  # noqa: E402
from style import load_house_style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "tests" / "fixtures" / "water_solubility_full.yaml"
OUT_DIR = ROOT / "tests" / "_acceptance"

# 레시피가 참조하는 데이터 (재오픈 검증에서 대조한다).
WANT_VALUES = [14.5, 1.85, 23.2]
WANT_TEXT = ("Water solubility", "lowest", "14.5", "1.85", "23.2")


def build(recipe) -> Path:
    png = OUT_DIR / f"{recipe['output']}.png"
    opju = OUT_DIR / f"{recipe['output']}.opju"
    # 목적지를 먼저 비운다 — 남아 있으면 저장 실패를 파일 존재로 오판한다.
    for stale in (png, opju):
        if stale.exists():
            stale.unlink()

    with origin_session() as op:
        for spec in recipe["graphs"]:
            if spec.get("donor_inferred"):
                print(f"  donor inferred for {spec['id']!r}: {spec['donor']}")
            page = build_graph(op, spec, style_mode=recipe["style"])
            target = str(png.resolve()).replace("\\", "/")
            if not op.find_graph(page).save_fig(target, width=1000) or not png.exists():
                raise RuntimeError(f"save_fig produced nothing for {spec['id']!r}")
            print(f"  {spec['id']:<12} -> {png}  ({png.stat().st_size:,} bytes)")

            op.lt_exec(f"win -a {page};")
            print(f"    y range = {op.lt_float('layer.y.from')} .. "
                  f"{op.lt_float('layer.y.to')} (inc {op.lt_float('layer.y.inc')})")
            layer = op.find_graph(page)[0]
            print(f"    plots   = {[p.color for p in layer.plot_list()]}")
            print(f"    texts   = {[o.Text for o in layer.obj.GraphObjects if o.Text]}")

        if not op.save(str(opju.resolve())) or not opju.exists():
            raise RuntimeError(f"op.save produced nothing at {opju}")
    print(f"  project     -> {opju}  ({opju.stat().st_size:,} bytes)")
    return opju


class OpenFailed(RuntimeError):
    """`op.open` 이 False. 세션을 새로 잡으면 풀릴 수 있다 (아래 참조)."""


def reopen(opju: Path, attempts: int = 3) -> None:
    """새 세션에서 다시 열어 그래프·데이터·house style을 재측정한다.

    같은 프로세스에서 세션을 이어 열면 `op.open` 이 **간헐적으로** False를 돌려준다
    (실측 2026-07-29: 같은 파일이 새 프로세스에서는 즉시 열렸고, 재실행에서는 같은
    경로가 그대로 통과했다). 열기 실패만 세션을 새로 잡아 다시 시도하고,
    **검증 실패는 재시도하지 않는다** — 재시도로 가려 버리면 검증이 무의미해진다.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return _reopen_once(opju)
        except OpenFailed as e:
            last = e
            print(f"  [retry] {e}")
            time.sleep(1.5 * (i + 1))
    raise last


def _reopen_once(opju: Path) -> None:
    house = load_house_style()
    with origin_session() as op:
        if not op.open(str(opju.resolve()), readonly=False):
            raise OpenFailed(f"could not reopen {opju.name}")

        graphs = op.graph_list()
        if not graphs:
            raise RuntimeError("reopened project has no graph page")
        gname = graphs[0].name
        op.lt_exec(f"win -a {gname};")
        layer = op.find_graph(gname)[0]

        measured = {
            "layer.x.thickness": op.lt_float("layer.x.thickness"),
            "layer.y.thickness": op.lt_float("layer.y.thickness"),
            "layer.y.label.pt": op.lt_float("layer.y.label.pt"),
            "layer.y.label.bold": op.lt_float("layer.y.label.bold"),
            "layer.y.ticks": op.lt_float("layer.y.ticks"),
            "YL.fsize": op.lt_float("YL.fsize"),
        }
        colors = [p.color for p in layer.plot_list()]
        texts = [o.Text or "" for o in layer.obj.GraphObjects if o.Text]
        y_title = op.get_lt_str("YL.text$")

        from build import find_worksheet
        wks = find_worksheet(op)
        if wks is None:
            raise RuntimeError("reopened project has no worksheet")
        df = wks.to_df()
        values = sorted(float(v) for v in df.iloc[:, 1].dropna())
        categories = [str(c) for c in df.iloc[:, 0]]

    print(f"\n  reopened {opju.name}")
    print(f"    graph      = {gname}")
    print(f"    categories = {categories}")
    print(f"    values     = {values}")
    print(f"    y title    = {y_title!r}")
    print(f"    plots      = {colors}")
    print(f"    texts      = {texts}")
    print(f"    style      = {measured}")

    problems = []
    if values != sorted(WANT_VALUES):
        problems.append(f"data lost: {values} != {sorted(WANT_VALUES)}")
    if categories != ["α-CD", "β-CD", "γ-CD"]:
        problems.append(f"categories lost: {categories}")
    joined = "\n".join(texts)
    for wanted in WANT_TEXT:
        if wanted not in joined:
            problems.append(f"text lost: {wanted!r}")
    if (128, 128, 128) not in colors or (178, 34, 34) not in colors:
        problems.append(f"colours lost: {colors}")
    want_style = {
        "layer.x.thickness": float(house["axis_thickness"]),
        "layer.y.thickness": float(house["axis_thickness"]),
        "layer.y.label.pt": float(house["tick_label_pt"]),
        "layer.y.label.bold": 1.0,
        "layer.y.ticks": float(house["tick_bitmask"][house["tick_direction"]]),
        "YL.fsize": float(house["axis_title_pt"]),
    }
    for key, want in want_style.items():
        if measured[key] != want:
            problems.append(f"house style lost: {key} = {measured[key]} (want {want})")

    if problems:
        raise RuntimeError("reopen check failed:\n  - " + "\n  - ".join(problems))
    print("    OK: 그래프 / 데이터 / house style 전부 보존됨")


def main() -> None:
    recipe = load_recipe(RECIPE)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opju = build(recipe)
    reopen(opju)


if __name__ == "__main__":
    main()
