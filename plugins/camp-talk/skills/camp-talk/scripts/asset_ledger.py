#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asset_ledger.py — camp-talk 자산 원장 생성기.

그림을 슬라이드에 올리기 전에 "이 그림이 무엇인지"를 기계가 먼저 측정한다.
픽셀 크기·종횡비(AR)·형태 class·권장 layout·해상도 한계·흰 여백 비율·캡션 밴드
의심 여부를 자동으로 채우고, 사람(모델)이 눈으로만 확인할 수 있는 두 필드
(`min_text_px`, `embedded_text_check`)는 null로 남겨 둔다. deck_qa.py의
LEDGER_TEXT_CHECK 게이트가 `embedded_text_check != "ok"`인 자산의 사용을
막으므로, 눈으로 확인하지 않은 그림은 덱에 들어갈 수 없다.

사용법
    python asset_ledger.py <images_dir_or_list> --out asset_ledger.json
                           [--crops crops.json] [--crops-from-trim] [--autotrim]
                           [--crop-dir DIR] [--trim-dir DIR] [--ppi 110]
    python asset_ledger.py --check asset_ledger.json --out asset_ledger.json

crops.json 형식과 좌표계
    {"F01": [{"name": "fig1b_peak", "box": [x0, y0, x1, y1]}]}
    box 는 **원본 이미지의 px 좌표**다(좌상단 기준, x1/y1 배타적).
    적용 순서는 **crop 이 먼저, autotrim 이 나중**이다 — 원본에서 잘라낸 뒤
    그 사본의 흰 여백을 다듬는다. 그래서 crops.json 을 쓸 때 autotrim 사본의
    좌표를 넣으면 엉뚱한 자리가 잘린다.
    trim 사본을 보며 좌표를 딴 경우에는 `--crops-from-trim` 을 주면 된다.
    저장해 둔 trim offset(잘라낸 좌상단 위치)을 더해 원본 좌표로 환산한다.

min_text_px 값의 뜻
    양수(px)        그림 안 가장 작은 글자의 높이
    0 또는 "none"   그림 안에 글자가 없음 — 게이트 통과
    null            아직 확인하지 않음 — 이것만 '미확인'이다
    양수인데 13.2 px(= 0.12 in x 110 ppi) 미만이면 두 게이트를 동시에 만족시킬
    수 없으므로 advice 에 재플롯 권고를 남긴다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

# ---- layout-grid.md §2 auto 규칙 ------------------------------------------
AR_WIDE = 2.4        # AR >= 2.4      -> figure-top
AR_LANDSCAPE = 1.2   # 1.2 <= AR <2.4 -> figure-left
AR_SQUARE_LOW = 0.8  # 0.8 <= AR <1.2 -> figure-right (square)
DEFAULT_PPI = 110    # layout-grid.md §3-4 해상도 게이트

WHITE_THRESHOLD = 245   # 이 값 이상이면 "흰 픽셀"로 본다
INK_ROW_MIN = 0.010     # 텍스트 밴드로 볼 최소 잉크 비율
INK_ROW_MAX = 0.35      # 이 이상이면 그림/색면이지 텍스트 줄이 아니다
BAND_FRACTION = 0.20    # 상·하단 20% 영역을 캡션 밴드 후보로 본다
BAND_SPAN_MIN = 0.50    # 캡션 줄은 폭의 절반 이상을 가로지른다
BAND_RUNS_MIN = 10      # 한 행에서 글자처럼 끊겼다 이어지는 최소 횟수
BAND_BLANK_INK = 0.004  # 이 아래면 '빈 행' — 그림 본체와 캡션을 가르는 틈
BAND_GAP_FRACTION = 0.03  # 캡션 밴드는 본체와 높이의 3% 이상 떨어져 있어야 한다

# 0.12 in(작은 글씨 게이트) x 110 ppi(해상도 게이트) = 13.2 px.
# 원본 글자가 이보다 작으면 두 게이트를 동시에 만족시킬 방법이 없다.
MIN_TEXT_PX_FLOOR = 13.2
MIN_TEXT_PX_ADVICE = (
    "PPI≥110과 TEXT_TINY≥0.12 in을 동시에 만족할 수 없는 자산 — 재플롯 또는 "
    "원본 고해상 렌더(figure set pptx를 300 dpi로) 필요"
)

