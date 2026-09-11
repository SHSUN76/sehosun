"""donor .opj 전수를 PNG로 렌더한다 (Task 5 donor 큐레이션용 일회용 스크립트).

survey.py가 만드는 manifest는 수치만 담는다. 어떤 donor가 어떤 그림인지는 눈으로
봐야 고를 수 있으므로 미리보기를 뽑아 둔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from originsession import origin_session  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "donors" / "_unused"
OUT = SRC / "_preview"
OUT.mkdir(exist_ok=True)

with origin_session() as op:
    for opj in sorted(SRC.glob("*.opj")):
        # survey.py와 같은 이유로 절대 경로를 넘긴다 — Origin COM은 상대 경로를
        # 자기 작업 디렉터리 기준으로 풀어서 조용히 실패한다.
        if not op.open(str(opj.resolve()), readonly=False):
            print(f"SKIP {opj.name}")
            continue
        graphs = op.graph_list()
        if not graphs:
            print(f"SKIP {opj.name} (no graph)")
            continue
        png = str(OUT / f"{opj.stem}.png").replace("\\", "/")
        op.find_graph(graphs[0].name).save_fig(png, width=700)
        print(f"{opj.name} -> {png}")
