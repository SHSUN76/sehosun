#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deck_qa.py — 빌드된 pptx 를 열어 자산·그리드 규율을 검사한다.

비교테스트(iteration-1)에서 사용자가 지적한 결함을 자동 게이트로 옮긴 것이다.
  - 소제목이 슬라이드마다 위아래로 흔들림      -> TITLE_Y_FIXED
  - 그림이 늘어나거나 눌려 원본 비율이 깨짐     -> IMAGE_AR
  - 세로 가운데 정렬로 슬라이드가 비어 보임     -> IMAGE_TOP_ALIGNED / FILL_RATIO
  - 저해상도 그림을 크게 배치해 흐릿함          -> PPI
  - 철회한 주장이 텍스트·노트·그림에 남음       -> FORBIDDEN / LEDGER_TEXT_CHECK
  - 제목이 한 줄을 넘겨 제목 높이가 흔들림      -> TITLE_WIDTH

사용법
    python deck_qa.py <deck.pptx> [--spec deck_spec.json] [--ledger asset_ledger.json]
                      [--build out.build.json] [--render render_dir]
                      [--forbidden "a,b,c"] --out qa_report.json
    python deck_qa.py --font-rules --out -      # 폰트 역할 규칙만 출력

폰트 하한은 텍스트의 역할에 따라 다르다. 특히 **캡션은 60자 이하 한 문단이어야
caption 으로 분류**되며, 넘으면 본문(body)으로 넘어가 14 pt 하한을 받는다.
자세한 표는 `--font-rules`.

자산 원장의 min_text_px 는 양수(px) / 0 또는 "none"(글자 없음) / null(미확인)
셋 중 하나다. null 만 미확인이고, 0 과 "none" 은 게이트를 통과한다.

판형이 10 x 5.625 in 인 덱과 13.333 x 7.5 in 인 덱을 함께 다루려고 모든 좌표를
13.333 in 폭 기준으로 정규화한 뒤 layout-grid.md 의 존 좌표와 비교한다.
종료코드: 0 = pass/warn, 1 = fail 존재.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

Image.MAX_IMAGE_PIXELS = None

# ---- layout-grid.md §1 정본 좌표 (13.333 x 7.5 in 기준) -------------------
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
TITLE_Y_MIN, TITLE_Y_MAX = 0.50, 1.40      # 제목 상자 탐색 창
TITLE_Y_MAX_EXT = 2.60                     # 확장 창(제목이 아래로 밀린 덱 탐지용)
CONTENT_TOP, CONTENT_BOTTOM = 1.50, 6.45
CONTENT_LEFT, CONTENT_RIGHT = 0.50, 12.83
BOTTOM_TOP, BOTTOM_BOTTOM = 6.65, 7.15

TITLE_TOL_IN = 0.02       # 제목 top 허용 오차
BOTTOM_TOL_IN = 0.02
AR_WARN = 0.005           # 배치 AR 편차 0.5% 이상 -> warn
AR_FAIL = 0.01            # 1% 초과 -> fail
TOP_ALIGN_TOL = 0.05      # content 존 시작과의 허용 오차
CLUSTER_TOL = 0.12        # 덱 자체 상단 정렬 일관성 허용 오차
FILL_MIN = 0.55
PPI_MIN = 110
# 폰트 하한은 텍스트의 역할에 따라 다르다. footer/band 는 검사 대상이 아니고,
# 캡션은 작아도 되지만 본문은 뒷줄에서 읽혀야 한다.
FOOTER_TOP_MIN = 7.20     # 상자 top 이 이보다 아래면 footer — 검사 제외
FOOTER_TOL_IN = 0.02      # 위치 허용 오차(TITLE_TOL_IN 과 같은 값). builder 는
                          # footer 를 7.18 in 에 놓는데, 결론문 상자는 6.65 in 이라
                          # 이 오차로도 둘이 섞이지 않는다
BAND_BOTTOM_MAX = 0.45    # 상자 bottom 이 이보다 위면 상단 띠 — 검사 제외
CAPTION_MAX_CHARS = 60    # 한 문단 · 이 길이 이하면 캡션으로 본다
FONT_CAPTION_MIN = 10.0   # 캡션 하한

# 자산 원장의 min_text_px 하한 — 0.12 in x 110 ppi = 13.2 px
TEXT_TINY_MIN_IN = 0.12
MIN_TEXT_PX_FLOOR = 13.2

# TITLE_WIDTH — 제목 한 줄이 넘치는지 보는 문자 폭 근사(em 배수)
TITLE_NOMINAL_PT = 26.0   # 26 pt bold 기준
TITLE_MAX_WIDTH_IN = 12.0
EM_LATIN = 0.55
EM_HANGUL = 1.0
EM_SPACE = 0.3
FONT_BODY_WARN = 14.0     # 본문 권장 하한
FONT_BODY_FAIL = 12.0     # 본문 절대 하한
FONT_LABEL_WARN = 12.0    # 짧은 라벨 권장 하한
FONT_LABEL_FAIL = 9.0     # 짧은 라벨 절대 하한
NOTES_MIN_WORDS = 40
NOTES_MIN_HANGUL = 60
BG_AREA_FRAC = 0.90       # 슬라이드 면적의 90% 이상이면 배경으로 보고 제외

HANGUL_FONTS = {"malgun gothic", "noto sans kr", "맑은 고딕", "나눔고딕", "nanumgothic",
                "noto sans cjk kr", "malgungothic"}

TEXT_TYPES_CONTENT = {"content", "appendix"}
NOTES_TYPES = {"content", "appendix", "conclusion"}
FILL_EXEMPT_TYPES = {"title", "toc", "section", "thanks", "text-only", "text_only"}

HYPHENS = "-‐‑‒–—―−－ー"


