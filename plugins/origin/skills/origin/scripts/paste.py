"""Origin 그래프를 PowerPoint 덱으로 조립한다.

두 단계로 나뉜다.

1. Origin 세션에서 그래프를 하나씩 빌드하고 **각각 독립된 `.opju` 로 저장**한다.
2. Origin을 닫은 뒤 PowerPoint에서 `Shapes.AddOLEObject(FileName=...)` 로 그 파일을
   임베드한다.

클립보드를 경유하지 않는다. `gp.copy_page('OLE')` 는 이 환경(Origin 2021)에서
클립보드에 포맷을 하나도 올리지 못한다 — 반증 실험으로 확정했고, 그래서
`PasteSpecial(ppPasteOLEObject)` 이 "data type unavailable" 로 실패했다.
`AddOLEObject` 는 클립보드를 쓰지 않으므로 이 제약을 통째로 우회하고, 덤으로
병렬 실행과 사용자의 복사·붙여넣기 간섭에도 영향을 받지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pythoncom
import win32com.client as win32

from build import build_graph, load_recipe
from originsession import ORIGIN_IMAGES, origin_session

PP_LAYOUT_BLANK = 12

# 셀 하나의 크기(인치). 임베드한 객체는 비율을 유지한 채 이 안에 맞춘다.
CELL_W_IN, CELL_H_IN = 3.0, 2.1
PT_PER_IN = 72.0

# 슬라이드 높이(인치). PowerPoint 기본값이며, 실제 값은 프레젠테이션에서 읽어
# 넘긴다 (`_assemble_deck`). 격자가 이 아래로 넘어가면 캔버스 밖이라 안 보인다.
SLIDE_H_IN = 7.5

# msoFalse — 링크가 아니라 진짜 임베드(파일 내용이 pptx 안으로 들어간다)여야
# 나중에 .opju 를 지워도 슬라이드에서 편집할 수 있다.
MSO_FALSE = 0


class NoGraphsError(RuntimeError):
    """그래프를 하나도 덱에 넣지 못했다. 덱을 쓰지 않는다."""


def grid_positions(n: int, cols: int, width: float, height: float,
                   gap: float) -> list[tuple[float, float]]:
    """왼쪽 위부터 행 우선으로 배치할 (left, top) 좌표를 인치로 반환한다."""
    if cols < 1:
        raise ValueError(f"cols must be >= 1, got {cols}")
    return [((i % cols) * (width + gap), (i // cols) * (height + gap)) for i in range(n)]


def overflowing(positions, height: float, slide_h: float = SLIDE_H_IN) -> list[int]:
    """슬라이드 바닥 아래로 내려가 보이지 않게 되는 항목의 인덱스.

    격자는 줄바꿈만 하고 페이지는 나누지 않는다. `cols=4` 기준으로 13번째부터
    캔버스 밖으로 나가는데, 지금까지는 아무 신호도 없었다 — 덱을 열어 보기 전에는
    그래프가 사라진 것을 알 수 없다.
    """
    return [i for i, (_, top) in enumerate(positions) if top + height > slide_h]


def fit_size(nat_w: float, nat_h: float, cell_w: float, cell_h: float
             ) -> tuple[float, float]:
    """비율을 유지한 채 셀 안에 들어가는 크기를 준다.

    셀 크기로 폭·높이를 그냥 덮어쓰면 그래프가 찌그러진다. 격자가 겹치지 않으려면
    크기를 정해 줘야 하므로, 늘리지 않고 '가장 빡빡한 축'에 맞춘다.
    """
    if nat_w <= 0 or nat_h <= 0:
        return cell_w, cell_h
    scale = min(cell_w / nat_w, cell_h / nat_h)
    return nat_w * scale, nat_h * scale


def console_safe(text: str) -> str:
    """콘솔 코덱(여기선 cp949)이 못 찍는 글자를 지운다.

    실패 메시지에는 COM이 준 임의의 문자열이 섞인다. 그걸 그대로 print하다
    UnicodeEncodeError가 나면 '실패한 그래프는 건너뛰고 계속한다'는 약속이
    통째로 무너진다 — 보고 때문에 작업이 죽는 건 본말전도다.
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, errors="replace").decode(enc, errors="replace")


