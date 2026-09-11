"""house style 적용과 축 범위 재계산.

donor는 자기 데이터에 맞는 축 범위를 갖고 있다. 새 데이터를 주입해도 그 범위가
그대로 남으므로 (검증됨), 여기서 다시 계산해 넣어야 데이터가 잘리지 않는다.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

import yaml

_STYLE_PATH = Path(__file__).resolve().parents[1] / "data" / "house_style.yaml"


def load_house_style(path: Path | None = None) -> dict:
    return yaml.safe_load(Path(path or _STYLE_PATH).read_text(encoding="utf-8"))


def _nice_step(span: float) -> float:
    """사람이 읽기 좋은 눈금 간격 (1/2/5 x 10^n)."""
    if span <= 0:
        return 1.0
    raw = span / 5.0
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def finite_values(values: Iterable[float]) -> list[float]:
    """숫자로 쓸 수 있는 값만 남긴다 (빈 셀 = NaN 은 버린다)."""
    out = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not (math.isnan(f) or math.isinf(f)):
            out.append(f)
    return out


def compute_range(values: Iterable[float], pad: float = 0.05,
                  anchor_zero: bool = True) -> tuple[float, float]:
    """데이터에서 축 범위를 만든다. 최대/최소를 절대 자르지 않는다.

    anchor_zero: 막대는 0에서 자라므로, 축이 0을 물지 않으면 막대 길이가 크기를
        나타내지 못한다 (전부 음수인 데이터에서 실제로 그렇게 된다: -5..-3 이면
        축이 -5.5..-2.5 로 잡혀 막대가 어디서 시작하는지 알 수 없다). 그래서 한쪽
        부호로만 이뤄진 데이터는 반대편 끝을 0에 붙인다.
        범위 막대(floating bar)처럼 막대 바닥이 0이 아닌 축은 False로 끈다 — 거기서
        0을 강제하면 창(window)만 좁아지고 얻는 게 없다.
    """
    vals = finite_values(values)
    if not vals:
        raise ValueError("cannot compute an axis range from empty data")

    lo, hi = min(vals), max(vals)
    if lo == hi:
        lo, hi = lo - 1.0, hi + 1.0

    span = hi - lo
    step = _nice_step(span)

    low = math.floor((lo - span * pad) / step) * step
    high = math.ceil((hi + span * pad) / step) * step

    if anchor_zero:
        if lo >= 0:
            low = 0.0
        elif hi <= 0:
            high = 0.0
    return low, high


def clipped_values(lo: float, hi: float, values: Iterable[float]) -> list[float]:
    """축 [lo, hi] 밖으로 나가 잘려 버리는 값들. 없으면 빈 목록."""
    if lo is None or hi is None or math.isnan(lo) or math.isnan(hi):
        return []
    return [v for v in finite_values(values) if v < lo or v > hi]


def apply_axis_range(op, axis: str, values: Sequence[float],
                     anchor_zero: bool = True) -> tuple[float, float]:
    lo, hi = compute_range(values, anchor_zero=anchor_zero)
    op.lt_exec(f"layer.{axis}.from = {lo}; layer.{axis}.to = {hi}; "
               f"layer.{axis}.inc = {_nice_step(hi - lo)};")
    return lo, hi


def apply_house_style(op, style: dict | None = None) -> None:
    """활성 그래프에 house style을 강제 적용한다.

    호출 전에 대상 그래프가 활성화돼 있어야 한다.
    """
    s = style or load_house_style()
    ticks = s["tick_bitmask"][s["tick_direction"]]
    bold = 1 if s["tick_label_bold"] else 0

    cmds = []
    for ax in ("x", "y"):
        cmds.append(f"layer.{ax}.label.pt = {s['tick_label_pt']};")
        cmds.append(f"layer.{ax}.label.bold = {bold};")
        cmds.append(f"layer.{ax}.thickness = {s['axis_thickness']};")
        cmds.append(f"layer.{ax}.ticks = {ticks};")
    cmds.append("doc -uw;")
    op.lt_exec(" ".join(cmds))

    # 축 제목은 별도의 텍스트 오브젝트다. 그래프에 없는 제목(bar_labeled에는 XB가
    # 없다)에 fsize를 쓰면 COM이 예외를 던지고, 한 배치로 묶여 있으면 그 뒤 명령이
    # 통째로 유실된다. 제목마다 따로 실행하고, 글자가 없는 제목은 건드리지 않는다
    # (크기를 줘도 보이지 않으므로 의미가 없다).
    for title in ("XB", "YL", "YR"):
        try:
            if not op.get_lt_str(f"{title}.text$"):
                continue
            op.lt_exec(f"{title}.fsize = {s['axis_title_pt']};")
        except Exception:
            pass
    op.lt_exec("doc -uw;")
