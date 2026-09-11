"""인수 산출물: 전기화학 안정성 윈도우 (floating bar 아키타입).

    python scripts/_acceptance_esw.py

결과:
  tests/_acceptance/esw_window.png   (width=1000)
  tests/_acceptance/esw_window.opju  (op.save)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import build_graph, load_recipe  # noqa: E402
from originsession import origin_session  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "tests" / "fixtures" / "esw_window.yaml"
OUT_DIR = ROOT / "tests" / "_acceptance"


def main() -> None:
    recipe = load_recipe(RECIPE)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUT_DIR / f"{recipe['output']}.png"
    opju = OUT_DIR / f"{recipe['output']}.opju"

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
            layer = op.find_graph(page)[0]
            print(f"    y range = {op.lt_float('layer.y.from')} .. "
                  f"{op.lt_float('layer.y.to')}")
            print(f"    plots   = {[p.color for p in layer.plot_list()]}")
            print(f"    objects = {[o.Name for o in layer.obj.GraphObjects]}")
            print(f"    texts   = {[o.Text for o in layer.obj.GraphObjects if o.Text]}")

        if not op.save(str(opju.resolve())) or not opju.exists():
            raise RuntimeError(f"op.save produced nothing at {opju}")
        print(f"  project     -> {opju}  ({opju.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