CO_E_NOTINITIALIZED = -2147221008


def dispatch_powerpoint():
    """PowerPoint COM 핸들. 죽은 COM 아파트먼트를 되살려서라도 얻는다.

    origin_session이 끝날 때 부르는 op.exit()는 이 스레드의 COM을 해제한다. 우리는
    항상 Origin을 먼저 돌린 뒤 PowerPoint를 잡으므로 이 경로가 곧 정상 경로다.
    pythoncom이 스레드의 초기화 횟수를 자체 캐시하고 있어서 CoInitialize만 다시
    불러서는 안 되고, 먼저 비워야 먹는다(실측).
    """
    try:
        return win32.Dispatch("PowerPoint.Application")
    except Exception as e:
        if getattr(e, "args", (None,))[0] != CO_E_NOTINITIALIZED:
            raise
    for _ in range(4):
        try:
            pythoncom.CoUninitialize()
        except Exception:
            break
    pythoncom.CoInitialize()
    return win32.Dispatch("PowerPoint.Application")


def is_powerpoint_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq POWERPNT.EXE"],
        capture_output=True, text=True,
    ).stdout
    return "POWERPNT.EXE" in out


def origin_pids() -> set[int]:
    """지금 살아 있는 Origin 프로세스의 PID."""
    wanted = {i.lower() for i in ORIGIN_IMAGES}
    pids: set[int] = set()
    for image in ORIGIN_IMAGES:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
        ).stdout
        for row in csv.reader(io.StringIO(out)):
            if len(row) >= 2 and row[0].lower() in wanted:
                try:
                    pids.add(int(row[1]))
                except ValueError:
                    pass
    return pids


def reap_origin_servers(before: set[int]) -> list[int]:
    """PowerPoint가 임베드하면서 띄운 Origin OLE 서버를 정리한다.

    `AddOLEObject` 는 .opju 를 렌더하려고 **창 없는 Origin64.exe** 를 하나씩 띄우고,
    그 프로세스가 소스 파일을 계속 붙들고 있다 (실측 2026-07-29: 중간산물 삭제가
    WinError 32로 실패, 프로세스를 죽이면 즉시 풀린다). 창이 없으므로 WM_CLOSE는
    먹지 않는다 — 강제 종료가 유일한 경로다.

    그냥 두면 두 가지가 깨진다:
      * 중간산물 .opju 를 지울 수 없다.
      * `origin_session` 의 "Origin이 이미 실행 중" 가드가 **다음 실행부터 영원히**
        발동해 이 스킬이 두 번 돌지 못한다.

    덱은 이미 SaveAs 로 디스크에 내려간 뒤라 서버를 죽여도 임베드는 멀쩡하다(검증).

    죽일 대상을 두 조건의 **교집합**으로 좁힌다:
      1. 시작 시점 스냅샷에 없던 PID (= 우리가 도는 동안 생겼다)
      2. **주 창이 없는 프로세스** (= OLE 서버다)

    1번만으로는 부족하다. 조립 중에 사용자가 Origin을 열면 그 PID도 "새 PID"라
    강제 종료 대상이 되어 저장 안 된 프로젝트가 날아간다. 사용자가 대화형으로 띄운
    Origin은 항상 주 창을 갖고, `AddOLEObject` 가 띄우는 OLE 서버는 창이 없다 —
    이 차이가 둘을 가르는 유일하게 신뢰할 수 있는 신호다.

    창 유무를 판정하지 못하면(PowerShell 실패 등) **죽이지 않는다.** 남은 프로세스는
    중간산물 삭제 실패와 다음 실행의 busy 가드로 드러나지만, 그건 되돌릴 수 있다.
    사용자의 미저장 작업은 되돌릴 수 없다.
    """
    new = sorted(origin_pids() - before)
    if not new:
        return []

    windowless = _windowless_pids(new)
    spared = [p for p in new if p not in windowless]
    if spared:
        print(f"  [keep] 주 창이 있는 Origin {spared} — 사용자 세션으로 보고 건드리지 않음")

    reaped = []
    for pid in sorted(windowless):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
        reaped.append(pid)
    return reaped


