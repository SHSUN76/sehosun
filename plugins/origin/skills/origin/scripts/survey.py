"""Origin 프로젝트의 스타일 수치를 읽어 manifest YAML로 쓴다.

manifest는 감사·override용 기록이다. house style이 강제 적용되므로 manifest 값이
곧 결과 스타일은 아니다 — "이 donor가 원래 어떤 값이었는가"의 기록이다.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd
import yaml

from build import find_worksheet
from originsession import origin_session

PROPS = [
    "layer.x.thickness", "layer.y.thickness",
    "layer.x.label.pt", "layer.y.label.pt",
    "layer.x.label.bold", "layer.y.label.bold",
    "XB.fsize", "YL.fsize", "YR.fsize",
    "layer.x.ticks", "layer.y.ticks",
    "layer.x.type", "layer.y.type",
    "layer.x.from", "layer.x.to", "layer.x.inc",
    "layer.y.from", "layer.y.to", "layer.y.inc",
    "page.nLayers", "page.width", "page.height",
]


def _read_props(op) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for p in PROPS:
        v = op.lt_float(p)
        out[p] = None if (v is None or math.isnan(v)) else round(float(v), 3)
    return out


def _describe_data(op) -> dict:
    """첫 워크시트의 형태를 기록한다 (donor 추론 규칙의 근거).

    `has_worksheet` 를 함께 남긴다. "워크시트가 없다"(=이 donor로는 빌드가 불가능)와
    "읽다가 실패했다"는 완전히 다른 사실인데, x_type 하나로는 구분되지 않는다.
    """
    try:
        # find_sheet('w')의 'w'는 *활성* 워크시트를 뜻한다. survey_project는 바로 앞에서
        # 그래프를 활성화하므로 이름 없이 부르면 항상 None이다 (두 호출이 상호배타적).
        # find_worksheet 가 북 이름 후보 + 실제 워크북 열거를 둘 다 해 준다.
        wks = find_worksheet(op)
        if wks is None:
            return {"rows": 0, "cols": 0, "x_type": "none", "has_worksheet": False}
        df = wks.to_df()
        if df.empty or not len(df.columns):
            return {"rows": 0, "cols": 0, "x_type": "none", "has_worksheet": True}
        # pandas 3부터 문자열 컬럼의 dtype은 object가 아니라 StringDtype이다.
        # `dtype == object` 로 판정하면 범주형 x를 통째로 놓친다 —
        # `build.infer_donor` 가 이미 겪고 고친 것과 같은 함정이다.
        x_type = ("numeric" if pd.api.types.is_numeric_dtype(df.iloc[:, 0])
                  else "categorical")
        return {"rows": int(len(df)), "cols": int(len(df.columns)),
                "x_type": x_type, "has_worksheet": True}
    except Exception:
        # 판독 실패. 워크시트가 있는지도 알 수 없으므로 없다고 단정하지 않는다 —
        # x_type='unknown' 이 테스트에서 걸린다.
        return {"rows": 0, "cols": 0, "x_type": "unknown", "has_worksheet": None}


def survey_project(opj: Path, op=None) -> dict:
    """.opj 하나의 스타일 manifest를 만든다.

    op가 주어지면 그 세션을 재사용한다 (여러 개를 훑을 때 Origin 재시작 비용 회피).
    """
    if op is None:
        with origin_session() as session:
            return survey_project(opj, op=session)

    # Origin COM은 상대 경로를 자기 작업 디렉터리 기준으로 푼다 (파이썬 프로세스의 cwd가
    # 아니다). 상대 경로를 넘기면 예외도 없이 조용히 실패하므로 항상 절대 경로로 준다.
    opj = Path(opj).resolve()

    # 손상된 프로젝트는 False를 돌려주지 않는다 — Origin COM 계층이 RPC 실패로 터지면서
    # SystemError를 낸다 (RuntimeError의 하위 클래스가 아니다). 호출자(survey_dir)가
    # 걸러내기로 약속한 예외는 RuntimeError 하나뿐이므로 여기서 변환해 준다.
    # 변환하지 않으면 donor 하나가 깨졌을 때 전수 조사 전체가 중단된다.
    try:
        opened = op.open(str(opj), readonly=False)
    except Exception as e:
        raise RuntimeError(f"could not open {opj.name}: {e}") from e

    if not opened:
        raise RuntimeError(f"could not open {opj.name}")

    graphs = op.graph_list()
    if not graphs:
        raise RuntimeError(f"no graph page in {opj.name}")

    name = graphs[0].name
    op.lt_exec(f"win -a {name};")
    return {
        "source": opj.name,
        "graph": name,
        "graph_count": len(graphs),
        "measured": _read_props(op),
        "data_shape": _describe_data(op),
    }


def survey_dir(src: Path, out: Path) -> list[dict]:
    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifests = []
    with origin_session() as op:
        for opj in sorted(src.glob("*.opj")):
            try:
                m = survey_project(opj, op=op)
            except RuntimeError as e:
                print(f"  SKIP {opj.name}: {e}")
                continue
            (out / f"{opj.stem}.yaml").write_text(
                yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            manifests.append(m)
            print(f"  {opj.name:<18} title={m['measured']['YL.fsize']} "
                  f"ticklbl={m['measured']['layer.x.label.pt']} "
                  f"thick={m['measured']['layer.x.thickness']} "
                  f"yticks={m['measured']['layer.y.ticks']}")
    return manifests


def main() -> None:
    ap = argparse.ArgumentParser(description="Survey Origin project styles")
    ap.add_argument("src", type=Path, help="directory of .opj files")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    ms = survey_dir(args.src, args.out)
    print(f"\nsurveyed {len(ms)} projects -> {args.out}")


if __name__ == "__main__":
    main()
