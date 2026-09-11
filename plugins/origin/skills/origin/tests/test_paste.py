"""격자 산술(순수 함수) + 실제로 OLE가 박혔는지의 엔드투엔드 확인."""
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import paste  # noqa: E402
from paste import (NoGraphsError, fit_size, grid_positions,  # noqa: E402
                   overflowing, run_recipe)

FIX = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------- 순수 함수

def test_grid_wraps_by_cols():
    """cols에서 줄바꿈하고, 다음 행은 height+gap 만큼 내려간다."""
    got = grid_positions(5, cols=2, width=3.0, height=2.1, gap=0.2)
    flat = [round(v, 6) for pair in got for v in pair]
    assert flat == [
        0.0, 0.0, 3.2, 0.0,
        0.0, 2.3, 3.2, 2.3,
        0.0, 4.6,
    ]


def test_grid_single_column_is_a_stack():
    got = grid_positions(3, cols=1, width=3.0, height=2.1, gap=0.0)
    assert [left for left, _ in got] == [0.0, 0.0, 0.0]
    assert [top for _, top in got] == [0.0, 2.1, 4.2]


def test_grid_of_nothing_is_empty():
    assert grid_positions(0, cols=4, width=3.0, height=2.1, gap=0.2) == []


def test_grid_rejects_zero_cols():
    """실패해야 정상: cols=0이면 나눗셈이 아니라 모듈로가 터진다. 그 전에 막는다."""
    with pytest.raises(ValueError, match="cols must be >= 1"):
        grid_positions(4, cols=0, width=3.0, height=2.1, gap=0.2)


def test_grid_rejects_negative_cols():
    with pytest.raises(ValueError, match="cols must be >= 1"):
        grid_positions(4, cols=-2, width=3.0, height=2.1, gap=0.2)


def test_fit_keeps_aspect_and_stays_inside_the_cell():
    """넓적한 그래프는 폭에 걸리고, 비율은 유지된다."""
    w, h = fit_size(400.0, 200.0, cell_w=216.0, cell_h=151.2)
    assert (w, h) == pytest.approx((216.0, 108.0))
    assert w <= 216.0 and h <= 151.2


def test_fit_binds_on_height_when_tall():
    w, h = fit_size(200.0, 400.0, cell_w=216.0, cell_h=151.2)
    assert h == pytest.approx(151.2)
    assert w == pytest.approx(75.6)


def test_fit_survives_a_degenerate_size():
    """OLE 객체 크기를 못 읽어 0이 와도 셀 크기로 떨어질 뿐 죽지 않는다."""
    assert fit_size(0.0, 0.0, 216.0, 151.2) == (216.0, 151.2)


# ------------------------------------------------ 슬라이드 밖으로 나가는 격자

def test_a_grid_that_fits_reports_no_overflow():
    """경고가 항상 나오면 아무 정보도 주지 못한다 — 들어맞는 격자엔 조용해야 한다."""
    got = grid_positions(12, cols=4, width=3.0, height=2.1, gap=0.15)
    assert overflowing(got, height=2.1, slide_h=7.5) == []


def test_the_thirteenth_graph_falls_off_the_slide():
    """cols=4 기준 13번째부터 캔버스 밖이다 — 덱을 열기 전에는 사라진 걸 알 수 없다."""
    got = grid_positions(16, cols=4, width=3.0, height=2.1, gap=0.15)
    assert overflowing(got, height=2.1, slide_h=7.5) == [12, 13, 14, 15]


def test_overflow_follows_the_actual_slide_height():
    """슬라이드 높이는 상수가 아니라 프레젠테이션에서 읽어 넘긴다."""
    got = grid_positions(8, cols=4, width=3.0, height=2.1, gap=0.15)
    assert overflowing(got, height=2.1, slide_h=7.5) == []
    assert overflowing(got, height=2.1, slide_h=4.0) == [4, 5, 6, 7]


# ------------------------------------------------------------ 엔드투엔드

RECIPE_2 = """
output: two_graphs
style: house
layout:
  cols: 2
  gap_in: 0.2
graphs:
  - id: solubility
    donor: bar_labeled
    data: {csv}
    x: cyclodextrin
    y: solubility
    y_title: "g / 100 mL"
    y_range: auto
  - id: solubility_again
    donor: bar_labeled
    data: {csv}
    x: cyclodextrin
    y: solubility
    y_title: "g / 100 mL"
    y_range: auto
"""


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    """그래프 2개짜리 덱을 한 번만 만들어 두 검사에서 나눠 쓴다 (Origin 기동이 비싸다)."""
    tmp = tmp_path_factory.mktemp("deck")
    recipe = tmp / "two.yaml"
    recipe.write_text(
        RECIPE_2.format(csv=(FIX / "water_solubility_greek.csv").as_posix()),
        encoding="utf-8",
    )
    return run_recipe(recipe, tmp / "out")