FONT_RULES_TEXT = f"""FONT_MIN 역할 분류와 하한
  footer   상자 top >= {FOOTER_TOP_MIN} in            -> 검사 제외
  band     상자 bottom <= {BAND_BOTTOM_MAX} in           -> 검사 제외
  caption  한 문단 · {CAPTION_MAX_CHARS}자 이하 · {FONT_CAPTION_MIN:.0f} pt 이상 -> 통과
           ** 캡션은 {CAPTION_MAX_CHARS}자 이하여야 caption 으로 분류된다.
              넘으면 body 로 넘어가 {FONT_BODY_WARN:.0f} pt 하한을 받는다 **
  body     텍스트 프레임 {CAPTION_MAX_CHARS}자 초과 또는 문단 2개 이상
           -> {FONT_BODY_WARN:.0f} pt 미만 warn, {FONT_BODY_FAIL:.0f} pt 미만 fail
  label    그 밖의 짧은 글(diagram 라벨 등)
           -> {FONT_LABEL_WARN:.0f} pt 미만 warn, {FONT_LABEL_FAIL:.0f} pt 미만 fail
표는 셀 하나가 판정 단위다."""


# --------------------------------------------------------------- utilities --
def norm_text(s: str) -> str:
    """대소문자·전각/반각·하이픈 변형·공백을 흡수한 비교용 문자열."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = "".join("-" if ch in HYPHENS else ch for ch in s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def hangul_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    han = sum(1 for c in letters if "가" <= c <= "힣")
    return han / len(letters)


def word_count(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w])


def hangul_chars(s: str) -> int:
    return sum(1 for c in s if "가" <= c <= "힣")


def min_text_state(value) -> str:
    """원장 min_text_px 의 상태.

    null 만 '미확인'이다. 0 과 "none" 은 '그림 안에 글자가 없음'을 확인한
    값이므로 작은 글씨 게이트를 통과시킨다."""
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


def text_width_in(s: str, pt: float) -> float:
    """문자 폭 근사 — 라틴 0.55 em, 한글(및 전각) 1.0 em, 공백 0.3 em."""
    em = pt / 72.0
    total = 0.0
    for ch in s:
        if ch.isspace():
            total += EM_SPACE
        elif ord(ch) > 0x2E7F:      # 한글·한자·전각 기호
            total += EM_HANGUL
        else:
            total += EM_LATIN
    return total * em


class Res:
    """검사 하나의 결과."""

    def __init__(self, name: str):
        self.name = name
        self.status = "pass"
        self.evidence: list = []
        self.summary = ""

    def mark(self, status: str) -> None:
        order = {"pass": 0, "warn": 1, "fail": 2, "skip": -1}
        if order[status] > order.get(self.status, 0):
            self.status = status

    def add(self, status: str, slide: int | None, msg: str, **kw) -> None:
        self.mark(status)
        item = {"status": status, "slide": slide, "message": msg}
        item.update(kw)
        self.evidence.append(item)

    def to_dict(self) -> dict:
        return {"check": self.name, "status": self.status,
                "summary": self.summary, "evidence": self.evidence}


# ------------------------------------------------------------ deck reader --
class Deck:
    """pptx 를 정규화 좌표(13.333 x 7.5 in)로 읽어 둔 표현."""

    def __init__(self, path: Path):
        self.path = path
        self.prs = Presentation(str(path))
        self.w_in = Emu(self.prs.slide_width).inches
        self.h_in = Emu(self.prs.slide_height).inches
        self.scale = SLIDE_W_IN / self.w_in
        self.aspect = self.w_in / self.h_in
        self.slides = [self._read(i, s) for i, s in enumerate(self.prs.slides, 1)]

    def _i(self, emu) -> float | None:
        return None if emu is None else Emu(emu).inches * self.scale

    def _read(self, idx: int, s) -> dict:
        shapes: list[dict] = []
        self._walk(s.shapes, shapes)
        notes = ""
        try:
            if s.has_notes_slide:
                notes = s.notes_slide.notes_text_frame.text or ""
        except (AttributeError, KeyError):
            notes = ""
        texts = [sh["text"] for sh in shapes if sh["text"]]
        return {"index": idx, "shapes": shapes, "notes": notes,
                "layout": s.slide_layout.name, "texts": texts}

    def _walk(self, container, out: list) -> None:
        for sh in container:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                self._walk(sh.shapes, out)
                continue
            rec = {
                "name": sh.name,
                "kind": "picture" if sh.shape_type == MSO_SHAPE_TYPE.PICTURE
                        else ("table" if getattr(sh, "has_table", False) else "shape"),
                "left": self._i(sh.left), "top": self._i(sh.top),
                "width": self._i(sh.width), "height": self._i(sh.height),
                "text": "", "runs": [], "image": None,
            }
            if getattr(sh, "has_text_frame", False):
                rec["text"] = sh.text_frame.text or ""
                # 폰트 역할 판정의 단위는 텍스트 프레임 전체다
                unit_chars = len((sh.text_frame.text or "").strip())
                unit_paras = sum(1 for p in sh.text_frame.paragraphs if p.text.strip())
                for para in sh.text_frame.paragraphs:
                    ptext = "".join(r.text or "" for r in para.runs)
                    for r in para.runs:
                        rec["runs"].append({
                            "text": r.text or "",
                            "size": r.font.size.pt if r.font.size else None,
                            "font": r.font.name,
                            "para_text": ptext,
                            "unit_chars": unit_chars,
                            "unit_paras": unit_paras,
                        })
            if getattr(sh, "has_table", False):
                cells = []
                for row in sh.table.rows:
                    for c in row.cells:
                        cells.append(c.text or "")
                        # 표는 셀 하나가 판정 단위다
                        cell_chars = len((c.text or "").strip())
                        cell_paras = sum(1 for p in c.text_frame.paragraphs if p.text.strip())
                        for para in c.text_frame.paragraphs:
                            for r in para.runs:
                                rec["runs"].append({
                                    "text": r.text or "",
                                    "size": r.font.size.pt if r.font.size else None,
                                    "font": r.font.name,
                                    "para_text": c.text or "",
                                    "unit_chars": cell_chars,
                                    "unit_paras": cell_paras,
                                })
                rec["text"] = (rec["text"] + "\n" + "\n".join(cells)).strip()
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = sh.image.blob
                    with Image.open(io.BytesIO(blob)) as im:
                        rec["image"] = {"px_w": im.size[0], "px_h": im.size[1]}
                    # pptx 내부 crop(비율) 반영 — 실제로 보이는 원본 영역
                    crop = (sh.crop_left or 0, sh.crop_right or 0,
                            sh.crop_top or 0, sh.crop_bottom or 0)
                    rec["crop"] = [round(float(c), 5) for c in crop]
                    vis_w = rec["image"]["px_w"] * max(1e-6, 1 - crop[0] - crop[1])
                    vis_h = rec["image"]["px_h"] * max(1e-6, 1 - crop[2] - crop[3])
                    rec["image"]["vis_w"] = vis_w
                    rec["image"]["vis_h"] = vis_h
                except Exception as exc:  # 손상된 blob 은 건너뛰되 기록
                    rec["image_error"] = str(exc)[:120]
            out.append(rec)


def slide_types(deck: Deck, spec: dict | None) -> list[str]:
    """슬라이드 종류를 스펙에서 받거나, 없으면 내용으로 추정한다."""
    if spec and isinstance(spec.get("slides"), list) and \
            len(spec["slides"]) == len(deck.slides):
        return [str(s.get("type", "content")) for s in spec["slides"]]

    types = []
    n = len(deck.slides)
    for sl in deck.slides:
        joined = norm_text(" ".join(sl["texts"]))
        has_pic = any(sh["kind"] == "picture" and (sh["width"] or 0) < SLIDE_W_IN * 0.98
                      for sh in sl["shapes"])
        n_text = sum(1 for sh in sl["shapes"] if sh["text"].strip())
        if sl["index"] == 1:
            t = "title"
        elif "목차" in joined or "contents" in joined or "outline" in joined:
            t = "toc"
        elif "감사합니다" in joined or "q&a" in joined or "thank you" in joined:
            t = "thanks"
        elif "appendix" in joined and sl["index"] > n * 0.7:
            t = "appendix"
        elif not has_pic and n_text <= 3:
            t = "section"
        elif not has_pic:
            t = "text-only"
        else:
            t = "content"
        types.append(t)
    return types


def title_box(sl: dict, extended: bool = False) -> dict | None:
    """제목 상자 = y 가 0.5–1.4 in 범위인 텍스트 상자 중 폰트가 가장 큰 것."""
    hi = TITLE_Y_MAX_EXT if extended else TITLE_Y_MAX
    best, best_size = None, -1.0
    for sh in sl["shapes"]:
        if not sh["text"].strip() or sh["top"] is None:
            continue
        if not (TITLE_Y_MIN <= sh["top"] <= hi):
            continue
        sizes = [r["size"] for r in sh["runs"] if r["size"]]
        size = max(sizes) if sizes else 0.0
        # 같은 크기면 위에 있는 것을 제목으로 본다
        if size > best_size or (size == best_size and best and sh["top"] < best["top"]):
            best, best_size = sh, size
    if best is not None:
        best = dict(best)
        best["font_size"] = best_size
    return best


# ---------------------------------------------------------------- checks ---
def check_slide_count(deck: Deck, spec: dict | None) -> Res:
    r = Res("SLIDE_COUNT")
    n = len(deck.slides)
    ratio = deck.aspect
    if abs(ratio - 16 / 9) > 0.01:
        r.add("fail", None, f"판형이 16:9 가 아니다 ({deck.w_in:.3f} x {deck.h_in:.3f} in, "
                            f"AR {ratio:.3f})")
    else:
        r.add("pass", None, f"16:9 확인 ({deck.w_in:.3f} x {deck.h_in:.3f} in)")
    if spec and isinstance(spec.get("slides"), list):
        want = len(spec["slides"])
        if want != n:
            r.add("fail", None, f"스펙 {want}장 vs 덱 {n}장")
        else:
            r.add("pass", None, f"슬라이드 수 일치({n})")
    else:
        r.add("pass", None, f"스펙 없음 — 슬라이드 수만 기록({n})")
    r.summary = f"{n} slides, AR {ratio:.3f}"
    return r


def check_title_y(deck: Deck, types: list[str]) -> Res:
    r = Res("TITLE_Y_FIXED")
    tops, missing = [], []
    for sl, t in zip(deck.slides, types):
        if t not in TEXT_TYPES_CONTENT:
            continue
        tb = title_box(sl)
        if tb is None:
            tb_ext = title_box(sl, extended=True)
            if tb_ext is None:
                missing.append((sl["index"], None))
            else:
                missing.append((sl["index"], round(tb_ext["top"], 3)))
            continue
        tops.append((sl["index"], round(tb["top"], 4), tb["text"].strip()[:36]))

    if not tops and not missing:
        r.status = "skip"
        r.summary = "content/appendix 슬라이드 없음"
        return r

    for idx, top in missing:
        if top is None:
            r.add("fail", idx, "제목 상자를 0.5–1.4 in 창에서도, 확장 창에서도 못 찾았다")
        else:
            r.add("fail", idx,
                  f"제목이 고정 창(0.50–1.40 in) 밖 top={top} in — 세로 가운데 정렬 의심",
                  top_in=top)

    if tops:
        vals = [t for _, t, _ in tops]
        med = float(np.median(vals))
        spread = max(vals) - min(vals)
        for idx, top, txt in tops:
            if abs(top - med) > TITLE_TOL_IN:
                r.add("fail", idx,
                      f"제목 top {top:.3f} in (기준 {med:.3f} in, 편차 {top-med:+.3f} in) — {txt}",
                      top_in=top, deviation_in=round(top - med, 4))
        if r.status == "pass":
            r.add("pass", None, f"제목 top 전부 {med:.3f} in ±{TITLE_TOL_IN} in")
        r.summary = (f"n={len(tops)+len(missing)}, median {med:.3f} in, "
                     f"spread {spread:.3f} in, 창 밖 {len(missing)}장")
    else:
        r.summary = f"제목 상자를 고정 창에서 하나도 못 찾음(창 밖 {len(missing)}장)"
    return r


def check_title_width(deck: Deck, types: list[str]) -> Res:
    """제목 한 줄이 title 존 폭을 넘는지 독립 검증한다.

    빌더도 같은 규칙으로 폰트를 줄이지만, QA 는 빌더를 믿지 않고 제목 텍스트에서
    다시 계산한다. 기준은 26 pt bold 에서 12.0 in — 넘으면 두 줄로 흐르거나
    글자가 줄어 제목 높이가 흔들린다."""
    r = Res("TITLE_WIDTH")
    widths = []
    for sl, t in zip(deck.slides, types):
        if t not in TEXT_TYPES_CONTENT:
            continue
        tb = title_box(sl) or title_box(sl, extended=True)
        if tb is None:
            continue
        text = " ".join(tb["text"].split())
        w = text_width_in(text, TITLE_NOMINAL_PT)
        widths.append((sl["index"], w, text, tb.get("font_size")))
        if w > TITLE_MAX_WIDTH_IN:
            r.add("warn", sl["index"],
                  f"제목 폭 {w:.2f} in > {TITLE_MAX_WIDTH_IN} in "
                  f"({TITLE_NOMINAL_PT:.0f} pt bold 기준, {len(text)}자, "
                  f"실제 {tb.get('font_size') or '?'} pt) — '{text[:40]}'",
                  width_in=round(w, 3), chars=len(text))
    if not widths:
        r.status = "skip"
        r.summary = "제목 상자를 찾지 못했다"
        return r
    over = sum(1 for _, w, _, _ in widths if w > TITLE_MAX_WIDTH_IN)
    if r.status == "pass":
        r.add("pass", None,
              f"제목 {len(widths)}개 전부 {TITLE_MAX_WIDTH_IN} in 이하 "
              f"({TITLE_NOMINAL_PT:.0f} pt bold 기준)")
    r.summary = (f"n={len(widths)}, 최대 {max(w for _, w, _, _ in widths):.2f} in, "
                 f"초과 {over}장 (기준 {TITLE_MAX_WIDTH_IN} in @ "
                 f"{TITLE_NOMINAL_PT:.0f} pt)")
    return r


def check_bottomline(deck: Deck, types: list[str]) -> Res:
    r = Res("BOTTOMLINE_FIXED")
    tops = []
    for sl, t in zip(deck.slides, types):
        if t not in TEXT_TYPES_CONTENT:
            continue
        cands = [sh for sh in sl["shapes"]
                 if sh["text"].strip() and sh["top"] is not None
                 and sh["top"] >= CONTENT_BOTTOM - 0.10
                 and (sh["width"] or 0) >= SLIDE_W_IN * 0.30]
        if not cands:
            continue
        cands.sort(key=lambda s: (-(s["width"] or 0), s["top"]))
        tops.append((sl["index"], round(cands[0]["top"], 4),
                     cands[0]["text"].strip()[:36]))
    if not tops:
        r.status = "skip"
        r.summary = "결론문(bottom line) 상자를 찾지 못했다 — 덱에 없을 수 있음"
        return r
    vals = [t for _, t, _ in tops]
    med = float(np.median(vals))
    for idx, top, txt in tops:
        if abs(top - med) > BOTTOM_TOL_IN:
            r.add("fail", idx,
                  f"결론문 top {top:.3f} in (기준 {med:.3f} in, 편차 {top-med:+.3f} in) — {txt}",
                  top_in=top, deviation_in=round(top - med, 4))
    n_cov = len(tops)
    n_expect = sum(1 for t in types if t in TEXT_TYPES_CONTENT)
    if n_cov < n_expect:
        r.add("warn", None,
              f"content/appendix {n_expect}장 중 {n_cov}장에서만 결론문 상자를 찾았다")
    if r.status == "pass":
        r.add("pass", None, f"결론문 top 전부 {med:.3f} in ±{BOTTOM_TOL_IN} in")
    r.summary = f"n={n_cov}/{n_expect}, median {med:.3f} in"
    return r


def _pictures(sl: dict) -> list[dict]:
    return [sh for sh in sl["shapes"]
            if sh["kind"] == "picture" and sh["image"]
            and (sh["width"] or 0) > 0 and (sh["height"] or 0) > 0]


def check_image_ar(deck: Deck) -> Res:
    r = Res("IMAGE_AR")
    n = 0
    worst = 0.0
    for sl in deck.slides:
        for sh in _pictures(sl):
            n += 1
            placed = sh["width"] / sh["height"]
            src = sh["image"]["vis_w"] / sh["image"]["vis_h"]
            dev = abs(placed - src) / src
            worst = max(worst, dev)
            if dev > AR_FAIL:
                r.add("fail", sl["index"],
                      f"배치 AR {placed:.3f} vs 원본 AR {src:.3f} — 편차 {dev*100:.2f}% "
                      f"(원본 {sh['image']['px_w']}x{sh['image']['px_h']} px, "
                      f"배치 {sh['width']:.2f}x{sh['height']:.2f} in)",
                      deviation_pct=round(dev * 100, 3))
            elif dev >= AR_WARN:
                r.add("warn", sl["index"],
                      f"배치 AR {placed:.3f} vs 원본 AR {src:.3f} — 편차 {dev*100:.2f}%",
                      deviation_pct=round(dev * 100, 3))
    if n == 0:
        r.status = "skip"
        r.summary = "picture shape 없음"
        return r
    if r.status == "pass":
        r.add("pass", None, f"picture {n}개 전부 편차 {AR_WARN*100:.1f}% 미만")
    r.summary = f"n={n}, 최대 편차 {worst*100:.2f}% (warn≥{AR_WARN*100:.1f}%, fail>{AR_FAIL*100:.0f}%)"
    return r


def check_image_top(deck: Deck, types: list[str]) -> Res:
    """세로 가운데 정렬 검출. content 존 시작에 붙었는지, 아니면 최소한
    덱 전체에서 같은 y 에 붙었는지를 본다."""
    r = Res("IMAGE_TOP_ALIGNED")
    firsts = []
    for sl, t in zip(deck.slides, types):
        if t in ("title", "thanks"):
            continue
        pics = _pictures(sl)
        pics = [p for p in pics
                if (p["width"] or 0) < SLIDE_W_IN * 0.98 or (p["height"] or 0) < SLIDE_H_IN * 0.98]
        if not pics:
            continue
        top = min(p["top"] for p in pics if p["top"] is not None)
        firsts.append((sl["index"], round(top, 4)))
    if not firsts:
        r.status = "skip"
        r.summary = "배치된 picture 없음"
        return r

    vals = [t for _, t in firsts]
    med = float(np.median(vals))
    on_grid = abs(med - CONTENT_TOP) <= TOP_ALIGN_TOL
    aligned = [i for i, t in firsts if abs(t - med) <= CLUSTER_TOL]
    rate = len(aligned) / len(firsts)

    for idx, top in firsts:
        if abs(top - med) > CLUSTER_TOL:
            r.add("warn" if rate >= 0.6 else "fail", idx,
                  f"그림 top {top:.2f} in — 덱 기준선 {med:.2f} in 에서 {top-med:+.2f} in 어긋남",
                  top_in=top)

    if rate < 0.60:
        r.mark("fail")
        r.add("fail", None,
              f"그림 상단이 일정하지 않다 — 기준선 {med:.2f} in 에 맞는 슬라이드가 "
              f"{len(aligned)}/{len(firsts)} ({rate*100:.0f}%). 세로 가운데 정렬로 보인다")
    elif not on_grid:
        r.mark("warn")
        r.add("warn", None,
              f"그림 상단이 서로 일관({rate*100:.0f}%)되지만 content 존 시작 "
              f"{CONTENT_TOP:.2f} in 이 아니라 {med:.2f} in 이다")
    else:
        r.add("pass", None,
              f"그림 상단 {med:.2f} in = content 존 시작 ±{TOP_ALIGN_TOL} in, "
              f"일관율 {rate*100:.0f}%")
    r.summary = (f"n={len(firsts)}, median {med:.2f} in, 일관율 {rate*100:.0f}%, "
                 f"grid={'yes' if on_grid else 'no'}")
    return r


def diagram_kinds(build: dict | None) -> dict[int, str]:
    """build.json 의 slides[].diagram 을 슬라이드 번호로 색인한다.

    빌더가 이 필드를 아직 넣지 않으면 빈 표가 되고, FILL_RATIO 메시지는
    diagram 병기 없이 그대로 나간다."""
    out: dict[int, str] = {}
    if not build:
        return out
    for i, s in enumerate(build.get("slides") or [], 1):
        if not isinstance(s, dict):
            continue
        kind = s.get("diagram")
        if kind:
            out[int(s.get("index", i))] = str(kind)
    return out


def check_fill_ratio(deck: Deck, types: list[str],
                     build: dict | None = None) -> Res:
    r = Res("FILL_RATIO")
    diagrams = diagram_kinds(build)
    step = 0.02  # in
    zone_w, zone_h = CONTENT_RIGHT - CONTENT_LEFT, CONTENT_BOTTOM - CONTENT_TOP
    nx, ny = int(round(zone_w / step)), int(round(zone_h / step))
    slide_area = SLIDE_W_IN * SLIDE_H_IN
    ratios = []
    for sl, t in zip(deck.slides, types):
        if t in FILL_EXEMPT_TYPES:
            continue
        mask = np.zeros((ny, nx), dtype=bool)
        for sh in sl["shapes"]:
            if sh["left"] is None or sh["width"] is None:
                continue
            w, h = sh["width"], sh["height"]
            if w <= 0 or h <= 0:
                continue
            if w * h >= slide_area * BG_AREA_FRAC:
                continue  # 배경 판
            if sh["kind"] == "shape" and not sh["text"].strip() and w * h > zone_w * zone_h * 0.5:
                continue  # 큰 무텍스트 색면(배경 변형)
            x0 = max(CONTENT_LEFT, sh["left"]); x1 = min(CONTENT_RIGHT, sh["left"] + w)
            y0 = max(CONTENT_TOP, sh["top"]); y1 = min(CONTENT_BOTTOM, sh["top"] + h)
            if x1 <= x0 or y1 <= y0:
                continue
            i0 = int((x0 - CONTENT_LEFT) / step); i1 = int(np.ceil((x1 - CONTENT_LEFT) / step))
            j0 = int((y0 - CONTENT_TOP) / step); j1 = int(np.ceil((y1 - CONTENT_TOP) / step))
            mask[max(0, j0):min(ny, j1), max(0, i0):min(nx, i1)] = True
        ratio = float(mask.mean())
        ratios.append((sl["index"], round(ratio, 4)))
        if ratio < FILL_MIN:
            kind = diagrams.get(sl["index"])
            note = f" (diagram: {kind})" if kind else ""
            r.add("warn" if ratio >= FILL_MIN * 0.8 else "fail", sl["index"],
                  f"content 존 채움률 {ratio*100:.0f}% < {FILL_MIN*100:.0f}%{note}",
                  fill_ratio=round(ratio, 4), diagram=kind)
    if not ratios:
        r.status = "skip"
        r.summary = "대상 슬라이드 없음"
        return r
    vals = [v for _, v in ratios]
    if r.status == "pass":
        r.add("pass", None, f"{len(ratios)}장 전부 {FILL_MIN*100:.0f}% 이상")
    r.summary = (f"n={len(ratios)}, 평균 {np.mean(vals)*100:.0f}%, "
                 f"최저 {min(vals)*100:.0f}%, 미달 "
                 f"{sum(1 for v in vals if v < FILL_MIN)}장")
    return r


def check_ppi(deck: Deck) -> Res:
    r = Res("PPI")
    worst, n = 1e9, 0
    for sl in deck.slides:
        for sh in _pictures(sl):
            n += 1
            ppi = sh["image"]["vis_w"] / sh["width"]
            worst = min(worst, ppi)
            if ppi < PPI_MIN:
                r.add("warn" if ppi >= PPI_MIN * 0.75 else "fail", sl["index"],
                      f"{ppi:.0f} ppi < {PPI_MIN} — 원본 {sh['image']['px_w']} px 를 "
                      f"{sh['width']:.2f} in 폭에 배치",
                      ppi=round(ppi, 1))
    if n == 0:
        r.status = "skip"
        r.summary = "picture shape 없음"
        return r
    if r.status == "pass":
        r.add("pass", None, f"picture {n}개 전부 {PPI_MIN} ppi 이상 (최저 {worst:.0f})")
    r.summary = f"n={n}, 최저 {worst:.0f} ppi"
    return r


def check_forbidden(deck: Deck, forbidden: list[str]) -> Res:
    r = Res("FORBIDDEN")
    if not forbidden:
        r.status = "skip"
        r.summary = "forbidden 목록 없음(--spec 또는 --forbidden 으로 지정)"
        return r
    pats = [(f, norm_text(f)) for f in forbidden if f and f.strip()]
    for sl in deck.slides:
        hay_text = norm_text(" ".join(sl["texts"]))
        hay_notes = norm_text(sl["notes"])
        for raw, pat in pats:
            if pat and pat in hay_text:
                i = hay_text.find(pat)
                r.add("fail", sl["index"],
                      f"금지 문자열 '{raw}' 가 슬라이드 텍스트에 있다: "
                      f"…{hay_text[max(0,i-30):i+len(pat)+30]}…", term=raw, where="text")
            if pat and pat in hay_notes:
                i = hay_notes.find(pat)
                r.add("fail", sl["index"],
                      f"금지 문자열 '{raw}' 가 발표자 노트에 있다: "
                      f"…{hay_notes[max(0,i-30):i+len(pat)+30]}…", term=raw, where="notes")
    if r.status == "pass":
        r.add("pass", None, f"금지 문자열 {len(pats)}건 모두 미검출")
    r.summary = f"terms={len(pats)}, hits={len(r.evidence) if r.status=='fail' else 0}"
    return r


def text_role(sh: dict, run: dict) -> str:
    """텍스트의 역할을 정해 폰트 하한을 다르게 건다.

      footer  상자 top >= 7.20 in            — 검사 제외
      band    상자 bottom <= 0.45 in         — 검사 제외
      body    텍스트 프레임 60자 초과 또는 문단 2개 이상
      caption 한 문단 · 60자 이하
      label   그 밖의 짧은 글(diagram 라벨 등)

    caption 과 label 은 길이로는 같다. 10 pt 이상이면 캡션으로 보고 통과시키고,
    그 아래는 라벨 규칙으로 넘겨 더 엄하게 본다.
    """
    top = sh.get("top")
    if top is not None:
        if top >= FOOTER_TOP_MIN - FOOTER_TOL_IN:
            return "footer"
        bottom = top + (sh.get("height") or 0.0)
        if bottom <= BAND_BOTTOM_MAX:
            return "band"
    chars = run.get("unit_chars", len(run.get("para_text", "")))
    paras = run.get("unit_paras", 1)
    if chars > CAPTION_MAX_CHARS or paras >= 2:
        return "body"
    size = run.get("size")
    if size is not None and size >= FONT_CAPTION_MIN:
        return "caption"
    return "label"


def check_font_min(deck: Deck, types: list[str]) -> Res:
    r = Res("FONT_MIN")
    n_runs, n_checked, small = 0, 0, []
    roles: dict[str, int] = {}
    for sl, t in zip(deck.slides, types):
        for sh in sl["shapes"]:
            for run in sh["runs"]:
                if not run["text"].strip():
                    continue
                n_runs += 1
                role = text_role(sh, run)
                roles[role] = roles.get(role, 0) + 1
                if role in ("footer", "band"):
                    continue          # ① footer·band 는 검사 대상이 아니다
                size = run["size"]
                if size is None:
                    continue          # 테마 상속 — 크기를 알 수 없다
                n_checked += 1
                snippet = (run["para_text"] or run["text"]).strip()[:32]
                if role == "body":    # ③ 본문
                    if size < FONT_BODY_FAIL:
                        r.add("fail", sl["index"],
                              f"본문 {size:.1f} pt < {FONT_BODY_FAIL} pt — '{snippet}'",
                              size_pt=size, role=role)
                        small.append(size)
                    elif size < FONT_BODY_WARN:
                        r.add("warn", sl["index"],
                              f"본문 {size:.1f} pt < {FONT_BODY_WARN} pt — '{snippet}'",
                              size_pt=size, role=role)
                        small.append(size)
                elif role == "caption":   # ② 캡션 — 10 pt 이상이면 통과
                    continue
                else:                 # ④ 짧은 라벨
                    if size < FONT_LABEL_FAIL:
                        r.add("fail", sl["index"],
                              f"라벨 {size:.1f} pt < {FONT_LABEL_FAIL} pt — '{snippet}'",
                              size_pt=size, role=role)
                        small.append(size)
                    elif size < FONT_LABEL_WARN:
                        r.add("warn", sl["index"],
                              f"라벨 {size:.1f} pt < {FONT_LABEL_WARN} pt — '{snippet}'",
                              size_pt=size, role=role)
                        small.append(size)
    if n_runs == 0:
        r.status = "skip"
        r.summary = "run 없음"
        return r
    skipped = roles.get("footer", 0) + roles.get("band", 0)
    if r.status == "pass":
        r.add("pass", None,
              f"검사 대상 run {n_checked}개 전부 하한 통과 "
              f"(footer·band {skipped}개 제외, 캡션은 {CAPTION_MAX_CHARS}자 이하 "
              f"한 문단이어야 caption 으로 분류)")
    r.summary = (f"runs={n_runs}(검사 {n_checked}, footer·band 제외 {skipped}), "
                 f"하한 미달 {len(small)}건 · 캡션 상한 {CAPTION_MAX_CHARS}자")
    return r


def check_notes(deck: Deck, types: list[str]) -> Res:
    r = Res("NOTES")
    n_target, ok = 0, 0
    for sl, t in zip(deck.slides, types):
        if t not in NOTES_TYPES:
            continue
        n_target += 1
        notes = sl["notes"].strip()
        if not notes:
            r.add("fail", sl["index"], "발표자 노트가 비어 있다")
            continue
        if hangul_ratio(notes) >= 0.3:
            n_h = hangul_chars(notes)
            if n_h < NOTES_MIN_HANGUL:
                r.add("fail", sl["index"],
                      f"노트 한글 {n_h}자 < {NOTES_MIN_HANGUL}자", chars=n_h)
            else:
                ok += 1
        else:
            n_w = word_count(notes)
            if n_w < NOTES_MIN_WORDS:
                r.add("fail", sl["index"],
                      f"노트 {n_w}단어 < {NOTES_MIN_WORDS}단어", words=n_w)
            else:
                ok += 1
    if n_target == 0:
        r.status = "skip"
        r.summary = "대상 슬라이드 없음"
        return r
    if r.status == "pass":
        r.add("pass", None, f"{ok}/{n_target} 슬라이드 노트 충족")
    r.summary = f"{ok}/{n_target} 충족"
    return r


def check_hangul_font(deck: Deck, lang: str | None) -> Res:
    r = Res("HANGUL_FONT")
    if lang and lang.lower() not in ("ko", "kor", "korean"):
        r.status = "skip"
        r.summary = f"lang={lang} — 한글 폰트 검사 생략"
        return r
    n, bad = 0, {}
    for sl in deck.slides:
        for sh in sl["shapes"]:
            for run in sh["runs"]:
                if hangul_chars(run["text"]) == 0:
                    continue
                n += 1
                face = (run["font"] or "").strip()
                if not face:
                    continue  # 테마 상속 — 판단 불가
                if face.lower() not in HANGUL_FONTS:
                    bad.setdefault(face, []).append(sl["index"])
    if n == 0:
        r.status = "skip"
        r.summary = "한글 run 없음"
        return r
    for face, slides in bad.items():
        r.add("fail", slides[0],
              f"한글 run 의 fontFace '{face}' — Malgun Gothic/Noto Sans KR 아님 "
              f"(슬라이드 {sorted(set(slides))[:8]}, 총 {len(slides)} run)",
              font=face, count=len(slides))
    if r.status == "pass":
        r.add("pass", None, f"한글 run {n}개 — 지정 폰트 또는 테마 상속")
    r.summary = f"hangul runs={n}, 위반 폰트 {len(bad)}종"
    return r


def check_ledger_text(deck: Deck, ledger: list | None, spec: dict | None) -> Res:
    r = Res("LEDGER_TEXT_CHECK")
    if ledger is None:
        r.status = "skip"
        r.summary = "--ledger 미지정"
        return r
    by_id = {e.get("id"): e for e in ledger}
    by_file = {Path(str(e.get("path", ""))).name: e for e in ledger}

    used: dict[str, dict] = {}
    if spec and isinstance(spec.get("slides"), list):
        for i, s in enumerate(spec["slides"], 1):
            for a in s.get("assets", []) or []:
                key = a.get("ledger_id") or Path(str(a.get("path", ""))).name
                e = by_id.get(key) or by_file.get(key)
                if e:
                    used.setdefault(e["id"], {"entry": e, "slides": []})["slides"].append(i)
                else:
                    r.add("warn", i, f"스펙의 자산 '{key}' 가 원장에 없다")
    else:
        # 스펙이 없으면 원장 전체를 대상으로 본다(부모 항목만).
        for e in ledger:
            if e.get("parent_id"):
                continue
            used.setdefault(e["id"], {"entry": e, "slides": []})

    for aid, rec in used.items():
        e = rec["entry"]
        val = e.get("embedded_text_check")
        sl = rec["slides"][0] if rec["slides"] else None
        if val is None:
            r.add("fail", sl, f"자산 {aid}: embedded_text_check 가 null — "
                              f"모델이 그림 안 문구를 눈으로 확인하지 않았다")
        elif str(val).strip().lower() != "ok":
            r.add("fail", sl, f"자산 {aid}: embedded_text_check = '{val}'")
        state = min_text_state(e.get("min_text_px"))
        if state == "unchecked":
            r.add("warn", sl, f"자산 {aid}: min_text_px 가 null(미확인) — 작은 글씨 "
                              f"게이트를 못 돈다. 글자가 없으면 0 또는 \"none\" 으로 적어라")
        elif state == "floor":
            r.add("warn", sl,
                  f"자산 {aid}: min_text_px {e['min_text_px']} px < "
                  f"{MIN_TEXT_PX_FLOOR} px — PPI≥{PPI_MIN}과 TEXT_TINY≥"
                  f"{TEXT_TINY_MIN_IN} in 을 동시에 만족할 수 없다. 재플롯 또는 "
                  f"원본 고해상 렌더 필요", min_text_px=e.get("min_text_px"))
        # state 가 "none"(0 또는 "none") 또는 "ok" 면 통과 — 확인을 마친 값이다
    if not used:
        r.status = "skip"
        r.summary = "대상 자산 없음"
        return r
    if r.status == "pass":
        r.add("pass", None, f"자산 {len(used)}건 전부 embedded_text_check = ok")
    r.summary = f"assets={len(used)}"
    return r


def check_build_warnings(build: dict | None) -> Res:
    r = Res("BUILD_WARNINGS")
    if build is None:
        r.status = "skip"
        r.summary = "--build 미지정"
        return r
    warns = build.get("warnings") or []
    if isinstance(warns, dict):
        warns = [f"{k}: {v}" for k, v in warns.items()]
    codes: dict[str, int] = {}
    for w in warns:
        if isinstance(w, dict):
            code = str(w.get("code") or "WARN")
            detail = w.get("message") or w.get("detail") or ""
            codes[code] = codes.get(code, 0) + 1
            r.add("warn", w.get("slide"), f"{code}: {detail}".strip(), code=code)
        else:
            r.add("warn", None, str(w))
    if r.status == "pass":
        r.add("pass", None, "builder 경고 없음")
    r.summary = (f"builder warnings={len(warns)}"
                 + (" (" + ", ".join(f"{k} x{v}" for k, v in sorted(codes.items())) + ")"
                    if codes else ""))
    return r


def check_render(deck: Deck, render_dir: Path | None) -> Res:
    r = Res("RENDER")
    if render_dir is None:
        r.status = "skip"
        r.summary = "--render 미지정"
        return r
    pngs = sorted(render_dir.glob("slide_*.png"))
    if not pngs:
        r.add("fail", None, f"{render_dir} 에 slide_*.png 가 없다")
        r.summary = "0 png"
        return r
    if len(pngs) != len(deck.slides):
        r.add("fail", None, f"렌더 {len(pngs)}장 vs 덱 {len(deck.slides)}장")
    blanks = []
    for p in pngs:
        with Image.open(p) as im:
            arr = np.asarray(im.convert("L").resize((160, 90)))
        if (arr < 245).mean() < 0.01:
            blanks.append(p.name)
    if blanks:
        r.add("fail", None, f"거의 빈 슬라이드 렌더 {len(blanks)}장: {blanks[:6]}")
    if r.status == "pass":
        r.add("pass", None, f"렌더 {len(pngs)}장 확인, 빈 슬라이드 없음")
    r.summary = f"{len(pngs)} png"
    return r


# ---------------------------------------------------------------- console --
def _wide(s: str) -> int:
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _pad(s: str, w: int) -> str:
    return s + " " * max(0, w - _wide(s))


def print_summary(results: list[Res], title: str) -> None:
    print(f"\n== QA: {title} ==")
    headers = ["check", "status", "summary"]
    rows = [[r.name, r.status.upper(), r.summary or "-"] for r in results]
    widths = [max(_wide(h), *(_wide(r[i]) for r in rows)) for i, h in enumerate(headers)]
    widths[2] = min(widths[2], 72)
    print(" | ".join(_pad(h, w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        row[2] = row[2][:72]
        print(" | ".join(_pad(c, w) for c, w in zip(row, widths)))
    for r in results:
        if r.status == "fail":
            fails = [e for e in r.evidence if e["status"] == "fail"]
            print(f"\n  [{r.name}] fail {len(fails)}건 (앞 5건)")
            for e in fails[:5]:
                loc = f"slide {e['slide']}" if e["slide"] else "deck"
                print(f"    - {loc}: {e['message']}")


# ------------------------------------------------------------------- main --
def run_qa(pptx: Path, spec: dict | None, ledger: list | None, build: dict | None,
           render_dir: Path | None, forbidden: list[str]) -> tuple[list[Res], Deck, list[str]]:
    deck = Deck(pptx)
    types = slide_types(deck, spec)
    lang = (spec or {}).get("meta", {}).get("lang") if spec else None
    if lang is None:
        joined = " ".join(t for sl in deck.slides for t in sl["texts"])
        lang = "ko" if hangul_ratio(joined) >= 0.15 else "en"

    results = [
        check_slide_count(deck, spec),
        check_title_y(deck, types),
        check_title_width(deck, types),
        check_bottomline(deck, types),
        check_image_ar(deck),
        check_image_top(deck, types),
        check_fill_ratio(deck, types, build),
        check_ppi(deck),
        check_forbidden(deck, forbidden),
        check_font_min(deck, types),
        check_notes(deck, types),
        check_hangul_font(deck, lang),
        check_ledger_text(deck, ledger, spec),
        check_build_warnings(build),
        check_render(deck, render_dir),
    ]
    return results, deck, types


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="camp-talk 덱 빌드 후 검사")
    ap.add_argument("pptx", nargs="?")
    ap.add_argument("--spec", help="deck_spec.json (선택)")
    ap.add_argument("--ledger", help="asset_ledger.json (선택)")
    ap.add_argument("--build", help="out.build.json (선택)")
    ap.add_argument("--render", help="render 디렉터리 (선택)")
    ap.add_argument("--forbidden",
                    help="쉼표 구분 금지 문자열 (스펙 없이 쓸 때). 값이 '-' 로 "
                         "시작하면 --forbidden=-37%,re-routing 처럼 = 로 붙여 쓴다")
    ap.add_argument("--out", required=True, help="qa_report.json 출력 경로")
    ap.add_argument("--font-rules", action="store_true",
                    help="FONT_MIN 역할 분류 규칙을 출력하고 끝낸다")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.font_rules:
        print(FONT_RULES_TEXT)
        return 0

    if not args.pptx:
        ap.error("pptx 경로가 필요하다(또는 --font-rules).")
    pptx = Path(args.pptx)
    if not pptx.exists():
        print(f"[error] 파일 없음: {pptx}", file=sys.stderr)
        return 2

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8")) if args.spec else None
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8")) if args.ledger else None
    build = json.loads(Path(args.build).read_text(encoding="utf-8")) if args.build else None
    render_dir = Path(args.render) if args.render else None

    forbidden: list[str] = []
    if spec and spec.get("forbidden"):
        forbidden += list(spec["forbidden"])
    if args.forbidden:
        forbidden += [t.strip() for t in args.forbidden.split(",") if t.strip()]

    results, deck, types = run_qa(pptx, spec, ledger, build, render_dir, forbidden)

    n_fail = sum(1 for r in results if r.status == "fail")
    n_warn = sum(1 for r in results if r.status == "warn")
    report = {
        "deck": str(pptx).replace("\\", "/"),
        "slide_count": len(deck.slides),
        "slide_size_in": [round(deck.w_in, 3), round(deck.h_in, 3)],
        "slide_types": types,
        "verdict": "fail" if n_fail else ("warn" if n_warn else "pass"),
        "counts": {"fail": n_fail, "warn": n_warn,
                   "pass": sum(1 for r in results if r.status == "pass"),
                   "skip": sum(1 for r in results if r.status == "skip")},
        "checks": [r.to_dict() for r in results],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print_summary(results, pptx.name)
        print(f"\nverdict: {report['verdict'].upper()} "
              f"(fail {n_fail} / warn {n_warn}) -> {out}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
