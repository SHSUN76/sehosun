"""레시피의 선택 필드(title / colors / annotation)와 값 라벨 배치.

여기 있는 함수는 전부 "요청이 있을 때만" 그래프를 건드린다. 요청이 없으면 donor
상속 경로가 그대로 남는다 (골든 이미지 보존).

## 값 라벨에 대해 실측으로 알아낸 것 (2026-07-29)

bar_labeled donor의 값 라벨은 데이터 라벨(`layer.plot1.label.*`)이 아니다.
그 속성은 show=0인데도 라벨이 그려진다. 라벨의 실체는 레이어의 그래프 객체
`Style`, `Style1`, `Style2` — Origin이 '점별 스타일'을 저장할 때 만드는 홀더다.

  * 홀더 하나를 숨기면 해당 막대와 그 값 라벨이 함께 사라진다.
  * 홀더를 지우면 막대는 plot 기본색으로 돌아가고 값 라벨은 없어진다.
  * 홀더의 `fsize`는 그 점의 값 라벨 글자 크기다 (72로 키우면 라벨만 커진다).
  * 홀더의 `fillcolor`/`color`는 설정해도 먹지 않는다 (읽기값도 실제 색과 다르다).
  * 라벨의 세로 위치는 홀더의 어떤 속성으로도 노출되지 않는다. donor의 2번째 점은
    라벨이 '막대 top 위'가 아니라 '막대 top 아래'에 붙어 있고, 이건 데이터·축 범위와
    무관하게 점 인덱스를 따라간다 (값을 25/14.5/1.85로 줘도 2번째가 어긋난다).

그래서 고치는 방법은 하나뿐이다: 상속된 값 라벨을 무력화하고 우리가 직접 그린다.
`fsize`를 0.5로 낮추면 (0.1 이하는 Origin이 무시하고 기본 크기로 되돌린다) 렌더에
1px 이하만 남는다. 색을 지정받은 경우엔 홀더를 아예 지운다 — 홀더가 살아 있으면
plot 색 지정이 먹지 않기 때문이다.
"""
from __future__ import annotations

import math
import re

_HOLDER_NAME = re.compile(r"^Style\d*$")

# ---------------------------------------------------------------------------
# floating bar (범위 막대) — 2026-07-29 실측
#
# Origin의 열 플롯 막대 폭은 범주 간격의 80%다 (기본 gap 20%). LabTalk으로는 읽을
# 수도 쓸 수도 없다 — layer.gap / layer.barwidth / layer.colwidth / layer.plotN.gap
# 전부 nan이다. 렌더 픽셀 측정으로 확정했다 (축 0.5~2.5, 1200px 렌더에서 막대 폭
# 363px = 0.795 단위). 이 상수는 막대 위에 테두리 사각형을 정확히 겹치는 데 쓴다.
BAR_WIDTH = 0.8

# 그래프 오브젝트 타입 ID (GraphObjects.Add). 실측: 2=Text, 4/5=Line, 6=Polyline,
# 7=Curve, 8=Rect, 9=Circle, 11=Polygon. 0/1/3/10/12는 COM 예외.
_RECT_OBJ = 8

# 새 장식 요소의 글자 크기 — house style 값에서 파생한다 (별도 설정 항목을 늘리지
# 않기 위해). 기준: axis_title_pt=32, tick_label_pt=24.
SUBTITLE_RATIO = 0.65        # 제목 대비 부제목
VALUE_LABEL_RATIO = 0.80     # 눈금 라벨 대비 막대 끝 라벨
ANNOTATION_RATIO = 0.75      # 눈금 라벨 대비 주석
BAND_LABEL_RATIO = 0.70      # 눈금 라벨 대비 밴드 바깥 라벨

# annotation.at 이 범주 이름 대신 쓸 수 있는 위치 키워드.
ANNOTATION_ANCHORS = ("top_center", "top_left", "top_right")

# Origin은 0.1 이하의 fsize를 무시하고 기본 크기로 되돌린다 (실측). 0.5가 하한.
_MUTED_PT = 0.5

# 값 라벨 중심 = 값 + _LABEL_LIFT * 라벨높이. donor의 정상 라벨은 막대 top 위로
# 라벨 높이의 약 0.32배 간격을 두므로 0.5(절반) + 0.3(간격) = 0.8.
_LABEL_LIFT = 0.8


