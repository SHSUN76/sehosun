"""인수테스트: 실전 레시피 하나를 끝까지 돌려 PNG를 만든다.

파이프라인 전체(레시피 검증 -> donor 개방 -> 데이터 주입 -> 축 범위 재계산 ->
축 제목 -> house style -> 렌더)가 실제로 그림을 뱉는지 확인하는 용도다.
테스트가 아니라 눈으로 볼 산출물을 남기는 스크립트다.

    python scripts/_acceptance.py [recipe.yaml]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import build_graph, load_recipe  # noqa: E402
from originsession import origin_session  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECIPE = ROOT / "tests" / "fixtures" / "water_solubility.yaml"
OUT_DIR = ROOT / "tests" / "_acceptance"


def run(recipe_path: Path, out_dir: Path, width: int = 1000) -> list[Path]:
    recipe = load_recipe(recipe_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    with origin_session() as op:
        for spec in recipe["graphs"]:
            page = build_graph(op, spec, style_mode=recipe["style"])
            png = out_dir / f"{recipe['output']}.png"
            # Origin COM은 상대 경로를 자기 작업 디렉터리 기준으로 푼다 — 절대 경로 필수.
            target = str(png.resolve()).replace("\\", "/")
            saved = op.find_graph(page).save_fig(target, width=width)
            if not saved or not png.exists():
                raise RuntimeError(f"save_fig produced nothing for {spec['id']!r}")
            written.append(png)
            print(f"  {spec['id']:<14} -> {png}  ({png.stat().st_size:,} bytes)")

            op.lt_exec(f"win -a {page};")
            print(f"    y range = {op.lt_float('layer.y.from')} .. {op.lt_float('layer.y.to')}"
                  f"  (inc {op.lt_float('layer.y.inc')})")
    return written


def main() -> None:
    recipe = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RECIPE
    print(f"recipe: {recipe}")
    written = run(recipe, OUT_DIR)
    print(f"\nwrote {len(written)} figure(s) -> {OUT_DIR}")


if __name__ == "__main__":
    main()
