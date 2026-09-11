"""`donors/floating_bar.opj` 를 새로 저작한다 (+ manifest YAML).

    python scripts/_author_floating_bar.py

donor 9종은 전부 논문 덱의 임베드 그래프에서 복원한 것이지만, **범위 막대(floating
bar)는 그 35개에 없다.** 그래서 이 아키타입만 Origin 내장 템플릿 `FloatCol.otp` 에서
새로 만든다. donor 철학(기존 그래프에서 상속)에서 벗어나는 첫 케이스이므로
manifest의 `curated_from` 은 `authored:floating_bar` 로 표시한다.

저작 내용 (전부 실측으로 확인한 경로다 — references/labtalk_props.md §13 참조):

* `op.new_graph(template="FloatCol")` + `plotxy ... plot:=230` → 진짜 floating column.
  `plot:=230` 은 "템플릿의 플롯 타입을 그대로" 라는 뜻이다.
* Y 컬럼을 둘씩 묶어 막대 하나를 만든다. 범주마다 독립된 쌍을 주면 막대별로 plot이
  분리돼 계열색을 줄 수 있다.
* 범례는 `label -r legend;` 로 지운다 (`legend -r;` 은 지워지지 않는다).
* 밴드 바깥 라벨이 페이지 밖으로 잘리지 않도록 레이어 폭을 줄이고 페이지를 넓힌다.
* house style을 구워 넣는다 — 물려받을 '원본 논문 그림'이 없으므로 이 donor의
  고유 스타일이 곧 house style이어야 `style: inherit` 도 말이 된다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from originsession import origin_session  # noqa: E402
from style import apply_house_style  # noqa: E402
from survey import survey_project  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DONOR = ROOT / "donors" / "floating_bar.opj"
MANIFEST = ROOT / "donors" / "floating_bar.yaml"

# 페이지/레이어 배치. 기본 FloatCol은 layer.left=15 width=75 라서 플롯 바깥 오른쪽에
# 라벨을 놓으면 페이지 밖으로 잘린다 (실측). 오른쪽 여백을 확보한다.
PAGE_WIDTH = 9000
LAYER = {"left": 13, "top": 22, "width": 55, "height": 60}

NAN = float("nan")
SAMPLE = pd.DataFrame({
    "category": ["A", "B"],
    "lo_1": [-1.0, NAN], "hi_1": [4.0, NAN],
    "lo_2": [NAN, -0.5], "hi_2": [NAN, 4.5],
})


def author(op) -> str:
    wks = op.find_sheet("w", "Book1") or op.new_sheet("w")
    wks.from_df(SAMPLE, addindex=False)
    for i in range(len(SAMPLE.columns)):
        wks.set_label(i, "", "U")
    book = wks.lt_range(False)

    gp = op.new_graph(template="FloatCol")
    if gp is None:
        raise RuntimeError("could not create a graph from FloatCol.otp")
    gname = gp.name

    ncols = len(SAMPLE.columns)
    if not op.lt_exec(f"win -a {gname}; "
                      f"plotxy iy:={book}!(1,2:{ncols}) plot:=230 ogl:=[{gname}]1!;"):
        raise RuntimeError("plotxy failed")
    op.lt_exec("label -r legend; doc -uw;")

    plots = op.find_graph(gname)[0].plot_list()
    if len(plots) != ncols - 1:
        raise RuntimeError(f"expected {ncols - 1} plots, got {len(plots)}")

    op.lt_exec(f"page.width = {PAGE_WIDTH};")
    op.lt_exec("; ".join(f"layer.{k} = {v}" for k, v in LAYER.items()) + "; doc -uw;")
    op.lt_exec("layer.y.from = -2; layer.y.to = 6; layer.y.inc = 1; doc -uw;")
    apply_house_style(op)
    op.lt_exec("doc -uw;")
    return gname


def main() -> None:
    DONOR.parent.mkdir(parents=True, exist_ok=True)
    with origin_session() as op:
        gname = author(op)
        if not op.save(str(DONOR.resolve())) or not DONOR.exists():
            raise RuntimeError(f"op.save produced nothing at {DONOR}")
        print(f"  {gname} -> {DONOR}  ({DONOR.stat().st_size:,} bytes)")

    # manifest는 저장본을 다시 열어 읽는다 — 파일에 실제로 들어간 값이어야 한다.
    with origin_session() as op:
        m = survey_project(DONOR, op=op)
    m = {"archetype": "floating_bar",
         # 원본 덱에 이 플롯 타입이 없어 새로 저작했다. 아키타입 이름을 붙여
         # 두면 다른 저작 donor가 생겨도 중복 검사가 계속 유효하다.
         "curated_from": "authored:floating_bar",
         **{k: v for k, v in m.items() if k != "source"}}
    MANIFEST.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    print(f"  manifest -> {MANIFEST}")
    print(f"  measured: YL={m['measured']['YL.fsize']} "
          f"ticklbl={m['measured']['layer.x.label.pt']} "
          f"thick={m['measured']['layer.x.thickness']} "
          f"yticks={m['measured']['layer.y.ticks']} "
          f"shape={m['data_shape']}")


if __name__ == "__main__":
    main()