def _num(obj, prop):
    try:
        v = obj.GetNumProp(prop)
    except Exception:
        return None
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def style_holders(gl) -> list:
    """레이어의 점별 스타일 홀더(Style, Style1, ...)를 반환한다."""
    try:
        return [o for o in gl.obj.GraphObjects if _HOLDER_NAME.match(o.Name or "")]
    except Exception:
        return []


def value_label_pt(gl):
    """donor가 점별 값 라벨을 갖고 있으면 그 글자 크기, 아니면 None."""
    pts = [p for p in (_num(o, "fsize") for o in style_holders(gl)) if p and p > 1]
    return max(pts) if pts else None


def drop_point_styles(gl) -> int:
    """점별 스타일 홀더를 지운다 (막대는 plot 색을 따르게 되고 상속 라벨은 사라진다)."""
    removed = 0
    for o in style_holders(gl):
        try:
            o.Destroy()
            removed += 1
        except Exception:
            pass
    return removed


def mute_point_labels(gl) -> int:
    """상속된 값 라벨을 사실상 보이지 않게 만든다 (막대 색은 보존)."""
    muted = 0
    for o in style_holders(gl):
        try:
            o.SetNumProp("fsize", _MUTED_PT)
            muted += 1
        except Exception:
            pass
    return muted


def category_index(categories, wanted, field: str) -> int:
    """범주 이름 -> 인덱스. 없으면 조용히 넘기지 않고 즉시 실패한다."""
    cats = [str(c) for c in categories]
    target = str(wanted)
    if target not in cats:
        raise ValueError(f"{field} {target!r} not found in x values; has {cats}")
    return cats.index(target)


def is_missing(v) -> bool:
    """라벨로 찍을 수 없는 값인가 (빈 셀 / NaN / inf).

    csv의 빈 칸은 pandas에서 NaN으로 들어온다. `compute_range` 는 NaN을 명시적으로
    걸러내며 정상 동작하므로, 축은 멀쩡한데 라벨 단계에서만 죽는 상황이 실제로 난다.
    """
    if v is None:
        return True
    try:
        f = float(v)
    except (TypeError, ValueError):
        return True
    return math.isnan(f) or math.isinf(f)


def format_value(v) -> str:
    """숫자 -> 라벨 문자열.

    값이 없으면 즉시, 그리고 원인을 알 수 있게 실패한다. `int(nan)` 이 내는
    'cannot convert float NaN to integer' 로는 어느 셀이 비었는지 알 수 없다.
    라벨을 그리지 않고 넘어가는 판단은 호출자 몫이다 (`is_missing` 참조).
    """
    if is_missing(v):
        raise ValueError(f"cannot format a missing value ({v!r}); "
                         f"callers must skip the label instead")
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.6g}"


def bold(text: str) -> str:
    r"""Origin 텍스트를 굵게.

    텍스트 객체의 `bold` 속성은 설정해도 먹지 않는다 (set_int/LabTalk 모두 실측
    실패). donor의 축 제목이 쓰는 방식과 같은 `\b(...)` 이스케이프가 정본이다.
    """
    return f"\\b({text})"


def _center(op, lb, x, y_center):
    """텍스트 객체의 중심을 데이터 좌표로 놓는다 (x/y 속성이 중심이다 — 실측)."""
    lb.set_float("x", x)
    lb.set_float("y", y_center)
    op.lt_exec("doc -uw;")


def apply_colors(op, gl, wks, colors: dict, categories, values, y_label: str) -> None:
    """막대 색을 지정한다.

    base는 plot 전체 색. highlight는 해당 범주만 값이 있는 컬럼을 하나 더 만들어
    같은 자리에 두 번째 column plot으로 겹쳐 그린다 (Origin에서 점별 색을 지정하는
    LabTalk 경로 — colorlist/cmap/fillcolor — 는 전부 먹지 않았다, 실측).
    """
    base = colors.get("base")
    highlight = colors.get("highlight")
    if not base and not highlight:
        return

    # 홀더가 살아 있으면 plot 색이 무시된다.
    drop_point_styles(gl)

    plots = gl.plot_list()
    if not plots:
        raise RuntimeError("layer has no data plot to colour")
    if base:
        plots[0].color = base

    if not highlight:
        return

    idx = category_index(categories, highlight["category"],
                         "colors.highlight.category")
    col = wks.shape[1]
    nan = float("nan")
    series = [nan] * len(values)
    series[idx] = values[idx]
    # 같은 Long Name을 준다: 축 제목이 '%(?Y)' 치환 토큰인 donor에서 새 컬럼이
    # 축 제목으로 새어 나오지 않게 한다.
    wks.from_list(col, series, y_label)

    keep = (op.lt_float("layer.y.from"), op.lt_float("layer.y.to"),
            op.lt_float("layer.y.inc"))
    plot = gl.add_plot(wks, coly=col, colx=0, type="c")
    if plot is None:
        raise RuntimeError("could not add the highlight plot")
    plot.color = highlight["color"]
    try:
        gl.group(False)
    except Exception:
        pass
    if all(k == k for k in keep):
        op.lt_exec(f"layer.y.from = {keep[0]}; layer.y.to = {keep[1]}; "
                   f"layer.y.inc = {keep[2]}; doc -uw;")


