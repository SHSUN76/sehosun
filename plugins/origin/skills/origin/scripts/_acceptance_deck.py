"""인수 산출물: 레시피 하나를 pptx 덱으로 끝까지 조립한다.

    python scripts/_acceptance_deck.py

water_solubility_full.yaml 에 layout(cols=2, gap_in=0.2)을 얹고 출력 이름만 deck으로
바꿔서 돌린다. 결과: tests/_acceptance/deck.pptx
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from paste import run_recipe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tests" / "fixtures" / "water_solubility_full.yaml"
OUT_DIR = ROOT / "tests" / "_acceptance"


def main() -> None:
    recipe = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    recipe["layout"] = {"cols": 2, "gap_in": 0.2}
    recipe["output"] = "deck"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    merged = OUT_DIR / "_deck_recipe.yaml"
    merged.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")

    deck = run_recipe(merged, OUT_DIR)

    with zipfile.ZipFile(deck) as z:
        names = z.namelist()
        embeddings = [n for n in names if n.startswith("ppt/embeddings/")]
        slide = z.read("ppt/slides/slide1.xml").decode("utf-8", "replace")

    print(f"\n--- {deck.name} 내부 검사 ---")
    print(f"  크기          : {deck.stat().st_size:,} bytes")
    print(f"  OLE 임베드    : {len(embeddings)}  {embeddings}")
    print(f"  progId 포함   : {'progId' in slide}")
    print(f"  'Origin' 포함 : {'Origin' in slide}")


if __name__ == "__main__":
    main()