MIN_TEXT_PX_NOTE = (
    "모델이 그림을 직접 열어 채울 것: 그림 안 가장 작은 글자의 높이(원본 px). "
    "배치 배율로 환산해 슬라이드 상 0.12 in(약 9 pt) 미만이면 그 그림은 나눠야 한다. "
    "허용값 — 양수(px) | 0 또는 \"none\"(그림 안에 글자가 없음, 게이트 통과) | "
    "null(아직 확인하지 않음). null 만 '미확인'이며, 0/\"none\" 은 확인을 마친 값이다. "
    f"양수인데 {MIN_TEXT_PX_FLOOR} px 미만이면 advice 가 붙는다."
)
EMBEDDED_TEXT_CHECK_NOTE = (
    "모델이 그림을 직접 열어 채울 것: 그림 안에 인쇄된 문구를 읽고 철회·폐기·"
    "미검증 어휘(retracted, withdrawn, preliminary, do not cite, 철회, 폐기, "
    "가상 데이터 등)나 forbidden 수치가 있는지 확인한 뒤 \"ok\" 또는 "
    "\"contains: <읽은 문구>\"로 채운다. null 이면 deck_qa 의 LEDGER_TEXT_CHECK 가 fail 한다."
)


# ---------------------------------------------------------------- helpers --
def asset_id_from_name(path: Path) -> str:
    """파일명 앞 토큰을 자산 id 로 쓴다(F03_Fig1_peakforce.png -> F03)."""
    stem = path.stem
    for sep in ("_", "-", " "):
        if sep in stem:
            return stem.split(sep, 1)[0]
    return stem


def classify(ar: float) -> str:
    if ar >= AR_WIDE:
        return "wide"
    if ar >= AR_LANDSCAPE:
        return "landscape"
    if ar >= AR_SQUARE_LOW:
        return "square"
    return "tall"


def recommend_layout(ar: float) -> str:
    """layout-grid.md §2: auto 규칙(자산 1개 기준)."""
    if ar >= AR_WIDE:
        return "figure-top"
    if ar >= AR_LANDSCAPE:
        return "figure-left"
    return "figure-right"