def value_label_center(value: float, dy: float) -> float:
    """값 라벨의 중심 y.

    막대는 0을 기준으로 자라므로 음수 막대는 아래로 뻗는다. 라벨을 항상 +y로 올리면
    음수 막대에서는 라벨이 막대 *안*에 그려진다. 방향은 값의 부호를 따라간다.
    (0은 위로 — 높이 0짜리 막대라 어느 쪽이든 겹치지 않는다.)
    """
    lift = float(dy) * _LABEL_LIFT
    return float(value) - lift if float(value) < 0 else float(value) + lift


def place_value_labels(op, gl, positions, values, pt, highlight=None) -> list:
    """상속 값 라벨을 무력화하고, 막대 끝에 값 라벨을 직접 그린다.

    highlight는 (index, color) — 해당 막대의 값 라벨만 다른 색으로 쓴다.
    반환 목록은 입력과 길이·인덱스가 같다. 값이 없는 점은 `None` 이 들어간다 —
    건너뛴 자리를 압축하면 호출자의 인덱스 참조(주석 바닥 계산)가 밀린다.
    """
    mute_point_labels(gl)  # 색 지정 경로에서 이미 지워졌으면 아무 일도 안 한다

    made = []
    for i, (x, v) in enumerate(zip(positions, values)):
        if is_missing(v):
            made.append(None)
            continue
        lb = gl.add_label(bold(format_value(v)), x, v)
        if lb is None:
            raise RuntimeError(f"could not add a value label for point {i}")
        lb.set_int("attach", 2)
        lb.set_float("fsize", pt)
        if highlight and highlight[0] == i:
            lb.color = highlight[1]
        op.lt_exec("doc -uw;")
        dy = lb.get_float("dy")
        _center(op, lb, x, value_label_center(v, dy))
        made.append(lb)
    return made


def add_title(op, gl, text: str, pt: float, base: float | None = None):
    """플롯 영역 위 가운데에 그래프 제목을 놓는다.

    base: 제목이 올라앉을 바닥 y값. 기본은 플롯 상단(`layer.y.to`)이고, 부제목이
    있으면 그 윗변을 넘겨 제목을 한 칸 더 올린다.
    """
    x0, x1 = op.lt_float("layer.x.from"), op.lt_float("layer.x.to")
    y1 = op.lt_float("layer.y.to") if base is None else float(base)
    xc = (x0 + x1) / 2.0
    lb = gl.add_label(bold(text), xc, y1)
    if lb is None:
        raise RuntimeError("could not add the graph title")
    lb.set_int("attach", 2)
    lb.set_float("fsize", pt)
    op.lt_exec("doc -uw;")
    _center(op, lb, xc, y1 + lb.get_float("dy") * 0.75)
    return lb


