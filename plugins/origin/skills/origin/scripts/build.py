"""레시피 + 데이터 -> Origin 그래프.

donor를 열어 워크시트 데이터를 갈아끼운다. 스타일은 donor에서 상속되고,
style_mode='house'면 그 위에 표준값을 덮어쓴다.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import yaml

import decorate
from style import (apply_axis_range, apply_house_style, clipped_values,
                   load_house_style)

DONOR_DIR = Path(__file__).resolve().parents[1] / "donors"
BOOK_CANDIDATES = ("Book1", "Book2", "Book3", "Book4", "Book5")

# y_range 로 쓸 수 있는 키워드. 리스트가 아니면 이 둘 중 하나여야 한다 —
# 오타(`atuo`)가 조용히 'donor 범위 유지'로 흘러가면 축이 왜 그대로인지 알 수 없다.
Y_RANGE_KEYWORDS = ("auto", "inherit")


class AxisClipWarning(UserWarning):
    """`y_range: inherit` 인데 새 데이터가 donor 축을 벗어나 잘린다."""

# y_low/y_high 를 쓰면 이 아키타입으로 간다 (donor를 생략했을 때).
FLOATING_DONOR = "floating_bar"

# plotxy 의 plot ID. 230 = "템플릿의 플롯 타입을 그대로 쓴다" (originpro가 type='?'
# 에 쓰는 값과 같다). floating_bar donor는 Origin 내장 FloatCol.otp 에서 왔으므로
# 이 값이 곧 floating column이다.
_TEMPLATE_PLOT_ID = 230

# donor의 축 제목은 리터럴이 아니라 '%(?Y)' 같은 치환 토큰일 수 있다 (bar_labeled가
# 그렇다: YL.text$ == r'\p127(\b(%(?Y)))'). 이 토큰은 해당 축 컬럼의
# Long Name (Units) 로 렌더된다.
_TITLE_TOKEN = {"XB": "%(?X)", "YL": "%(?Y)", "YR": "%(?Y)"}

# 범위 막대(floating) 경로에서만 구현된 필드. 일반 donor에 적으면 그리는 코드가
# 없어 **조용히 사라진다** — 검증만 통과시키고 렌더에서 없어지는 것이 가장 나쁘므로
# `load_recipe` 에서 즉시 거부한다.
FLOATING_ONLY_FIELDS = ("subtitle", "bands", "value_labels", "x_labels")


def _read_data(spec_data: str) -> pd.DataFrame:
    """'file.xlsx#Sheet1' 또는 'file.csv' 를 읽는다."""
    if "#" in spec_data:
        path, sheet = spec_data.rsplit("#", 1)
        return pd.read_excel(path, sheet_name=sheet)
    if spec_data.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(spec_data)
    return pd.read_csv(spec_data)


def infer_donor(df: pd.DataFrame, x: str, ycols: list[str]) -> str:
    """데이터 형태로 아키타입을 추론한다. 결과는 반드시 호출자가 사용자에게 보고한다."""
    if any(c.lower().endswith(("_err", "_sd", "_std")) for c in ycols):
        return "errorbar"

    # pandas 3부터 문자열 컬럼의 dtype은 object가 아니라 StringDtype이다.
    # `dtype == object`로 판정하면 범주형 x를 통째로 놓친다.
    if not pd.api.types.is_numeric_dtype(df[x]):
        return "bar_grouped" if len(ycols) > 1 else "bar_labeled"

    positive = df[x][df[x] > 0]
    if len(positive) >= 2 and positive.max() / positive.min() >= 1000:
        return "log_axis"

    return "line_symbol"


def spec_ycols(spec: dict) -> list[str]:
    """스펙이 쓰는 y 컬럼 목록. `y` 와 `y_low`/`y_high` 는 상호배타다."""
    has_y = spec.get("y") is not None
    has_low = spec.get("y_low") is not None
    has_high = spec.get("y_high") is not None

    if has_y and (has_low or has_high):
        raise ValueError("y and y_low/y_high are mutually exclusive; pick one")
    if has_low != has_high:
        raise ValueError("y_low and y_high must be given together")
    if has_y:
        return [spec["y"]] if isinstance(spec["y"], str) else list(spec["y"])
    if has_low:
        return [spec["y_low"], spec["y_high"]]
    raise ValueError("each graph needs either y or y_low + y_high")


def is_floating(spec: dict) -> bool:
    return spec.get("y_low") is not None and spec.get("y_high") is not None


def floating_only_fields(spec: dict) -> list[str]:
    """이 스펙이 쓰는 floating 전용 필드 이름들 (일반 donor면 전부 무효다)."""
    used = [k for k in FLOATING_ONLY_FIELDS if spec.get(k)]
    if (spec.get("colors") or {}).get("series"):
        used.append("colors.series")
    return used


def category_x_range(n: int) -> tuple[float, float]:
    """범주 N개가 놓이는 x축 범위.

    Origin은 텍스트 x 컬럼을 1..N 자리에 배치하므로 축은 0.5 ~ N+0.5 여야 막대가
    양끝에서 잘리지 않는다. donor에는 자기 범주 개수(floating_bar는 2개)에 맞는
    범위가 구워져 있어서, 새 데이터의 범주 수가 다르면 그대로 두면 잘린다.
    """
    n = int(n)
    if n < 1:
        raise ValueError(f"need at least one category to place an x axis, got {n}")
    return 0.5, n + 0.5


def floating_frame(xcol: str, categories, lows, highs, x_labels=None):
    """범주 N개를 '범주열 + (아래,위) 쌍 N개' 로 펼친다.

    한 쌍은 자기 범주 행에만 값이 있고 나머지는 NaN이다. Origin의 floating column
    레이어는 Y 컬럼을 앞에서부터 둘씩 묶어 막대 하나로 그리므로, 이렇게 나누면
    막대마다 독립된 plot을 갖게 되어 계열별 색 지정이 가능해진다 (점별 색 지정
    경로는 Origin에서 전부 죽어 있다).
    """
    labels = x_labels or {}
    data = {xcol: [labels.get(c, c) for c in categories]}
    nan = float("nan")
    for i, cat in enumerate(categories):
        lo = [nan] * len(categories)
        hi = [nan] * len(categories)
        lo[i] = float(lows[i])
        hi[i] = float(highs[i])
        data[f"lo_{i + 1}"] = lo
        data[f"hi_{i + 1}"] = hi
    return pd.DataFrame(data)


def _validate_optional_fields(spec: dict, df: pd.DataFrame, categories) -> None:
    """floating 전용 선택 필드 검증. 없는 컬럼·범주는 조용히 무시하지 않는다."""
    for key in ("x_labels", "colors.series"):
        mapping = spec.get("x_labels") if key == "x_labels" else \
            (spec.get("colors") or {}).get("series")
        if not mapping:
            continue
        if not isinstance(mapping, dict):
            raise ValueError(f"{key} must be a mapping, got {type(mapping).__name__}")
        for name in mapping:
            decorate.category_index(categories, name, key)

    for i, band in enumerate(spec.get("bands") or []):
        decorate.validate_band(band, f"bands[{i}]")

    value_labels = spec.get("value_labels") or {}
    if value_labels and not isinstance(value_labels, dict):
        raise ValueError("value_labels must be a mapping")
    for where, sub in value_labels.items():
        if where not in ("top", "bottom"):
            raise ValueError(f"value_labels key must be 'top' or 'bottom', got {where!r}")
        if not isinstance(sub, dict) or "source" not in sub:
            raise ValueError(f"value_labels.{where} needs a 'source' column")
        if sub["source"] not in df.columns:
            raise ValueError(
                f"value_labels.{where}.source {sub['source']!r} not found in "
                f"{spec['data']}; has {list(df.columns)}"
            )
        # 포맷 오류는 그래프를 만들기 전에 잡는다.
        decorate.format_value_label(sub.get("format"), 0.0)


def donor_manifest(donor: str) -> dict:
    """donor의 survey manifest. 없으면 빈 dict."""
    path = DONOR_DIR / f"{donor}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def donor_has_worksheet(donor: str) -> bool:
    """이 donor에 데이터를 주입할 워크시트가 있는가.

    log_axis / errorbar 는 워크북이 통째로 없다 (실측 2026-07-29: `op.pages('w')`
    가 비어 있고, 그래프 페이지 하나만 들어 있다). PowerPoint에 붙일 때 Origin이
    그래프 페이지만 임베드한 것으로, 플롯이 참조하던 데이터셋 자체가 프로젝트에
    없다. 북 이름 후보가 부족한 게 아니라 워크시트가 정말 없다.

    명시적으로 `false` 일 때만 막는다. 키가 없거나(구 manifest) 판독 실패로 `null`
    이면 통과시킨다 — "모른다"를 "없다"로 단정해 멀쩡한 donor를 막는 쪽이 더 나쁘고,
    정말 없으면 `build_graph` 가 같은 문구로 실패시킨다.
    """
    shape = donor_manifest(donor).get("data_shape") or {}
    return shape.get("has_worksheet", True) is not False


def buildable_donors() -> list[str]:
    return sorted(p.stem for p in DONOR_DIR.glob("*.opj") if donor_has_worksheet(p.stem))


def _check_donor(donor: str, inferred: bool = False) -> None:
    if not (DONOR_DIR / f"{donor}.opj").exists():
        available = sorted(p.stem for p in DONOR_DIR.glob("*.opj"))
        raise ValueError(f"unknown donor {donor!r}; available: {available}")
    if not donor_has_worksheet(donor):
        how = "inferred" if inferred else "requested"
        raise ValueError(
            f"{how} donor {donor!r} has no worksheet, so there is nowhere to inject "
            f"the data (the recovered OLE embedded only the graph page). "
            f"usable donors: {buildable_donors()}"
        )


def validate_y_range(y_range) -> None:
    """`auto` / `inherit` / 2원소 숫자 리스트만 허용한다."""
    if isinstance(y_range, str):
        if y_range not in Y_RANGE_KEYWORDS:
            raise ValueError(
                f"y_range must be one of {list(Y_RANGE_KEYWORDS)} or [lo, hi]; "
                f"got {y_range!r}")
        return
    if isinstance(y_range, (list, tuple)):
        if len(y_range) != 2:
            raise ValueError(
                f"y_range needs exactly 2 values [lo, hi]; got {list(y_range)}")
        try:
            lo, hi = float(y_range[0]), float(y_range[1])
        except (TypeError, ValueError):
            raise ValueError(
                f"y_range values must be numbers; got {list(y_range)}") from None
        if lo == hi:
            raise ValueError(
                f"y_range needs two different values; got {list(y_range)}")
        return
    raise ValueError(
        f"y_range must be one of {list(Y_RANGE_KEYWORDS)} or [lo, hi]; "
        f"got {y_range!r}")


def load_recipe(path: Path) -> dict:
    """레시피를 읽고 즉시 검증한다. 잘못된 것은 그래프를 만들기 전에 잡는다."""
    recipe = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    recipe.setdefault("style", "house")
    if recipe["style"] not in ("house", "inherit"):
        raise ValueError(f"style must be 'house' or 'inherit', got {recipe['style']!r}")

    # 같은 id가 둘이면 개별 `.opju` 경로가 겹쳐 뒤엣것이 앞엣것을 덮어쓴다 —
    # 덱에는 같은 그래프가 두 번 박히고, 하나는 통째로 사라진다.
    seen: set[str] = set()
    for spec in recipe["graphs"]:
        gid = spec.get("id")
        if gid is None:
            continue
        if gid in seen:
            raise ValueError(
                f"duplicate graph id {gid!r}; ids must be unique (they name the "
                f"intermediate .opju, so a repeat silently overwrites the first)")
        seen.add(gid)

    for spec in recipe["graphs"]:
        # donor를 적어 놓았으면 데이터를 읽기 전에 먼저 확인한다 — 오타 하나 때문에
        # 없는 파일을 읽으러 가서 엉뚱한 예외가 나면 원인을 못 찾는다.
        if spec.get("donor"):
            _check_donor(spec["donor"])
        validate_y_range(spec.get("y_range", "auto"))

        df = _read_data(spec["data"])
        ycols = spec_ycols(spec)
        for col in [spec["x"]] + ycols:
            if col not in df.columns:
                raise ValueError(
                    f"column {col!r} not found in {spec['data']}; has {list(df.columns)}"
                )

        if not spec.get("donor"):
            spec["donor"] = (FLOATING_DONOR if is_floating(spec)
                             else infer_donor(df, spec["x"], ycols))
            spec["donor_inferred"] = True
            # 추론이 빌드 불가 donor(워크시트 없음)에 도달하면 **이 그래프만** 실패
            # 시킨다. 사용자가 고른 게 아니라 우리가 고른 것이므로 레시피 전체를
            # 죽이면 안 된다 — paste.py 의 "부분 실패는 건너뛰고 n/total로 보고"
            # 계약과 정면으로 충돌한다. 명시(`donor:`)한 경우는 위에서 이미 즉시
            # ValueError 다 (사용자가 틀린 것을 골랐으니 알려야 한다).
            try:
                _check_donor(spec["donor"], inferred=True)
            except ValueError as e:
                spec["build_error"] = str(e)

        if not is_floating(spec):
            used = floating_only_fields(spec)
            if used:
                raise ValueError(
                    f"{used} only work on the floating bar path (y_low/y_high); "
                    f"graph {spec.get('id', '?')!r} uses donor {spec['donor']!r} and "
                    f"they would be silently dropped")

        # 강조/주석이 가리키는 범주가 데이터에 없으면 조용히 무시하지 않는다.
        categories = [str(c) for c in df[spec["x"]]]
        highlight = (spec.get("colors") or {}).get("highlight")
        if highlight:
            decorate.category_index(categories, highlight["category"],
                                    "colors.highlight.category")
        if spec.get("annotation") and not decorate.is_anchor(spec["annotation"]["at"]):
            decorate.category_index(categories, spec["annotation"]["at"],
                                    "annotation.at")
        _validate_optional_fields(spec, df, categories)
    return recipe


def find_worksheet(op):
    """프로젝트의 데이터 워크시트. 없으면 None.

    이름 후보(`Book1`...)를 먼저 보고, 못 찾으면 실제 워크북을 열거한다 — donor가
    `Draw1` 처럼 다른 이름을 달고 있어도 잡히게. 두 경로 모두 비면 워크북이 정말
    없는 것이다 (log_axis / errorbar 가 그 경우).
    """
    for book in BOOK_CANDIDATES:
        wks = op.find_sheet("w", book)
        if wks is not None:
            return wks
    try:
        for page in op.pages("w"):
            if len(page):
                return page[0]
    except Exception:
        pass
    return None


# 하위 호환 별칭 (기존 호출부).
_find_wks = find_worksheet


def fit_columns(op, wks, ncols: int) -> int:
    """워크시트 컬럼 수를 `ncols` 개로 줄인다. 남은 개수를 반환한다.

    `wks.from_df()` 는 컬럼을 늘리기만 하고 줄이지 않는다 (originpro
    `_check_add_cols`). donor가 우리 데이터보다 컬럼이 많으면 그 초과분이 donor의
    값을 그대로 담은 채 살아남고, 그것을 참조하는 donor의 plot도 계속 그려진다 —
    "데이터를 갈아끼웠는데 남의 계열이 하나 더 붙어 있는" 결함이 여기서 난다.
    """
    have = int(wks.cols)
    if have <= ncols:
        return have
    wks.del_col(ncols, have - ncols)
    op.lt_exec("doc -uw;")
    return int(wks.cols)


def _inject(op, wks, frame) -> None:
    """워크시트를 frame 모양으로 정확히 맞춰 채운다."""
    fit_columns(op, wks, len(frame.columns))

    # 텍스트 컬럼도 from_df가 그대로 쓴다 (실측). 범주형 x축 눈금 라벨은 그 텍스트
    # 컬럼을 데이터셋으로 참조하므로(layer.x.label.dataset$), 숫자로 치환해 넣으면
    # 라벨이 1,2,3으로 무너진다 — 원본 dtype 그대로 넘긴다.
    wks.from_df(frame, addindex=False)

    # from_df는 Long Name은 갈아끼우지만 Units는 남긴다. donor의 단위가 새 데이터에
    # 눌러앉으면 축 제목이 'val (B/G)'처럼 거짓이 되므로 명시적으로 비운다.
    for i in range(len(frame.columns)):
        wks.set_label(i, "", "U")


def _apply_y_range(op, spec: dict, values, anchor_zero: bool = True) -> None:
    """`y_range` 를 축에 반영한다. `inherit` 는 donor 범위를 그대로 두되 경고한다."""
    y_range = spec.get("y_range", "auto")
    validate_y_range(y_range)

    if y_range == "auto":
        apply_axis_range(op, "y", values, anchor_zero=anchor_zero)
        return
    if isinstance(y_range, (list, tuple)):
        op.lt_exec(f"layer.y.from = {y_range[0]}; layer.y.to = {y_range[1]};")
        lo, hi = float(y_range[0]), float(y_range[1])
    else:  # inherit — donor 범위 유지
        lo, hi = op.lt_float("layer.y.from"), op.lt_float("layer.y.to")

    # 고정 범위든 상속 범위든, 데이터가 그 밖으로 나가면 조용히 잘린다.
    outside = clipped_values(min(lo, hi), max(lo, hi), values)
    if outside:
        warnings.warn(
            f"graph {spec.get('id', '?')!r}: y_range={y_range!r} keeps the axis at "
            f"[{lo}, {hi}] but {len(outside)} value(s) fall outside it "
            f"(min={min(outside)}, max={max(outside)}); they will be clipped",
            AxisClipWarning, stacklevel=3,
        )


def _set_axis_title(op, wks, obj: str, col_index: int, text: str) -> None:
    """축 제목을 넣는다.

    donor의 제목이 치환 토큰이면 리터럴로 덮어쓰면 안 된다. 토큰에는 서식
    이스케이프가 함께 걸려 있어서(예: r'\\p127(\\b(%(?Y)))' = 127% 크기 + 볼드),
    통째로 갈아끼우면 글자는 맞아도 렌더가 달라진다. 동적 제목은 컬럼 Long Name을
    바꿔서 원래 경로 그대로 렌더시킨다.
    """
    current = op.get_lt_str(f"{obj}.text$") or ""
    if _TITLE_TOKEN[obj] in current:
        wks.set_label(col_index, text, "L")
    else:
        op.lt_exec(f'{obj}.text$ = "{text}";')


def build_graph(op, spec: dict, style_mode: str = "house") -> str:
    """donor를 열어 데이터를 주입하고 그래프 페이지 이름을 반환한다."""
    # `load_recipe` 가 미뤄 둔 실패 (추론이 빌드 불가 donor에 도달한 경우). 여기서
    # 터뜨려야 호출자의 "이 그래프만 건너뛴다" 경로를 그대로 탄다. Origin은 아직
    # 건드리지 않는다.
    if spec.get("build_error"):
        raise RuntimeError(spec["build_error"])

    donor = (DONOR_DIR / f"{spec['donor']}.opj").resolve()
    if not op.open(str(donor), readonly=False):
        raise RuntimeError(f"could not open donor {donor.name}")

    graphs = op.graph_list()
    if not graphs:
        raise RuntimeError(f"donor {donor.name} has no graph page")
    gname = graphs[0].name

    df = _read_data(spec["data"])
    if is_floating(spec):
        return _build_floating(op, spec, df, gname, style_mode)

    ycols = spec_ycols(spec)
    new = df[[spec["x"]] + ycols]

    wks = find_worksheet(op)
    if wks is None:
        raise RuntimeError(
            f"donor {donor.name} has no worksheet, so there is nowhere to inject "
            f"the data; usable donors: {buildable_donors()}")

    _inject(op, wks, new)

    op.lt_exec(f"win -a {gname};")

    _apply_y_range(op, spec, pd.concat([new[c] for c in ycols]).tolist())

    if spec.get("y_title"):
        _set_axis_title(op, wks, "YL", 1, spec["y_title"])
    if spec.get("x_title"):
        _set_axis_title(op, wks, "XB", 0, spec["x_title"])

    if style_mode == "house":
        apply_house_style(op)

    _decorate(op, gname, wks, spec, new, spec["x"], ycols, style_mode)

    op.lt_exec("doc -uw;")
    return gname


# floating column 레이어는 Y 컬럼 2개(= 막대 1개)가 최소 단위다. 그 아래로는 지워지지
# 않는다 (실측: 4개 → 2개까지만 삭제되고 그 뒤로는 조용히 무시). 그래서 "전부 지우고
# 다시 그리기"가 아니라 "2개만 남기고 나머지를 이어 붙이기"로 간다.
_FLOAT_MIN_PLOTS = 2


def _trim_plots(op, gname: str, keep: int) -> int:
    """레이어의 데이터 plot을 `keep` 개까지 줄이고 남은 개수를 반환한다.

    `plot.remove()` 는 COM 객체를 Destroy 한다. 미리 뽑아 둔 목록을 앞에서부터 돌면
    남은 핸들이 무효가 돼 일부만 지워진다 (실측: 4개 중 2개만 삭제). 매번 목록을
    다시 읽고 **뒤에서부터** 지운다.
    """
    for _ in range(200):
        layer = op.find_graph(gname)[0]
        plots = layer.plot_list()
        if len(plots) <= keep:
            return len(plots)
        layer.remove_plot(plots[-1])
        op.lt_exec("doc -uw;")
        if len(op.find_graph(gname)[0].plot_list()) == len(plots):
            return len(plots)          # 더는 줄지 않는다
    raise RuntimeError(f"could not trim the plots on {gname}")


def _build_floating(op, spec: dict, df, gname: str, style_mode: str) -> str:
    """범위 막대(floating bar) 경로.

    donor의 레이어 스타일은 물려받되 plot 구성은 데이터에 맞춘다 — 범주 개수가
    donor(2개)와 다르면 필요한 컬럼 쌍의 수가 달라지기 때문이다. donor에 남겨 둔
    첫 쌍(컬럼 B,C)이 1번 범주를 그대로 받고, 2번 범주부터는 이어 붙인다.
    """
    x = spec["x"]
    categories = [str(c) for c in df[x]]
    lows = [float(v) for v in df[spec["y_low"]]]
    highs = [float(v) for v in df[spec["y_high"]]]
    frame = floating_frame(x, categories, lows, highs, spec.get("x_labels"))

    op.lt_exec(f"win -a {gname};")
    _trim_plots(op, gname, _FLOAT_MIN_PLOTS)

    wks = find_worksheet(op)
    if wks is None:
        raise RuntimeError(
            f"donor {spec['donor']} has no worksheet, so there is nowhere to inject "
            f"the data; usable donors: {buildable_donors()}")
    _inject(op, wks, frame)
    book = wks.lt_range(False)

    ncols = len(frame.columns)
    op.lt_exec(f"win -a {gname};")
    if ncols > _FLOAT_MIN_PLOTS + 1:
        if not op.lt_exec(f"plotxy iy:={book}!(1,{_FLOAT_MIN_PLOTS + 2}:{ncols}) "
                          f"plot:={_TEMPLATE_PLOT_ID} ogl:=[{gname}]1!;"):
            raise RuntimeError("plotxy failed for the floating bar layer")
    # 범례는 계열이 lo_1/hi_1... 이라 의미가 없다. `legend -r` 로는 안 지워진다 (실측).
    op.lt_exec("label -r legend; doc -uw;")

    made = len(op.find_graph(gname)[0].plot_list())
    if made != ncols - 1:
        raise RuntimeError(f"floating plot landed {made} plots, expected {ncols - 1}")

    # donor에는 자기 범주 수(2개)에 맞는 x 범위 [0.5, 2.5]가 구워져 있다. 범주가
    # 3개 이상이면 그대로 두는 순간 뒤쪽 막대가 통째로 잘린다 — y축만 관리하면
    # 안 된다. 눈금 간격은 1(범주 하나당 하나)이 정본이다.
    x_from, x_to = category_x_range(len(categories))
    if not op.lt_exec(f"layer.x.from = {x_from}; layer.x.to = {x_to}; "
                      f"layer.x.inc = 1; doc -uw;"):
        raise RuntimeError(f"could not set the x range on {gname}")

    # 범위 막대는 바닥이 0이 아니라 y_low 다. 0을 억지로 물리면 창만 좁아진다.
    _apply_y_range(op, spec, lows + highs, anchor_zero=False)

    if spec.get("y_title"):
        _set_axis_title(op, wks, "YL", 1, spec["y_title"])
    if spec.get("x_title"):
        _set_axis_title(op, wks, "XB", 0, spec["x_title"])

    if style_mode == "house":
        apply_house_style(op)

    _decorate_floating(op, gname, spec, df, categories, lows, highs)
    op.lt_exec("doc -uw;")
    return gname


def _decorate_floating(op, gname, spec, df, categories, lows, highs) -> None:
    """floating 경로의 선택 필드. z 순서 = 만든 순서라 막대 → 밴드 → 글자 순이다."""
    house = load_house_style()
    layer = op.find_graph(gname)[0]
    positions = list(range(1, len(categories) + 1))

    series = (spec.get("colors") or {}).get("series") or {}
    if series:
        decorate.color_floating_series(op, layer, categories, series)
        decorate.draw_floating_bars(op, layer, positions, lows, highs,
                                    categories, series)

    if spec.get("bands"):
        decorate.add_bands(op, layer, spec["bands"],
                           house["tick_label_pt"] * decorate.BAND_LABEL_RATIO)

    value_labels = spec.get("value_labels") or {}
    pt = house["tick_label_pt"] * decorate.VALUE_LABEL_RATIO
    colors = [(series.get(c) or {}).get("line") for c in categories]
    for where, anchors in (("top", highs), ("bottom", lows)):
        sub = value_labels.get(where)
        if not sub:
            continue
        values = [float(v) for v in df[sub["source"]]]
        decorate.place_range_labels(op, layer, positions, anchors, values, sub,
                                    pt, above=(where == "top"), colors=colors)

    base = None
    if spec.get("subtitle"):
        _, base = decorate.add_subtitle(
            op, layer, spec["subtitle"],
            house["axis_title_pt"] * decorate.SUBTITLE_RATIO)
    if spec.get("title"):
        decorate.add_title(op, layer, spec["title"], house["axis_title_pt"],
                           base=base)

    annotation = spec.get("annotation")
    if annotation:
        apt = house["tick_label_pt"] * decorate.ANNOTATION_RATIO
        if decorate.is_anchor(annotation["at"]):
            decorate.add_anchored_annotation(op, layer, annotation, apt)
        else:
            decorate.add_annotation(op, layer, annotation, positions, highs,
                                    categories)


def _x_positions(series) -> list:
    """범주형 x는 1..N 자리에 그려진다 (Origin은 텍스트 컬럼을 행 번호로 배치한다)."""
    if not pd.api.types.is_numeric_dtype(series):
        return list(range(1, len(series) + 1))
    return [float(v) for v in series]


def _decorate(op, gname, wks, spec, frame, xcol, ycols, style_mode) -> None:
    """선택 필드(colors/title/annotation)와 값 라벨 배치.

    값 라벨 손보기는 house 모드(또는 색을 직접 지정한 경우)에서만 한다. inherit는
    'donor를 그대로'라는 약속이라 픽셀 하나도 바꾸면 안 된다.
    """
    layer = op.find_graph(gname)[0]
    categories = [str(c) for c in frame[xcol]]
    values = [float(v) for v in frame[ycols[0]]]
    positions = _x_positions(frame[xcol])
    label_pt = decorate.value_label_pt(layer)

    colors = spec.get("colors") or {}
    hl_index = None
    if colors:
        labels = wks.get_labels("L")
        y_label = labels[1] if len(labels) > 1 else ycols[0]
        decorate.apply_colors(op, layer, wks, colors, categories, values, y_label)
        if colors.get("highlight"):
            hl_index = decorate.category_index(
                categories, colors["highlight"]["category"],
                "colors.highlight.category")

    value_labels = []
    if label_pt and (style_mode == "house" or colors):
        highlight = None
        if hl_index is not None:
            highlight = (hl_index, colors["highlight"]["color"])
        value_labels = decorate.place_value_labels(
            op, layer, positions, values, label_pt, highlight)

    if spec.get("title"):
        decorate.add_title(op, layer, spec["title"],
                           load_house_style()["axis_title_pt"])

    if spec.get("annotation") and decorate.is_anchor(spec["annotation"]["at"]):
        decorate.add_anchored_annotation(
            op, layer, spec["annotation"],
            load_house_style()["tick_label_pt"] * decorate.ANNOTATION_RATIO)
    elif spec.get("annotation"):
        # 화살표가 값 라벨을 뚫고 내려오지 않게, 그 라벨의 윗변을 바닥으로 준다.
        floor = None
        at = decorate.category_index(categories, spec["annotation"]["at"],
                                     "annotation.at")
        # 값이 비어 라벨을 건너뛴 자리는 None이다 (자리는 유지된다).
        lb = value_labels[at] if at < len(value_labels) else None
        if lb is not None:
            floor = lb.get_float("y") + lb.get_float("dy") / 2.0
        decorate.add_annotation(op, layer, spec["annotation"], positions, values,
                                categories, tip_floor=floor)