@pytest.mark.origin
@pytest.mark.powerpoint
def test_deck_file_is_written(deck):
    assert deck.exists(), f"no deck at {deck}"
    with zipfile.ZipFile(deck) as z:
        assert "ppt/slides/slide1.xml" in z.namelist(), "덱에 슬라이드가 없다"


@pytest.mark.origin
@pytest.mark.powerpoint
def test_deck_embeds_editable_ole_objects(deck):
    """핵심 주장: 그림이 그럴듯한 게 아니라 진짜 OLE가 박혔는가.

    PNG를 붙여도 슬라이드는 멀쩡해 보인다. 편집 가능 여부는 ppt/embeddings/에
    OLE 바이너리가 있고 슬라이드가 그것을 progId로 참조할 때만 참이다.
    """
    with zipfile.ZipFile(deck) as z:
        embeddings = [n for n in z.namelist() if n.startswith("ppt/embeddings/")]
        slide_xml = z.read("ppt/slides/slide1.xml").decode("utf-8", "replace")

    assert len(embeddings) == 2, f"OLE 임베드 개수가 2가 아니다: {embeddings}"
    assert "progId" in slide_xml, "슬라이드가 OLE 객체를 참조하지 않는다"
    assert "Origin" in slide_xml, "임베드된 OLE가 Origin 객체가 아니다"


@pytest.mark.origin
@pytest.mark.powerpoint
def test_no_origin_process_survives_the_run(deck):
    """임베드가 띄운 Origin OLE 서버가 남으면 다음 실행이 통째로 막힌다.

    `AddOLEObject` 는 .opju 마다 창 없는 Origin64.exe 를 띄운다. 그걸 거두지 않으면
    `origin_session` 의 "Origin이 이미 실행 중" 가드가 영원히 발동해 이 스킬을
    두 번 돌릴 수 없다.
    """
    from originsession import is_origin_running
    assert not is_origin_running(), "Origin 프로세스가 남아 있다 (OLE 서버 미회수)"


@pytest.mark.origin
@pytest.mark.powerpoint
def test_temporary_project_folder_is_cleaned_up(deck):
    """중간산물 .opju 폴더는 성공 시 남지 않는다 (Link=False라 pptx에 복사됐다)."""
    leftovers = [p for p in deck.parent.iterdir() if p.name.startswith("_")]
    assert not leftovers, f"임시 프로젝트 폴더가 남았다: {leftovers}"


# ------------------------------------------------ OLE 서버 회수 (COM 불필요)

class _Done:
    def __init__(self, out="", returncode=0):
        self.stdout = out
        self.returncode = returncode


def test_origin_pids_parses_tasklist_output(monkeypatch):
    """'실행 중인 작업이 없습니다' 안내문을 PID로 착각하면 안 된다."""
    def fake_run(cmd, **kw):
        if "IMAGENAME eq Origin64.exe" in cmd:
            return _Done('"Origin64.exe","142344","Console","1","1,234,567 K"\n')
        return _Done("정보: 지정한 조건에 맞는 작업이 실행되고 있지 않습니다.\n")

    monkeypatch.setattr(paste.subprocess, "run", fake_run)
    assert paste.origin_pids() == {142344}


def _record_kills(monkeypatch):
    killed = []
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda cmd, **kw: (killed.append(cmd), _Done())[1])
    return killed


def test_reap_kills_the_windowless_servers_that_appeared(monkeypatch):
    """실행 전부터 있던 Origin(사용자 것)은 건드리지 않는다."""
    monkeypatch.setattr(paste, "origin_pids", lambda: {100, 200, 300})
    monkeypatch.setattr(paste, "_windowless_pids", lambda pids: set(pids))
    killed = _record_kills(monkeypatch)

    assert paste.reap_origin_servers({100}) == [200, 300]
    assert [cmd[2] for cmd in killed] == ["200", "300"]


def test_reap_spares_a_new_origin_that_has_a_window(monkeypatch):
    """조립 중에 사용자가 Origin을 열면 그것도 '새 PID'다 — 창이 있으면 살려 둔다.

    죽이면 저장 안 된 사용자 프로젝트가 날아간다. 되돌릴 수 없는 쪽을 보호한다.
    """
    monkeypatch.setattr(paste, "origin_pids", lambda: {100, 200, 300})
    monkeypatch.setattr(paste, "_windowless_pids", lambda pids: {300})
    killed = _record_kills(monkeypatch)

    assert paste.reap_origin_servers({100}) == [300]
    assert [cmd[2] for cmd in killed] == ["300"], "창 있는 Origin(200)을 죽였다"