def add_annotation(op, gl, annotation: dict, positions, values, categories,
                   tip_floor=None):
    """지정 범주를 가리키는 주석(텍스트 + 가능하면 화살표)을 놓는다.

    tip_floor: 화살촉이 이보다 아래로 내려가면 안 되는 y값 (값 라벨 위에 세우기 위함).
    반환값: (label, line|None) — 화살표를 못 그리면 line은 None이다.
    """
    idx = category_index(categories, annotation["at"], "annotation.at")
    x, v = positions[idx], values[idx]
    color = annotation.get("color")

    y0, y1 = op.lt_float("layer.y.from"), op.lt_float("layer.y.to")
    span = y1 - y0

    tip = v + span * 0.06                      # 막대 바로 위 (화살촉)
    if tip_floor is not None:
        tip = max(tip, tip_floor + span * 0.03)
    tail = min(tip + span * 0.28, y1 - span * 0.22)

    line = None
    if tail > tip:
        try:
            line = gl.add_line(x, tail, x, tip)
            if line is not None:
                line.set_int("attach", 2)
                line.set_int("arrowendshape", 2)   # 끝에 화살촉
                line.width = 3
                if color:
                    line.color = color
        except Exception:
            line = None

    lb = gl.add_label(annotation["text"], x, tail)
    if lb is None:
        raise RuntimeError("could not add the annotation text")
    lb.set_int("attach", 2)
    if color:
        lb.color = color
    op.lt_exec("doc -uw;")
    dy = lb.get_float("dy")
    base = tail if line is not None else tip
    _center(op, lb, x, base + span * 0.02 + dy / 2.0)
    return lb, line


# ===========================================================================
# floating bar 전용 — 여기부터는 전부 "레시피가 요청했을 때만" 호출된다.
# ===========================================================================


def is_anchor(at) -> bool:
    """annotation.at 이 범주 이름이 아니라 위치 키워드인가."""
    return isinstance(at, str) and at in ANNOTATION_ANCHORS


def anchor_x(at: str, x_from: float, x_to: float) -> float:
    """위치 키워드의 가로 기준점 (플롯 폭의 15% 안쪽으로 물린다)."""
    if not is_anchor(at):
        raise ValueError(f"annotation.at {at!r} is not a position keyword; "
                         f"known: {list(ANNOTATION_ANCHORS)}")
    span = x_to - x_from
    if at == "top_left":
        return x_from + span * 0.15
    if at == "top_right":
        return x_to - span * 0.15
    return (x_from + x_to) / 2.0


def validate_band(band, field: str) -> tuple[float, float]:
    """밴드 하나를 검증하고 (from, to)를 돌려준다. 잘못된 건 즉시 실패."""
    if not isinstance(band, dict):
        raise ValueError(f"{field} must be a mapping, got {type(band).__name__}")
    for key in ("from", "to"):
        if key not in band:
            raise ValueError(f"{field} needs a {key!r} value")
    try:
        lo, hi = float(band["from"]), float(band["to"])
    except (TypeError, ValueError):
        raise ValueError(f"{field} from/to must be numbers, got "
                         f"{band['from']!r}/{band['to']!r}") from None
    if not lo < hi:
        raise ValueError(f"{field} needs from < to, got from={lo} to={hi}")
    side = band.get("label_side", "right")
    if side not in ("right", "left"):
        raise ValueError(f"{field}.label_side must be 'right' or 'left', got {side!r}")
    alpha = band.get("alpha")
    if alpha is not None and not 0.0 <= float(alpha) <= 1.0:
        raise ValueError(f"{field}.alpha must be within 0..1, got {alpha!r}")
    return lo, hi


def band_rect(band: dict, x_from: float, x_to: float,
              field: str = "bands[]") -> tuple[float, float, float, float]:
    """밴드 사각형의 (중심x, 중심y, 폭, 높이). 순수 함수 — Origin이 필요 없다."""
    lo, hi = validate_band(band, field)
    return ((x_from + x_to) / 2.0, (lo + hi) / 2.0, x_to - x_from, hi - lo)


def transparency_of(alpha) -> float:
    """레시피의 alpha(=불투명도 0..1)를 Origin의 transparency(0..100)로."""
    if alpha is None:
        return 0.0
    return round((1.0 - float(alpha)) * 100.0, 3)


def format_value_label(fmt, value) -> str:
    """'Eox {v:.2f} V' + 5.55 -> 'Eox 5.55 V'.

    포맷이 없으면 기존 `format_value` 와 같게 찍는다. `{v}` 를 참조하지 않는
    포맷은 값을 잃어버린 것이므로 조용히 넘기지 않고 실패시킨다.
    """
    if is_missing(value):
        raise ValueError(f"cannot format a missing value ({value!r}); "
                         f"callers must skip the label instead")
    if fmt is None:
        return format_value(value)
    if not isinstance(fmt, str):
        raise ValueError(f"value label format must be a string, got {fmt!r}")
    if "{v" not in fmt:
        raise ValueError(f"value label format {fmt!r} does not reference {{v}}")
    try:
        return fmt.format(v=float(value))
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"invalid value label format {fmt!r}: {e}") from None


