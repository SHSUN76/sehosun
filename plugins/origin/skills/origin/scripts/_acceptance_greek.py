"""그리스 문자 카테고리 라벨이 Origin까지 살아서 가는지 확인한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import build_graph, load_recipe
from originsession import origin_session

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
OUT = ROOT / "tests" / "_acceptance"
OUT.mkdir(parents=True, exist_ok=True)

recipe = FIX / "water_solubility_greek.yaml"
recipe.write_text(
    "output: water_solubility_greek\n"
    "style: house\n"
    "graphs:\n"
    "  - id: solubility\n"
    "    donor: bar_labeled\n"
    f"    data: {(FIX / 'water_solubility_greek.csv').resolve().as_posix()}\n"
    "    x: cyclodextrin\n"
    "    y: solubility\n"
    '    y_title: "g / 100 mL"\n'
    "    y_range: auto\n",
    encoding="utf-8",
)

spec = load_recipe(recipe)["graphs"][0]
with origin_session() as op:
    page = build_graph(op, spec, style_mode="house")
    wks = None
    for book in ("Book1", "Book2", "Book3"):
        wks = op.find_sheet("w", book)
        if wks is not None:
            break
    df = wks.to_df().dropna(how="all")
    print("worksheet round-trip:")
    print(df.to_string())
    print("\nx labels as stored:", [repr(v) for v in df.iloc[:, 0]])
    png = str((OUT / "water_solubility_greek.png").resolve()).replace("\\", "/")
    op.find_graph(page).save_fig(png, width=1000)
    print("rendered:", png)
