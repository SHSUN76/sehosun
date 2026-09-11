"""증명: build.py 산출물이 편집 가능한 Origin 프로젝트인가?

PNG가 그럴듯하게 나오는 것과 '진짜 Origin 그래프'인 것은 다른 주장이다.
빌드 → .opj 저장 → 세션 종료 → 새 세션에서 재오픈 → 그래프·데이터·스타일 재확인.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import build_graph, load_recipe
from originsession import origin_session

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "_acceptance"
OUT.mkdir(parents=True, exist_ok=True)
OPJ = (OUT / "water_solubility.opju").resolve()

spec = load_recipe(ROOT / "tests" / "fixtures" / "water_solubility.yaml")["graphs"][0]

print("=== 1) build + save project ===")
with origin_session() as op:
    page = build_graph(op, spec, style_mode="house")
    # LabTalk `save -i`는 파일을 만들지 않는다. originpro의 op.save()가 정본이다.
    print(f"    op.save -> {op.save(str(OPJ))}")
print(f"    saved: {OPJ.exists()}  size={OPJ.stat().st_size if OPJ.exists() else 0:,} bytes")
if OPJ.exists():
    print(f"    magic: {OPJ.read_bytes()[:16]!r}")

print("\n=== 2) reopen in a FRESH session ===")
with origin_session() as op:
    ok = op.open(str(OPJ), readonly=False)
    print(f"    open       : {ok}")
    graphs = [g.name for g in op.graph_list()]
    print(f"    graphs     : {graphs}")
    op.lt_exec(f"win -a {graphs[0]};")

    wks = None
    for book in ("Book1", "Book2", "Book3"):
        wks = op.find_sheet("w", book)
        if wks is not None:
            break
    df = wks.to_df() if wks is not None else None
    print(f"    worksheet  : {wks.lt_range() if wks is not None else None}")
    if df is not None:
        print(f"    data       :\n{df.dropna(how='all').to_string()}")

    print(f"    y range    : {op.lt_float('layer.y.from')} .. {op.lt_float('layer.y.to')}")
    print(f"    house style: thickness={op.lt_float('layer.x.thickness')} "
          f"ticklabel={op.lt_float('layer.x.label.pt')} "
          f"ticks={op.lt_float('layer.y.ticks')} YLsize={op.lt_float('YL.fsize')}")

    png = str((OUT / "roundtrip.png").resolve()).replace("\\", "/")
    op.find_graph(graphs[0]).save_fig(png, width=1000)
    print(f"    re-rendered: {png}")