def _rect(op, gl, xc, yc, dx, dy, line=None, fill=None, alpha=None, width=None):
    """데이터 좌표에 사각형 그래프 오브젝트를 놓는다.

    **크기를 먼저, 위치를 나중에** 준다. 반대로 하면 dx/dy 를 줄 때 객체가 한쪽
    모서리를 고정한 채 자라서 중심이 밀린다 (실측: y를 2.15로 준 뒤 dy=6.8을 주면
    중심이 3.69로 이동). 색은 `Rect.color`(테두리) / `Rect.fillcolor`(채움) —
    plot에는 없는 속성이라 테두리 색을 지정하는 유일한 경로다.
    """
    obj = gl.obj.GraphObjects.Add(_RECT_OBJ)
    if obj is None:
        raise RuntimeError("could not add a rectangle graph object")
    name = obj.Name
    obj.SetNumProp("attach", 2)
    op.lt_exec("doc -uw;")
    if not op.lt_exec(f"{name}.dx = {dx}; {name}.dy = {dy}; doc -uw;"):
        raise RuntimeError(f"could not size the rectangle {name}")
    if not op.lt_exec(f"{name}.x = {xc}; {name}.y = {yc}; doc -uw;"):
        raise RuntimeError(f"could not place the rectangle {name}")
    cmds = []
    if line:
        cmds.append(f"{name}.color = color({line});")
    if fill:
        cmds.append(f"{name}.fillcolor = color({fill});")
    if alpha is not None:
        cmds.append(f"{name}.transparency = {transparency_of(alpha)};")
    if width is not None:
        cmds.append(f"{name}.linewidth = {width};")
    if cmds:
        op.lt_exec(" ".join(cmds) + " doc -uw;")
    return obj


def color_floating_series(op, gl, categories, series: dict) -> int:
    """floating 플롯의 채움색을 계열별로 지정한다.

    floating column 레이어는 범주 하나가 plot 두 개(아래/위)로 들어간다.
    범주 i(0부터)는 plot 2i+1, 2i+2 이다 (실측).
    """
    plots = gl.plot_list()
    painted = 0
    for i, cat in enumerate(categories):
        style = series.get(cat)
        if not style or not style.get("fill"):
            continue
        for k in (2 * i, 2 * i + 1):
            if k < len(plots):
                plots[k].color = style["fill"]
        painted += 1
    op.lt_exec("doc -uw;")
    return painted


def draw_floating_bars(op, gl, positions, lows, highs, categories, series: dict,
                       line_width: float = 3) -> list:
    """계열색이 지정된 막대 위에 테두리 있는 사각형을 정확히 겹쳐 그린다.

    plot에는 테두리 색 속성이 없다 (`fillcolor`/`patterncolor`/`bordercolor`/
    `linecolor`/`linewidth` 전부 nan, `set -c` 는 채움색과 같은 곳으로 간다).
    그래서 테두리 색을 요구받은 계열만 막대와 같은 자리·같은 크기의 Rect로 덮는다.
    폭은 `BAR_WIDTH`(=0.8) — Origin 열 플롯의 실측 막대 폭이다.

    막대가 없는 행(빈 셀 = NaN)은 건너뛴다. 그냥 계산하면 `dy = nan` 인 Rect를
    Origin에 넘기게 되고, 그 순간 그래프가 통째로 실패한다 (다른 라벨 경로는 전부
    `is_missing` 으로 걸러 내는데 여기만 빠져 있었다).
    """
    made = []
    for i, cat in enumerate(categories):
        style = series.get(cat)
        if not style:
            continue
        if is_missing(lows[i]) or is_missing(highs[i]):
            continue
        lo, hi = float(lows[i]), float(highs[i])
        made.append(_rect(op, gl, positions[i], (lo + hi) / 2.0,
                          BAR_WIDTH, hi - lo,
                          line=style.get("line"), fill=style.get("fill"),
                          width=line_width))
    return made


