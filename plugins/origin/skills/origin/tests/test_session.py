import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from originsession import OriginBusyError, is_origin_running, origin_session  # noqa: E402


def test_is_origin_running_returns_bool():
    assert isinstance(is_origin_running(), bool)


def test_detects_running_origin(monkeypatch):
    """실패해야 정상: Origin이 떠 있으면 세션을 열지 않고 예외를 낸다."""
    monkeypatch.setattr("originsession.is_origin_running", lambda: True)
    with pytest.raises(OriginBusyError, match="already running"):
        with origin_session():
            pass


@pytest.mark.origin
def test_session_opens_and_closes():
    with origin_session() as op:
        assert op.lt_float("@V") > 0
        # 세션이 살아 있는 동안 탐지기가 실제로 발동해야 한다. 이 확인이 없으면 아래
        # 종료 확인은 "원래부터 그 이름의 프로세스가 없었다"와 구분되지 않는
        # 항진명제가 된다 (구 버전이 Origin.exe를 찾다가 빠졌던 함정).
        assert is_origin_running()

    # Origin 2021 64-bit의 실제 이미지 이름으로 확인해야 의미가 있다.
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Origin64.exe"],
        capture_output=True, text=True,
    ).stdout
    assert "Origin64.exe" not in out
    assert not is_origin_running()