def test_reap_kills_nobody_when_the_window_check_fails(monkeypatch):
    """판정 실패(빈 집합)면 아무도 죽이지 않는다 — 남은 프로세스는 되돌릴 수 있다."""
    monkeypatch.setattr(paste, "origin_pids", lambda: {100, 200, 300})
    monkeypatch.setattr(paste, "_windowless_pids", lambda pids: set())
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda *a, **k: pytest.fail("창 유무를 모르는데 taskkill을 불렀다"))
    assert paste.reap_origin_servers({100}) == []


def test_reap_does_nothing_when_no_server_appeared(monkeypatch):
    monkeypatch.setattr(paste, "origin_pids", lambda: {100})
    monkeypatch.setattr(paste, "_windowless_pids",
                        lambda pids: pytest.fail("새 PID가 없는데 창을 조회했다"))
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda *a, **k: pytest.fail("죽일 게 없는데 taskkill을 불렀다"))
    assert paste.reap_origin_servers({100}) == []


# ------------------------------------------------ 창 유무 판정 (COM 불필요)

def test_windowless_pids_reads_the_powershell_output(monkeypatch):
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda *a, **k: _Done("200\n300\n"))
    assert paste._windowless_pids([100, 200, 300]) == {200, 300}


def test_windowless_pids_is_empty_when_powershell_fails(monkeypatch):
    """실패를 '창 없음'으로 읽으면 사용자 Origin을 전부 죽인다."""
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda *a, **k: _Done("200\n", returncode=1))
    assert paste._windowless_pids([100, 200]) == set()


def test_windowless_pids_is_empty_when_powershell_explodes(monkeypatch):
    def boom(*a, **k):
        raise OSError("powershell not found")

    monkeypatch.setattr(paste.subprocess, "run", boom)
    assert paste._windowless_pids([100, 200]) == set()


def test_windowless_pids_ignores_non_numeric_noise(monkeypatch):
    """PowerShell이 경고문을 섞어 내보내도 그것을 PID로 착각하면 안 된다."""
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda *a, **k: _Done("WARNING: something\n200\n"))
    assert paste._windowless_pids([100, 200]) == {200}


def test_windowless_pids_does_not_shell_out_for_an_empty_list(monkeypatch):
    monkeypatch.setattr(paste.subprocess, "run",
                        lambda *a, **k: pytest.fail("빈 목록으로 PowerShell을 불렀다"))
    assert paste._windowless_pids([]) == set()


# ------------------------------------- 개별 .opju 저장의 계약 (COM 불필요)

class _SaveOp:
    """`op.save` 가 무엇을 반환하고 파일을 실제로 쓰는지 시나리오로 조종한다."""

    def __init__(self, returns=True, writes=True):
        self.returns = returns
        self.writes = writes
        self.saved = []

    def save(self, path):
        self.saved.append(path)
        if self.writes:
            Path(path).write_text("fresh project", encoding="utf-8")
        return self.returns


def _projects(monkeypatch, op, graphs, proj_dir):
    """`_build_projects` 를 Origin 없이 돌린다. (built, failures)"""
    from contextlib import contextmanager

    @contextmanager
    def fake_session(show=False):
        yield op

    monkeypatch.setattr(paste, "origin_session", fake_session)
    monkeypatch.setattr(paste, "build_graph",
                        lambda op, spec, style_mode="house": "Graph1")
    failures: list[str] = []
    built = paste._build_projects({"style": "house", "graphs": graphs},
                                  proj_dir, failures)
    return built, failures


def test_a_stale_project_file_is_not_mistaken_for_a_fresh_save(tmp_path, monkeypatch):
    """실패해야 정상(수정 전): `op.save` 반환값을 버리고 `exists()` 만 봤다.

    같은 이름의 파일이 이미 있으면 저장이 실패해도 통과하고, **이전 실행의 그래프가
    새 덱에 박힌다.** 눈으로는 구분되지 않는 종류의 사고다.
    """
    proj_dir = tmp_path / "p"
    proj_dir.mkdir()
    stale = proj_dir / "g.opju"
    stale.write_text("이전 실행 잔재", encoding="utf-8")

    op = _SaveOp(returns=False, writes=False)
    built, failures = _projects(monkeypatch, op, [{"id": "g", "donor": "bar_labeled"}],
                                proj_dir)

    assert built == [], "저장에 실패했는데 성공으로 넘어갔다"
    assert failures and "did not write" in failures[0], failures
    assert not stale.exists(), "이전 실행 잔재가 그대로 남아 다음 단계로 흘러간다"


def test_a_save_that_writes_nothing_is_a_failure(tmp_path, monkeypatch):
    """반환값이 True여도 파일이 없으면 실패다 (반대편도 막는다)."""
    proj_dir = tmp_path / "p"
    proj_dir.mkdir()
    op = _SaveOp(returns=True, writes=False)
    built, failures = _projects(monkeypatch, op, [{"id": "g", "donor": "bar_labeled"}],
                                proj_dir)
    assert built == []
    assert failures and "did not write" in failures[0], failures