def add_bands(op, gl, bands, pt: float) -> list:
    """가로 음영 밴드 + (요청 시) 플롯 바깥 라벨.

    막대 위에 겹쳐 그린다 — 반투명이 의미를 가지려면 막대보다 위에 있어야 한다.
    """
    x0, x1 = op.lt_float("layer.x.from"), op.lt_float("layer.x.to")
    made = []
    for i, band in enumerate(bands):
        xc, yc, dx, dy = band_rect(band, x0, x1, f"bands[{i}]")
        rect = _rect(op, gl, xc, yc, dx, dy,
                     line=band.get("fill"), fill=band.get("fill"),
                     alpha=band.get("alpha", 1.0), width=1)
        label = None
        if band.get("label"):
            label = _band_label(op, gl, band, x0, x1, yc, pt)
        made.append((rect, label))
    return made


def _band_label(op, gl, band, x0, x1, yc, pt):
    """밴드 라벨을 플롯 바깥(좌/우)에 놓는다."""
    side = band.get("label_side", "right")
    span = x1 - x0
    anchor = x1 if side == "right" else x0
    lb = gl.add_label(band["label"], anchor, yc)
    if lb is None:
        raise RuntimeError("could not add the band label")
    lb.set_int("attach", 2)
    lb.set_float("fsize", pt)
    if band.get("label_color"):
        lb.color = band["label_color"]
    op.lt_exec("doc -uw;")
    dx = lb.get_float("dx")
    gap = span * 0.04 + dx / 2.0
    _center(op, lb, anchor + gap if side == "right" else anchor - gap, yc)
    return lb


def place_range_labels(op, gl, positions, anchors, values, spec: dict, pt: float,
                       above: bool, colors=None) -> list:
    """막대 위(above=True) 또는 아래에 값 라벨을 붙인다.

    anchors: 라벨이 붙을 막대 끝의 y값. values: 실제로 찍을 숫자 (다른 컬럼일 수 있다).
    값이나 붙일 자리가 비어 있는 점은 `None` 을 남기고 건너뛴다 (인덱스 보존).
    """
    y0, y1 = op.lt_float("layer.y.from"), op.lt_float("layer.y.to")
    span = y1 - y0
    fmt = spec.get("format")
    made = []
    for i, x in enumerate(positions):
        if is_missing(values[i]) or is_missing(anchors[i]):
            made.append(None)
            continue
        lb = gl.add_label(bold(format_value_label(fmt, values[i])), x, anchors[i])
        if lb is None:
            raise RuntimeError(f"could not add a range label for point {i}")
        lb.set_int("attach", 2)
        lb.set_float("fsize", pt)
        if colors and colors[i]:
            lb.color = colors[i]
        op.lt_exec("doc -uw;")
        dy = lb.get_float("dy")
        pad = span * 0.015 + dy / 2.0
        _center(op, lb, x, anchors[i] + pad if above else anchors[i] - pad)
        made.append(lb)
    return made


def add_subtitle(op, gl, text: str, pt: float):
    """플롯 바로 위 부제목. 반환: (label, 윗변 y) — 제목을 그 위에 올리기 위함."""
    x0, x1 = op.lt_float("layer.x.from"), op.lt_float("layer.x.to")
    y1 = op.lt_float("layer.y.to")
    xc = (x0 + x1) / 2.0
    lb = gl.add_label(bold(text), xc, y1)
    if lb is None:
        raise RuntimeError("could not add the subtitle")
    lb.set_int("attach", 2)
    lb.set_float("fsize", pt)
    op.lt_exec("doc -uw;")
    dy = lb.get_float("dy")
    center = y1 + dy * 0.75
    _center(op, lb, xc, center)
    return lb, center + dy / 2.0


def add_anchored_annotation(op, gl, annotation: dict, pt: float):
    """위치 키워드(top_center 등)로 지정된 주석. 플롯 안쪽 상단에 놓는다."""
    x0, x1 = op.lt_float("layer.x.from"), op.lt_float("layer.x.to")
    y0, y1 = op.lt_float("layer.y.from"), op.lt_float("layer.y.to")
    span = y1 - y0
    x = anchor_x(annotation["at"], x0, x1)
    lb = gl.add_label(annotation["text"], x, y1)
    if lb is None:
        raise RuntimeError("could not add the annotation text")
    lb.set_int("attach", 2)
    lb.set_float("fsize", pt)
    if annotation.get("color"):
        lb.color = annotation["color"]
    op.lt_exec("doc -uw;")
    dy = lb.get_float("dy")
    _center(op, lb, x, y1 - span * 0.03 - dy / 2.0)
    return lb
