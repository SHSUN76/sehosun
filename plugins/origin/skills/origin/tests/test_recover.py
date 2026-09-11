import sys
import zipfile
from pathlib import Path

import olefile
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from recover import (CONTENT_STREAMS, ORIGIN_MAGICS, recover_all,  # noqa: E402
                     recover_one)

DECK = Path(r"C:\Obsidian\SSH\4.Project\6. 논문 작성중\Origin graph list.pptx")


def test_magic_prefixes_cover_both_flavors():
    assert b"CPYA" in ORIGIN_MAGICS
    assert b"CPYUA" in ORIGIN_MAGICS


@pytest.mark.skipif(not DECK.exists(), reason="reference deck not present")
def test_recovers_all_35_graphs(tmp_path):
    results = recover_all(DECK, tmp_path)
    assert len(results) == 35
    assert all(r.path.exists() for r in results)
    assert all(r.path.suffix == ".opj" for r in results)


def _embedded_streams(deck: Path, staging: Path) -> dict[str, bytes]:
    """덱에서 OLE Contents 스트림을 recover.py 와 무관하게 직접 꺼낸다."""
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(deck) as z:
        members = [n for n in z.namelist()
                   if n.startswith("ppt/embeddings/") and n.endswith(".bin")]
        for m in members:
            raw = staging / ("src_" + Path(m).name)
            raw.write_bytes(z.read(m))
            with olefile.OleFileIO(str(raw)) as ole:
                name = next(s for s in CONTENT_STREAMS if ole.exists(s))
                out[Path(m).name] = ole.openstream(name).read()
    return out


@pytest.mark.skipif(not DECK.exists(), reason="reference deck not present")
def test_recovered_files_match_the_embedded_streams(tmp_path):
    """복원본이 원본 스트림과 바이트 단위로 같고, 서로 덮어쓰지 않았는지 확인한다.

    이 자리에 있던 '복원 파일이 Origin 매직으로 시작하는가' 는 실패할 수 없는
    동어반복이었다 — `recover_one` 이 쓰기 *전에* 같은 바이트에 대해 이미 강제하는
    조건이라, 통과해도 아무것도 증명하지 못한다. 실제 위험은 다른 데 있다:
    스트림을 잘라 쓰거나, 두 OLE가 같은 목적지로 가서 하나가 조용히 사라지는 것.
    """
    staging = tmp_path / "staging"
    staging.mkdir()
    out = tmp_path / "out"
    results = recover_all(DECK, out)
    expected = _embedded_streams(DECK, staging)

    assert len(results) == len(expected), "임베드 개수와 복원 개수가 다르다"
    assert len({r.path for r in results}) == len(results), "복원본 경로가 겹친다"

    for r in results:
        assert r.name in expected, f"{r.name}: 원본 임베드에 없는 이름"
        got = r.path.read_bytes()
        assert len(got) == r.size, f"{r.name}: 보고한 크기와 파일 크기가 다르다"
        assert got == expected[r.name], f"{r.name}: 복원본이 원본 스트림과 다르다"
        assert any(got.startswith(m) for m in ORIGIN_MAGICS)


def test_rejects_non_ole_payload(tmp_path):
    """실패해야 정상: OLE가 아닌 파일은 조용히 넘어가지 않고 예외를 낸다."""
    bogus = tmp_path / "bogus.bin"
    bogus.write_bytes(b"not an ole file at all")
    with pytest.raises(ValueError, match="not an OLE"):
        recover_one(bogus, tmp_path / "out.opj")
