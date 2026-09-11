"""Recover embedded Origin projects from a PowerPoint deck's OLE objects.

Origin 그래프를 PowerPoint에 붙여넣으면 프로젝트 전체가 OLE 객체의 Contents 스트림에
들어간다. 이 스크립트는 그것을 독립 .opj 파일로 꺼낸다. Origin이 필요 없다.
"""
from __future__ import annotations

import argparse
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import olefile

# Origin 프로젝트 파일 시그니처. Origin50.Graph는 CPYA, Origin95.Graph는 CPYUA.
ORIGIN_MAGICS = (b"CPYA", b"CPYUA")

# OLE 안에서 프로젝트가 들어 있는 스트림 이름 (대소문자 변형 존재)
CONTENT_STREAMS = ("CONTENTS", "Contents")


@dataclass
class Recovered:
    name: str       # 원본 OLE 파일명 (oleObject17.bin)
    path: Path      # 복원된 .opj 경로
    size: int


def recover_one(ole_path: Path, dst: Path) -> Recovered:
    """OLE 객체 하나에서 Origin 프로젝트를 꺼낸다."""
    if not olefile.isOleFile(str(ole_path)):
        raise ValueError(f"{ole_path.name} is not an OLE compound file")

    with olefile.OleFileIO(str(ole_path)) as ole:
        stream = next((s for s in CONTENT_STREAMS if ole.exists(s)), None)
        if stream is None:
            found = ["/".join(p) for p in ole.listdir()]
            raise ValueError(f"{ole_path.name} has no Contents stream (streams: {found})")
        data = ole.openstream(stream).read()

    if not any(data.startswith(m) for m in ORIGIN_MAGICS):
        raise ValueError(f"{ole_path.name} Contents is not an Origin project (head={data[:8]!r})")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return Recovered(name=ole_path.name, path=dst, size=len(data))


def _sort_key(name: str) -> int:
    digits = "".join(c for c in name if c.isdigit())
    return int(digits) if digits else 0


def recover_all(pptx: Path, out_dir: Path) -> list[Recovered]:
    """pptx의 모든 임베드 OLE에서 Origin 프로젝트를 복원한다.

    선별하지 않는다 — 전부 꺼낸다. donor 9종 선별은 별도의 큐레이션 작업이다.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # staging은 중간산물일 뿐이다. out_dir에 두면 .opj와 같은 크기의 .bin이 나란히
    # 남아 저장소를 두 배로 부풀린다 (35개 기준 7MB). 임시 디렉터리에서 처리하고 버린다.
    results: list[Recovered] = []
    with tempfile.TemporaryDirectory(prefix="origin_recover_") as tmp:
        staging = Path(tmp)
        with zipfile.ZipFile(pptx) as z:
            members = [n for n in z.namelist()
                       if n.startswith("ppt/embeddings/") and n.endswith(".bin")]
            for m in members:
                (staging / Path(m).name).write_bytes(z.read(m))

        for bin_path in sorted(staging.iterdir(), key=lambda p: _sort_key(p.name)):
            dst = out_dir / bin_path.name.replace(".bin", ".opj")
            results.append(recover_one(bin_path, dst))
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Recover Origin projects from a pptx")
    ap.add_argument("pptx", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    results = recover_all(args.pptx, args.out)
    for r in results:
        print(f"{r.name:<18} -> {r.path.name:<18} {r.size:>9,} bytes")
    print(f"\nrecovered {len(results)} projects -> {args.out}")


if __name__ == "__main__":
    main()
