"""Origin COM 세션 관리.

Origin은 단일 인스턴스로 동작한다. 사용자가 Origin에서 작업 중일 때 자동화가 끼어들면
그 프로젝트를 덮어쓸 수 있으므로, 실행 중이면 착수를 거부한다.
"""
from __future__ import annotations

import subprocess
from contextlib import contextmanager


class OriginBusyError(RuntimeError):
    """Origin이 이미 실행 중이라 자동화를 시작할 수 없음."""


# Origin 2021 64-bit의 실제 이미지 이름은 Origin64.exe다. "Origin.exe"는
# "Origin64.exe"의 부분 문자열이 아니므로, Origin.exe만 찾으면 사용자가 Origin을
# 띄워 놓아도 가드가 영원히 발동하지 않는다 (= 이 모듈의 존재 이유가 무력화된다).
# 32-bit 설치본 대비로 두 이름을 모두 확인한다.
ORIGIN_IMAGES = ("Origin64.exe", "Origin.exe")


def is_origin_running() -> bool:
    for image in ORIGIN_IMAGES:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}"],
            capture_output=True, text=True,
        ).stdout
        if image in out:
            return True
    return False


def _drop_stale_handle() -> None:
    """originpro가 들고 있는 죽은 Origin Application 핸들을 버린다.

    originpro의 APP 래퍼는 `self._app.Exit()`가 성공해야 `_app`을 비운다. 종료가
    COM 예외로 깨지면(관측됨: 0x800706BE) 죽은 핸들이 모듈에 남고, 다음 세션은
    Origin을 새로 띄우지 않은 채 그 핸들을 재사용해 "RPC server unavailable"로
    터진다. 세션이 여러 개 이어질 때만 드러나는 함정이라 여기서 정리한다.
    """
    try:
        from originpro import config as cfg
    except Exception:
        return
    if getattr(cfg, "oext", False) and getattr(cfg.po, "_app", None) is not None:
        cfg.po._app = None


@contextmanager
def origin_session(show: bool = False):
    """숨김 Origin 세션. 예외가 나도 반드시 exit()한다.

    yield 하는 것은 originpro 모듈 자체다 (op.open, op.lt_float 등을 그대로 쓴다).
    """
    if is_origin_running():
        raise OriginBusyError(
            "Origin is already running. 작업 중인 프로젝트를 덮어쓸 수 있어 중단합니다. "
            "Origin을 닫고 다시 실행하세요."
        )

    import originpro as op

    try:
        op.set_show(show)
    except Exception:
        _drop_stale_handle()
        op.set_show(show)
    try:
        yield op
    finally:
        try:
            op.exit()
        except Exception:
            pass
        _drop_stale_handle()