def _windowless_pids(pids: list[int]) -> set[int]:
    """주어진 PID 중 주 창이 없는 것만 반환한다. 판정 실패 시 빈 집합(= 아무도 안 죽인다)."""
    if not pids:
        return set()
    joined = ",".join(str(p) for p in pids)
    script = (
        f"Get-Process -Id {joined} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowHandle -eq 0 } | "
        "Select-Object -ExpandProperty Id"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return set()
        return {int(line) for line in out.stdout.split() if line.strip().isdigit()}
    except Exception:
        return set()


def remove_tree(path: Path, attempts: int = 5) -> bool:
    """디렉터리를 지운다. 핸들이 늦게 풀릴 수 있어 몇 번 다시 시도한다."""
    for i in range(attempts):
        if not path.exists():
            return True
        try:
            shutil.rmtree(path)
            return True
        except OSError:
            time.sleep(0.3 * (i + 1))
    return not path.exists()


def embed_project(slide, project: Path, left_pt: float, top_pt: float):
    """`.opju` 하나를 편집 가능한 OLE 객체로 슬라이드에 박는다.

    자연 크기로 먼저 넣고 나서 셀에 맞춘다 — 넣을 때 Width/Height를 주면 비율이
    깨진다. 위치는 크기를 바꾼 뒤 다시 잡는다 (크기 변경이 한쪽 모서리를 밀 수 있다).
    """
    project = Path(project).resolve()
    shape = slide.Shapes.AddOLEObject(
        FileName=str(project), Link=MSO_FALSE,
        Left=left_pt, Top=top_pt,
    )
    w, h = fit_size(shape.Width, shape.Height,
                    CELL_W_IN * PT_PER_IN, CELL_H_IN * PT_PER_IN)
    shape.Width, shape.Height = w, h
    shape.Left, shape.Top = left_pt, top_pt
    return shape


def _close_deck(ppt, pres, quit_app: bool) -> None:
    """덱을 닫고, 우리가 띄운 PowerPoint만 종료한다.

    PowerPoint는 단일 인스턴스다. 사용자가 쓰던 PowerPoint에 Dispatch가 그대로
    붙으므로, 무조건 Quit()하면 사용자의 저장 안 된 문서를 같이 닫아 버린다.
    """
    for call in (lambda: pres.Close(), lambda: ppt.Quit() if quit_app else None):
        try:
            call()
        except Exception:
            pass


def _build_projects(recipe: dict, proj_dir: Path, failures: list[str]
                    ) -> list[tuple[dict, Path]]:
    """그래프별로 빌드해 개별 `.opju` 로 저장한다. (spec, 경로) 목록을 반환한다.

    `build_graph` 는 매번 donor를 `op.open` 하고, 이는 현재 프로젝트를 통째로
    교체한다. 그래서 매 반복의 `op.save` 는 그 그래프 하나만 담은 프로젝트가 된다.
    """
    built: list[tuple[dict, Path]] = []
    with origin_session() as op:
        for spec in recipe["graphs"]:
            try:
                gid = spec.get("id")
                if not gid:
                    raise ValueError("graph needs an 'id' (it names the .opju)")
                build_graph(op, spec, style_mode=recipe["style"])
                proj = (proj_dir / f"{gid}.opju").resolve()
                # 목적지를 먼저 비운다. 파일이 남아 있으면 저장이 실패해도
                # `exists()` 가 참이라 **이전 실행의 그래프가 새 덱에 박힌다.**
                if proj.exists():
                    proj.unlink()
                saved = op.save(str(proj))
                # 반환값과 파일 존재를 모두 본다 — 어느 한쪽만으로는 위 사고를
                # 재현할 수 있다 (save는 실패해도 조용한 편이다).
                if not saved or not proj.exists():
                    raise RuntimeError(f"Origin did not write {proj.name}")
                built.append((spec, proj))
                print(f"  [ok] {gid} ({spec.get('donor', '?')})")
            except Exception as e:
                # 처리기 자신이 KeyError로 터지면 '건너뛰고 계속' 계약이 깨진다.
                reason = console_safe(f"{spec.get('id', '?')}: {e}")
                failures.append(reason)
                print(f"  [FAIL] {reason}")
    return built


def _assemble_deck(built: list[tuple[dict, Path]], out_path: Path, cols: int,
                   gap: float, failures: list[str]) -> int:
    """빌드된 프로젝트를 슬라이드에 격자로 박고 저장한다. 성공 개수를 반환한다."""
    positions = grid_positions(len(built), cols, CELL_W_IN, CELL_H_IN, gap)

    # Origin 세션은 이미 닫혔다. 지금 살아 있는 Origin이 있다면 사용자 것이므로
    # 스냅샷에 담아 두고, 임베드가 새로 띄우는 것만 나중에 거둔다.
    origin_before = origin_pids()

    quit_app = not is_powerpoint_running()
    ppt = dispatch_powerpoint()
    pres = ppt.Presentations.Add()
    slide = pres.Slides.Add(1, PP_LAYOUT_BLANK)

    try:
        slide_h = float(pres.PageSetup.SlideHeight) / PT_PER_IN
    except Exception:
        slide_h = SLIDE_H_IN
    over = overflowing(positions, CELL_H_IN, slide_h)
    if over:
        names = [built[i][0].get("id", "?") for i in over]
        print(f"  [warn] {len(over)}개가 슬라이드({slide_h:g}in) 아래로 넘어갑니다: "
              f"{names} — layout.cols 를 늘리거나 그래프를 나누세요")

    embedded = 0
    try:
        for (spec, proj), (left, top) in zip(built, positions):
            try:
                embed_project(slide, proj, left * PT_PER_IN, top * PT_PER_IN)
                embedded += 1
            except Exception as e:
                reason = console_safe(f"{spec.get('id', '?')}: OLE embed failed: {e}")
                failures.append(reason)
                print(f"  [FAIL] {reason}")
        if embedded:
            pres.SaveAs(str(out_path.resolve()))
    finally:
        _close_deck(ppt, pres, quit_app)
        reaped = reap_origin_servers(origin_before)
        if reaped:
            print(f"  [cleanup] closed {len(reaped)} Origin OLE server(s)")
    return embedded


def run_recipe(recipe_path: Path, out_dir: Path) -> Path:
    """레시피 하나를 pptx로 만든다.

    하나도 성공하지 못하면 `NoGraphsError` 를 던진다 — 빈 덱을 써 놓고 성공한 척하면
    호출자가 성공과 실패를 구분할 수 없다.
    """
    recipe = load_recipe(Path(recipe_path))
    layout = recipe.get("layout", {})
    cols = int(layout.get("cols", 4))
    gap = float(layout.get("gap_in", 0.15))

    for spec in recipe["graphs"]:
        if spec.get("donor_inferred"):
            print(f"  [infer] {spec.get('id', '?')}: donor={spec['donor']} "
                  f"(데이터 형태로 추론함)")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{recipe['output']}.pptx"
    # 임베드가 끝나면 필요 없는 중간산물이다 (Link=False 라 내용이 pptx로 복사된다).
    proj_dir = out_dir / f"_{recipe['output']}_projects"
    proj_dir.mkdir(parents=True, exist_ok=True)

    total = len(recipe["graphs"])
    failures: list[str] = []
    built = _build_projects(recipe, proj_dir, failures)

    embedded = 0
    if built:
        embedded = _assemble_deck(built, out_path, cols, gap, failures)

    if failures:
        print("\n실패한 그래프:")
        for f in failures:
            print(f"  - {f}")

    if not embedded:
        # 진단에 쓸 수 있게 중간산물은 남긴다.
        raise NoGraphsError(
            f"0/{total} graphs made it into the deck; no file was written to "
            f"{out_path}. reasons: " + " | ".join(failures or ["(none reported)"])
        )

    if not remove_tree(proj_dir):
        print(f"  [warn] 중간산물을 지우지 못했습니다: {proj_dir}")
    if embedded < total:
        print(f"\n부분 성공: {embedded}/{total} graphs embedded "
              f"({total - embedded} failed)")
    print(f"\nwrote {out_path}  ({embedded}/{total} graphs)")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Origin graphs into a pptx")
    ap.add_argument("recipe", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("output"))
    args = ap.parse_args()
    try:
        run_recipe(args.recipe, args.out)
    except NoGraphsError as e:
        print(f"\n실패: {console_safe(e)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
