#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_deck.py — pptx 를 슬라이드 PNG 로 렌더한다.

LibreOffice headless 로 pdf 를 만들고 PyMuPDF 로 페이지마다
`slide_NN.png` 를 뽑는다. 빌드 직후 눈으로 확인하는 용도이며,
deck_qa.py 의 `--render` 입력이 된다.

사용법
    python render_deck.py <deck.pptx> [--dpi 110] [--out render_dir]
                          [--sheet 1,2,14,20,25,29] [--soffice PATH]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF < 1.24
    import fitz
from PIL import Image

DEFAULT_SOFFICE = r"C:/Program Files/LibreOffice/program/soffice.exe"
SHEET_COLS, SHEET_ROWS = 3, 2   # contact sheet 2행 x 3열
SHEET_TILE_W = 900              # 타일 한 칸 폭(px)
SHEET_MARGIN = 18
SHEET_LABEL_H = 34


def find_soffice(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.path.exists(DEFAULT_SOFFICE):
        return DEFAULT_SOFFICE
    for cand in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(cand)
        if found:
            return found
    return DEFAULT_SOFFICE


def convert_to_pdf(soffice: str, pptx: Path, outdir: Path,
                   attempt: int = 1) -> Path:
    """soffice --headless 로 pdf 변환. 잠금 파일 실패 시 1회 재시도."""
    outdir.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.gettempdir()) / f"conf_talk_lo_profile_{os.getpid()}_{attempt}"
    profile_uri = "file:///" + str(profile).replace("\\", "/").lstrip("/")
    cmd = [
        soffice,
        f"-env:UserInstallation={profile_uri}",
        "--headless", "--norestore", "--invisible", "--nolockcheck",
        "--convert-to", "pdf:impress_pdf_Export",
        "--outdir", str(outdir), str(pptx),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    pdf = outdir / (pptx.stem + ".pdf")
    if pdf.exists():
        return pdf

    detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if attempt == 1:
        print(f"[warn] soffice 변환 실패(1차). 재시도한다.\n        {detail[:400]}",
              file=sys.stderr)
        # 잠금 파일이 남아 있으면 치운다
        for junk in (pptx.parent / f".~lock.{pptx.name}#",):
            try:
                junk.unlink()
            except OSError:
                pass
        try:
            shutil.rmtree(profile, ignore_errors=True)
        except OSError:
            pass
        time.sleep(4)
        return convert_to_pdf(soffice, pptx, outdir, attempt=2)
    raise RuntimeError(f"soffice pdf 변환 실패 (2회): {detail[:800]}")


def render_pdf(pdf: Path, outdir: Path, dpi: int) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    with fitz.open(pdf) as doc:
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(dpi=dpi)
            dst = outdir / f"slide_{i:02d}.png"
            pix.save(dst)
            pages.append(dst)
    return pages


def contact_sheet(pages: list[Path], picks: list[int], dst: Path) -> Path | None:
    """지정 슬라이드 번호 6장을 2x3 으로 붙인 연락용 시트."""
    chosen = []
    for n in picks:
        if 1 <= n <= len(pages):
            chosen.append((n, pages[n - 1]))
        else:
            print(f"[warn] contact sheet: 슬라이드 {n} 없음(총 {len(pages)}장)",
                  file=sys.stderr)
    if not chosen:
        return None

    tiles = []
    for n, p in chosen[:SHEET_COLS * SHEET_ROWS]:
        with Image.open(p) as im:
            im = im.convert("RGB")
            h = max(1, round(SHEET_TILE_W * im.height / im.width))
            tiles.append((n, im.resize((SHEET_TILE_W, h), Image.LANCZOS)))

    tile_h = max(t.height for _, t in tiles)
    cols = SHEET_COLS
    rows = (len(tiles) + cols - 1) // cols
    W = SHEET_MARGIN + cols * (SHEET_TILE_W + SHEET_MARGIN)
    H = SHEET_MARGIN + rows * (tile_h + SHEET_LABEL_H + SHEET_MARGIN)
    sheet = Image.new("RGB", (W, H), (255, 255, 255))

    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("malgun.ttf", 22)
        except OSError:
            font = ImageFont.load_default()
    except ImportError:  # pragma: no cover
        draw, font = None, None

    for idx, (n, tile) in enumerate(tiles):
        r, c = divmod(idx, cols)
        x = SHEET_MARGIN + c * (SHEET_TILE_W + SHEET_MARGIN)
        y = SHEET_MARGIN + r * (tile_h + SHEET_LABEL_H + SHEET_MARGIN)
        sheet.paste(tile, (x, y))
        if draw is not None:
            draw.rectangle([x, y, x + SHEET_TILE_W, y + tile.height],
                           outline=(190, 190, 190), width=2)
            draw.text((x + 4, y + tile.height + 6), f"slide {n}",
                      fill=(40, 40, 40), font=font)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst)
    return dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pptx -> PDF -> slide_NN.png 렌더")
    ap.add_argument("pptx")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--out", help="렌더 디렉터리(기본: <pptx 폴더>/render)")
    ap.add_argument("--sheet", help="contact sheet 슬라이드 번호, 예 1,2,14,20,25,29")
    ap.add_argument("--soffice", help="soffice 실행 파일 경로")
    ap.add_argument("--keep-pdf", action="store_true", help="중간 pdf 보존")
    args = ap.parse_args(argv)

    pptx = Path(args.pptx).resolve()
    if not pptx.exists():
        print(f"[error] 파일 없음: {pptx}", file=sys.stderr)
        return 2
    outdir = Path(args.out).resolve() if args.out else pptx.parent / "render"
    outdir.mkdir(parents=True, exist_ok=True)

    soffice = find_soffice(args.soffice)
    if not (os.path.exists(soffice) or shutil.which(soffice)):
        print(f"[error] soffice 를 찾을 수 없다: {soffice}", file=sys.stderr)
        return 2

    pdf_dir = outdir / "_pdf"
    t0 = time.time()
    pdf = convert_to_pdf(soffice, pptx, pdf_dir)
    pages = render_pdf(pdf, outdir, args.dpi)
    took = time.time() - t0

    print(f"deck      : {pptx}")
    print(f"pages     : {len(pages)}")
    print(f"dpi       : {args.dpi}")
    print(f"out       : {outdir}")
    print(f"elapsed   : {took:.1f}s")

    if args.sheet:
        picks = [int(x) for x in args.sheet.replace(" ", "").split(",") if x]
        sheet = contact_sheet(pages, picks, outdir / "contact_sheet.png")
        if sheet:
            print(f"sheet     : {sheet}")

    if not args.keep_pdf:
        shutil.rmtree(pdf_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