def test_a_real_save_lands_in_the_built_list(tmp_path, monkeypatch):
    """항상 실패하는 구현이면 위 두 테스트는 무의미하다 — 성공 경로도 고정한다."""
    proj_dir = tmp_path / "p"
    proj_dir.mkdir()
    stale = proj_dir / "g.opju"
    stale.write_text("이전 실행 잔재", encoding="utf-8")

    op = _SaveOp(returns=True, writes=True)
    built, failures = _projects(monkeypatch, op, [{"id": "g", "donor": "bar_labeled"}],
                                proj_dir)

    assert failures == []
    assert [spec["id"] for spec, _ in built] == ["g"]
    assert built[0][1].read_text(encoding="utf-8") == "fresh project"


def test_a_graph_without_an_id_does_not_abort_the_run(tmp_path, monkeypatch):
    """실패해야 정상(수정 전): 예외 처리기가 `spec['id']` 를 참조해 KeyError로 다시
    터졌다. '건너뛰고 계속' 계약이 처리기 자신 때문에 깨진다."""
    proj_dir = tmp_path / "p"
    proj_dir.mkdir()
    op = _SaveOp()
    built, failures = _projects(
        monkeypatch, op,
        [{"donor": "bar_labeled"}, {"id": "ok", "donor": "bar_labeled"}], proj_dir)

    assert [spec["id"] for spec, _ in built] == ["ok"], "뒤 그래프까지 죽었다"
    assert len(failures) == 1 and failures[0].startswith("?:"), failures


# ------------------------------------------------- 전멸했을 때의 신호 (COM 불필요)

RECIPE_1 = """
output: only_one
style: house
graphs:
  - id: doomed
    donor: bar_labeled
    data: {csv}
    x: cyclodextrin
    y: solubility
"""


class _FakeOp:
    """origin_session 이 내주는 것 흉내. 아무것도 하지 않는다."""

    def save(self, path):        # pragma: no cover - 호출되면 안 된다
        raise AssertionError("build가 실패했는데 save까지 왔다")


def _all_builds_fail(tmp_path, monkeypatch, boom=RuntimeError("donor exploded")):
    """모든 build_graph 가 실패하는 상황을 만든다. PowerPoint는 건드리지 않는다."""
    from contextlib import contextmanager

    @contextmanager
    def fake_session(show=False):
        yield _FakeOp()

    def fake_build(op, spec, style_mode="house"):
        raise boom

    monkeypatch.setattr(paste, "origin_session", fake_session)
    monkeypatch.setattr(paste, "build_graph", fake_build)
    # 여기까지 오면 계약 위반이다 — 넣을 게 없는데 PowerPoint를 띄우면 안 된다.
    monkeypatch.setattr(paste, "dispatch_powerpoint",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("빌드가 전멸했는데 PowerPoint를 띄웠다")))

    recipe = tmp_path / "one.yaml"
    recipe.write_text(
        RECIPE_1.format(csv=(FIX / "water_solubility_greek.csv").as_posix()),
        encoding="utf-8",
    )
    return recipe


def test_run_recipe_raises_when_every_graph_fails(tmp_path, monkeypatch):
    """실패해야 정상: 빈 덱을 써 놓고 성공한 척하면 호출자가 구분할 수 없다."""
    recipe = _all_builds_fail(tmp_path, monkeypatch)
    out = tmp_path / "out"
    with pytest.raises(NoGraphsError, match="0/1"):
        run_recipe(recipe, out)
    assert not (out / "only_one.pptx").exists(), "실패했는데 덱을 썼다"


def test_run_recipe_reports_why_it_failed(tmp_path, monkeypatch):
    recipe = _all_builds_fail(tmp_path, monkeypatch)
    with pytest.raises(NoGraphsError, match="donor exploded"):
        run_recipe(recipe, tmp_path / "out")


def test_main_exits_nonzero_when_nothing_was_built(tmp_path, monkeypatch):
    """종료 코드가 0이면 스크립트를 부른 쪽이 실패를 알 수 없다."""
    recipe = _all_builds_fail(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["paste.py", str(recipe), "-o", str(tmp_path / "out")])
    assert paste.main() == 1


def test_main_exits_zero_on_success(tmp_path, monkeypatch):
    """반대편도 확인한다 — 항상 1을 돌려주는 구현이면 위 테스트는 무의미하다."""
    made = tmp_path / "fine.pptx"
    monkeypatch.setattr(paste, "run_recipe", lambda r, o: made)
    monkeypatch.setattr(sys, "argv", ["paste.py", "r.yaml", "-o", str(tmp_path)])
    assert paste.main() == 0