def load_gray(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        gray = im.convert("L")
        return np.asarray(gray, dtype=np.uint8)


def margin_ratios(gray: np.ndarray) -> dict:
    """테두리에서 안쪽으로 들어가며 '전부 흰' 행/열이 몇 %인지 센다."""
    h, w = gray.shape
    ink = gray < WHITE_THRESHOLD
    row_has_ink = ink.any(axis=1)
    col_has_ink = ink.any(axis=0)

    def lead(mask) -> int:
        idx = np.flatnonzero(mask)
        return int(idx[0]) if idx.size else int(mask.size)

    def trail(mask) -> int:
        idx = np.flatnonzero(mask)
        return int(mask.size - 1 - idx[-1]) if idx.size else int(mask.size)

    top, bottom = lead(row_has_ink), trail(row_has_ink)
    left, right = lead(col_has_ink), trail(col_has_ink)
    return {
        "top": round(top / h, 4),
        "bottom": round(bottom / h, 4),
        "left": round(left / w, 4),
        "right": round(right / w, 4),
        "total": round(1.0 - ((h - top - bottom) * (w - left - right)) / float(h * w), 4),
        "content_box_px": [left, top, w - right, h - bottom],
    }


def _row_runs(row_ink: np.ndarray) -> int:
    """한 행에서 잉크가 끊겼다 이어지는 횟수 — 글자 줄은 run 이 많다."""
    if not row_ink.any():
        return 0
    diff = np.diff(row_ink.astype(np.int8))
    return int((diff == 1).sum()) + int(row_ink[0])


def caption_band_suspect(gray: np.ndarray) -> dict:
    """상·하단 20% 영역에 가로로 긴 '글자 줄'이 있는지 휴리스틱으로 본다.

    조립 figure 의 하단 캡션("Figure S17. Cumulative Intrusion vs ...")이나
    상단 제목 줄을 잘라내지 않고 슬라이드에 올리면 슬라이드 캡션과 이중으로
    찍힌다. 그 상황을 미리 알린다.

    축 라벨·패널 문자와 구분하려고 세 조건을 함께 건다:
      (1) 행의 잉크가 글자처럼 여러 번 끊긴다(runs >= 10)
      (2) 그 줄이 그림 폭의 절반 이상을 가로지른다
      (3) 그림 본체와 빈 행으로 갈려 있거나 이미지 가장자리에 붙어 있다
    """
    h, w = gray.shape
    ink = gray < WHITE_THRESHOLD
    band_h = max(1, int(round(h * BAND_FRACTION)))
    min_run = max(2, int(round(h * 0.008)))
    gap_min = max(2, int(round(h * BAND_GAP_FRACTION)))
    edge_px = max(1, int(round(h * 0.01)))
    result = {"suspect": False, "where": [], "detail": {}}

    for where, sl in (("top", slice(0, band_h)), ("bottom", slice(h - band_h, h))):
        sub = ink[sl]
        n = sub.shape[0]
        frac = sub.mean(axis=1)
        blank = frac < BAND_BLANK_INK
        text_like = np.zeros(n, dtype=bool)
        for i in range(n):
            if not (INK_ROW_MIN <= frac[i] <= INK_ROW_MAX):
                continue
            row = sub[i]
            cols = np.flatnonzero(row)
            if cols.size == 0:
                continue
            if (cols[-1] - cols[0] + 1) / float(w) < BAND_SPAN_MIN:
                continue
            if _row_runs(row) < BAND_RUNS_MIN:
                continue
            text_like[i] = True

        runs, start = [], None
        for i, v in enumerate(text_like):
            if v and start is None:
                start = i
            if not v and start is not None:
                runs.append((start, i))
                start = None
        if start is not None:
            runs.append((start, n))

        bands = []
        for a, b in runs:
            if b - a < min_run:
                continue
            if where == "top":
                gap = 0
                for i in range(b, min(n, b + gap_min * 2 + 2)):
                    if not blank[i]:
                        break
                    gap += 1
                touches_edge = a <= edge_px
                abs_rows = [int(a), int(b)]
            else:
                gap = 0
                for i in range(a - 1, max(-1, a - 1 - (gap_min * 2 + 2)), -1):
                    if not blank[i]:
                        break
                    gap += 1
                touches_edge = b >= n - edge_px
                abs_rows = [int(h - band_h + a), int(h - band_h + b)]
            if gap >= gap_min or touches_edge:
                bands.append({"rows_px": abs_rows, "height_px": int(b - a),
                              "gap_px": int(gap), "touches_edge": bool(touches_edge)})

        result["detail"][where] = {
            "text_like_rows": int(text_like.sum()),
            "bands": bands,
        }
        if bands:
            result["suspect"] = True
            result["where"].append(where)
    return result


def autotrim_box(gray: np.ndarray, pad: int = 4) -> tuple | None:
    ink = gray < WHITE_THRESHOLD
    rows = np.flatnonzero(ink.any(axis=1))
    cols = np.flatnonzero(ink.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    h, w = gray.shape
    y0 = max(0, int(rows[0]) - pad)
    y1 = min(h, int(rows[-1]) + 1 + pad)
    x0 = max(0, int(cols[0]) - pad)
    x1 = min(w, int(cols[-1]) + 1 + pad)
    if (x1 - x0, y1 - y0) == (w, h):
        return None
    return (x0, y0, x1, y1)


# ------------------------------------------------------------ measurement --
def measure(path: Path, aid: str, ppi: int, parent: str | None = None,
            derived: str | None = None) -> dict:
    with Image.open(path) as im:
        w, h = im.size
    ar = w / float(h)
    gray = load_gray(path)
    margins = margin_ratios(gray)
    band = caption_band_suspect(gray)

    warnings = []
    if margins["total"] >= 0.12:
        warnings.append(
            f"흰 여백 {margins['total']*100:.0f}% — --autotrim 또는 crop 권장")
    max_w = w / float(ppi)
    if max_w < 4.0:
        warnings.append(
            f"{ppi} ppi 기준 최대 폭 {max_w:.2f} in — 전폭 배치 불가, two-up/figure-stack 검토")

    # 캡션 밴드는 게이트가 아니라 힌트다 — 사람이 그림을 열어 볼 자리를 짚어 줄 뿐이다.
    checks = []
    if band["suspect"]:
        where = set(band["where"])
        pos = ("상·하단" if where == {"top", "bottom"}
               else "상단" if where == {"top"} else "하단")
        checks.append(f"{pos} 밴드 확인 필요")

    entry = {
        "id": aid,
        "path": str(path).replace("\\", "/"),
        "file": path.name,
        "px": {"w": w, "h": h},
        "ar": round(ar, 4),
        "class": classify(ar),
        "recommended_layout": recommend_layout(ar),
        "max_width_in_at_ppi": round(max_w, 3),
        "ppi_basis": ppi,
        "margin_ratio": margins,
        "caption_band_suspect": band,
        "min_text_px": None,
        "min_text_px_note": MIN_TEXT_PX_NOTE,
        "embedded_text_check": None,
        "embedded_text_check_note": EMBEDDED_TEXT_CHECK_NOTE,
        "warnings": warnings,
        "checks": checks,
        "advice": [],
    }
    if parent:
        entry["parent_id"] = parent
    if derived:
        entry["derived"] = derived
    apply_min_text_advice(entry)
    return entry


def min_text_state(value) -> str:
    """min_text_px 값의 상태 — unchecked / none / ok / floor."""
    if value is None:
        return "unchecked"
    if isinstance(value, str):
        return "none" if value.strip().lower() == "none" else "unchecked"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "unchecked"
    if v <= 0:
        return "none"
    return "floor" if v < MIN_TEXT_PX_FLOOR else "ok"


def apply_min_text_advice(entry: dict) -> str:
    """min_text_px 를 읽어 13.2 px 미만이면 advice 를 남긴다.

    0 또는 "none" 은 '그림 안에 글자가 없음'이라 게이트를 통과한다.
    null 만 '아직 확인하지 않음'이다."""
    entry.setdefault("advice", [])
    entry["advice"] = [a for a in entry["advice"] if not a.startswith("min_text_px")]
    state = min_text_state(entry.get("min_text_px"))
    if state == "floor":
        entry["advice"].append(
            f"min_text_px {entry['min_text_px']} px < {MIN_TEXT_PX_FLOOR} px — "
            + MIN_TEXT_PX_ADVICE)
    return state


def collect_inputs(targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.suffix.lower() in IMAGE_EXTS:
                    out.append(f)
        elif p.is_file():
            if p.suffix.lower() in IMAGE_EXTS:
                out.append(p)
            else:  # 목록 텍스트 파일
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        out.append(Path(line))
        else:
            print(f"[warn] 입력을 찾을 수 없음: {t}", file=sys.stderr)
    return out


# ------------------------------------------------------------------ table --
def _wide(s: str) -> int:
    """한글 등 전각 문자를 2칸으로 세어 표 정렬을 맞춘다."""
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0x2E7F and ord(ch) not in (0x2022,) else 1
    return n


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _wide(s))


def print_table(entries: list[dict]) -> None:
    headers = ["id", "px", "AR", "class", "layout", "max_w(in)", "warn", "확인"]
    rows = []
    for e in entries:
        warn = "; ".join(e["warnings"]) if e["warnings"] else "-"
        hints = list(e.get("checks") or []) + list(e.get("advice") or [])
        rows.append([
            e["id"] + ("*" if e.get("parent_id") else ""),
            f"{e['px']['w']}x{e['px']['h']}",
            f"{e['ar']:.2f}",
            e["class"],
            e["recommended_layout"],
            f"{e['max_width_in_at_ppi']:.2f}",
            warn,
            "; ".join(hints) if hints else "-",
        ])
    widths = [max(_wide(h), *(_wide(r[i]) for r in rows)) if rows else _wide(h)
              for i, h in enumerate(headers)]
    widths[-2] = min(widths[-2], 46)
    widths[-1] = min(widths[-1], 46)
    print(" | ".join(_pad(h, w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        r[-2] = r[-2][:46]
        r[-1] = r[-1][:46]
        print(" | ".join(_pad(c, w) for c, w in zip(r, widths)))


# ------------------------------------------------------------------- main --
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="camp-talk 자산 원장 생성기")
    ap.add_argument("inputs", nargs="*",
                    help="이미지 디렉터리, 이미지 파일들, 또는 경로 목록 텍스트 파일 "
                         "(--check 모드에서는 생략)")
    ap.add_argument("--out", required=True, help="asset_ledger.json 출력 경로")
    ap.add_argument("--crops",
                    help="crops.json 경로. box 좌표는 **원본 이미지 픽셀 기준**이며, "
                         "crop 은 **autotrim 보다 먼저** 적용된다(자른 뒤 다듬는 순서). "
                         "trim 사본 기준 좌표를 쓰려면 --crops-from-trim 을 함께 준다")
    ap.add_argument("--crops-from-trim", action="store_true",
                    help="crops.json 의 box 를 autotrim 사본 기준 좌표로 읽어 "
                         "trim offset 만큼 더해 원본 좌표로 환산한다")
    ap.add_argument("--check", metavar="LEDGER",
                    help="기존 원장을 다시 읽어 min_text_px 를 판정하고 advice 를 "
                         f"갱신한다({MIN_TEXT_PX_FLOOR} px 미만이면 재플롯 권고). "
                         "이미지를 다시 읽지 않는다")
    ap.add_argument("--crop-dir", help="크롭 저장 디렉터리(기본: <out 폴더>/figures_cropped)")
    ap.add_argument("--trim-dir", help="autotrim 저장 디렉터리(기본: <out 폴더>/figures_trimmed)")
    ap.add_argument("--autotrim", action="store_true", help="흰 여백 제거 사본 생성(원본 보존)")
    ap.add_argument("--ppi", type=int, default=DEFAULT_PPI, help="해상도 게이트 기준(기본 110)")
    ap.add_argument("--quiet", action="store_true", help="콘솔 표 생략")
    args = ap.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop_dir = Path(args.crop_dir) if args.crop_dir else out_path.parent / "figures_cropped"
    trim_dir = Path(args.trim_dir) if args.trim_dir else out_path.parent / "figures_trimmed"

    if args.check:
        return run_check(Path(args.check), out_path, args.quiet)

    if not args.inputs:
        print("[error] 이미지 입력이 없다(또는 --check 를 쓸 것).", file=sys.stderr)
        return 2
    if not args.quiet:
        print("crops 좌표계: 원본 이미지 픽셀 기준"
              + (" ← --crops-from-trim: trim 사본 좌표를 원본으로 환산한다"
                 if args.crops_from_trim else "")
              + " · 적용 순서: crop → autotrim")

    files = collect_inputs(args.inputs)
    if not files:
        print("[error] 처리할 이미지가 없다.", file=sys.stderr)
        return 2

    entries: list[dict] = []
    by_id: dict[str, dict] = {}
    for f in files:
        aid = asset_id_from_name(f)
        base = aid
        n = 2
        while aid in by_id:
            aid = f"{base}#{n}"
            n += 1
        e = measure(f, aid, args.ppi)
        entries.append(e)
        by_id[aid] = e

    # --- crops -------------------------------------------------------------
    if args.crops:
        crops = json.loads(Path(args.crops).read_text(encoding="utf-8"))
        crop_dir.mkdir(parents=True, exist_ok=True)
        for pid, specs in crops.items():
            parent = by_id.get(pid)
            if parent is None:
                print(f"[warn] crops.json 의 id '{pid}' 가 원장에 없다.", file=sys.stderr)
                continue
            offset = (0, 0)
            if args.crops_from_trim:
                tbox = trim_offset_for(parent)
                if tbox is None:
                    print(f"[warn] '{pid}' 는 잘라낼 흰 여백이 없어 trim offset 이 "
                          f"(0,0) 이다.", file=sys.stderr)
                else:
                    offset = (tbox[0], tbox[1])
                    parent["trim_offset"] = [tbox[0], tbox[1]]
            for spec in specs:
                name = spec["name"]
                x0, y0, x1, y1 = (int(v) for v in spec["box"])
                if offset != (0, 0):
                    x0, x1 = x0 + offset[0], x1 + offset[0]
                    y0, y1 = y0 + offset[1], y1 + offset[1]
                    x1 = min(x1, parent["px"]["w"]); y1 = min(y1, parent["px"]["h"])
                dst = crop_dir / f"{pid}_{name}.png"
                with Image.open(parent["path"]) as im:
                    im.crop((x0, y0, x1, y1)).save(dst)
                child = measure(dst, f"{pid}_{name}", args.ppi,
                                parent=pid, derived="crop")
                child["crop_box"] = [x0, y0, x1, y1]
                child["crop_coords"] = "original"
                if offset != (0, 0):
                    child["crop_box_as_given"] = [int(v) for v in spec["box"]]
                    child["crop_coords"] = "from_trim"
                    child["trim_offset"] = list(offset)
                entries.append(child)
                by_id[child["id"]] = child

    # --- autotrim ----------------------------------------------------------
    if args.autotrim:
        trim_dir.mkdir(parents=True, exist_ok=True)
        for e in list(entries):
            if e.get("derived"):
                continue
            gray = load_gray(Path(e["path"]))
            box = autotrim_box(gray)
            if box is None:
                continue
            dst = trim_dir / f"{e['id']}_trim.png"
            with Image.open(e["path"]) as im:
                im.crop(box).save(dst)
            child = measure(dst, f"{e['id']}_trim", args.ppi,
                            parent=e["id"], derived="autotrim")
            child["crop_box"] = list(box)
            # trim 사본 좌표 -> 원본 좌표 환산에 쓰는 offset
            child["trim_offset"] = [box[0], box[1]]
            e["trim_offset"] = [box[0], box[1]]
            entries.append(child)
            by_id[child["id"]] = child

    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    if not args.quiet:
        print_table(entries)
        n_warn = sum(1 for e in entries if e["warnings"])
        n_check = sum(1 for e in entries if e.get("checks"))
        print()
        print(f"자산 {len(entries)}건 (경고 {n_warn}건 · 확인 권고 {n_check}건) -> {out_path}")
        print("min_text_px / embedded_text_check 는 null 이다 — 모델이 그림을 눈으로 "
              "확인한 뒤 채워야 deck_qa 의 LEDGER_TEXT_CHECK 를 통과한다.")
        print("min_text_px 는 양수(px) · 0 또는 \"none\"(글자 없음) · null(미확인) 중 하나다. "
              f"기입 후 `--check <원장>` 으로 {MIN_TEXT_PX_FLOOR} px 하한을 다시 돌려라.")
    return 0


def trim_offset_for(entry: dict) -> tuple | None:
    """부모 자산의 autotrim 상자를 구한다(이미 알고 있으면 그대로 쓴다)."""
    if entry.get("trim_offset"):
        off = entry["trim_offset"]
        return (int(off[0]), int(off[1]), entry["px"]["w"], entry["px"]["h"])
    return autotrim_box(load_gray(Path(entry["path"])))


def run_check(ledger_path: Path, out_path: Path, quiet: bool) -> int:
    """--check: 기입된 min_text_px 를 다시 읽어 advice 를 갱신한다."""
    entries = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        print("[error] 원장이 JSON 배열이 아니다.", file=sys.stderr)
        return 2
    tally = {"ok": 0, "none": 0, "floor": 0, "unchecked": 0}
    for e in entries:
        e.setdefault("checks", [])
        tally[apply_min_text_advice(e)] += 1
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    if not quiet:
        flagged = [e for e in entries if any(a.startswith("min_text_px")
                                             for a in e.get("advice", []))]
        print(f"min_text_px 판정 — 통과 {tally['ok']}건 · 글자 없음(0/\"none\") "
              f"{tally['none']}건 · 미확인(null) {tally['unchecked']}건 · "
              f"하한 미달 {tally['floor']}건")
        if flagged:
            print(f"\n{MIN_TEXT_PX_FLOOR} px 미만 — {MIN_TEXT_PX_ADVICE}")
            rows = [[e["id"], f"{e['min_text_px']} px",
                     f"{e['px']['w']}x{e['px']['h']}"] for e in flagged]
            headers = ["id", "min_text_px", "px"]
            widths = [max(_wide(h), *(_wide(r[i]) for r in rows))
                      for i, h in enumerate(headers)]
            print(" | ".join(_pad(h, w) for h, w in zip(headers, widths)))
            print("-+-".join("-" * w for w in widths))
            for r in rows:
                print(" | ".join(_pad(c, w) for c, w in zip(r, widths)))
        print(f"\n-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
