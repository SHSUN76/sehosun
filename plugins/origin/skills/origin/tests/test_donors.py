from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DONORS = ROOT / "donors"

ARCHETYPES = [
    "bar_labeled", "bar_grouped", "double_y", "broken_axis",
    "log_axis", "waterfall", "line_symbol", "errorbar", "annotated",
    # 원본 덱에 없어 새로 저작한 아키타입. provenance는 `authored:<이름>` 이다.
    "floating_bar",
]


@pytest.mark.parametrize("name", ARCHETYPES)
def test_donor_pair_exists(name):
    assert (DONORS / f"{name}.opj").exists(), f"{name}.opj missing"
    assert (DONORS / f"{name}.yaml").exists(), f"{name}.yaml missing"


@pytest.mark.parametrize("name", ARCHETYPES)
def test_donor_manifest_is_valid(name):
    m = yaml.safe_load((DONORS / f"{name}.yaml").read_text(encoding="utf-8"))
    assert m["graph"]
    assert "layer.x.label.pt" in m["measured"]


def test_double_y_really_has_two_layers():
    """아키타입 이름이 실물과 맞는지 — 라벨만 붙이고 엉뚱한 donor를 넣는 실수를 잡는다."""
    m = yaml.safe_load((DONORS / "double_y.yaml").read_text(encoding="utf-8"))
    assert m["measured"]["page.nLayers"] == 2.0


def test_broken_axis_really_has_two_layers():
    m = yaml.safe_load((DONORS / "broken_axis.yaml").read_text(encoding="utf-8"))
    assert m["measured"]["page.nLayers"] == 2.0


def test_log_axis_really_is_log():
    m = yaml.safe_load((DONORS / "log_axis.yaml").read_text(encoding="utf-8"))
    assert m["measured"]["layer.x.type"] == 2.0


def test_bar_labeled_is_single_layer_linear():
    m = yaml.safe_load((DONORS / "bar_labeled.yaml").read_text(encoding="utf-8"))
    assert m["measured"]["page.nLayers"] == 1.0
    assert m["measured"]["layer.x.type"] == 1.0


def test_floating_bar_is_authored_not_recovered():
    """저작 donor는 provenance가 `authored:` 로 시작하고 아키타입 이름을 달고 있어야 한다.

    `authored` 하나로만 적으면 두 번째 저작 donor가 생기는 순간 중복 판정이 나서
    중복 검사가 무력화된다.
    """
    m = yaml.safe_load((DONORS / "floating_bar.yaml").read_text(encoding="utf-8"))
    assert m["curated_from"] == "authored:floating_bar"
    assert m["measured"]["page.nLayers"] == 1.0


def test_no_archetype_reuses_the_same_source():
    """아키타입은 서로 다른 원본에서 와야 한다 — 같은 걸 두 번 넣으면 커버리지 착시가 생긴다.

    `curated_from`(원본 oleObjectNN, 저작본은 `authored:<이름>`)으로 비교한다.
    파일명(`archetype`)으로 비교하면 구조적으로 항상 다르므로 아무것도 검증하지 못한다.
    """
    sources = {}
    for name in ARCHETYPES:
        m = yaml.safe_load((DONORS / f"{name}.yaml").read_text(encoding="utf-8"))
        assert m.get("curated_from"), f"{name}.yaml has no curated_from provenance"
        sources.setdefault(m["curated_from"], []).append(name)
    dupes = {s: n for s, n in sources.items() if len(n) > 1}
    assert not dupes, f"duplicate donor sources: {dupes}"


@pytest.mark.parametrize("name", ARCHETYPES)
def test_donor_data_shape_is_populated(name):
    """판독 실패를 잡는 가드.

    `unknown` 만 보던 시절엔 이 가드가 죽어 있었다 — 워크시트를 못 찾았을 때 실제로
    기록되는 값은 `none` 이라, log_axis / errorbar 두 donor가 그냥 빠져나갔다.
    이제 둘 다 실패로 본다. 단 `none` 이면서 `has_worksheet: false` 인 경우는
    "판독 실패"가 아니라 "워크시트가 정말 없다"는 확인된 사실이므로 허용한다
    (그 donor로 빌드를 시도하면 load_recipe 가 막는다 — test_injection.py 참조).
    """
    shape = yaml.safe_load((DONORS / f"{name}.yaml").read_text(encoding="utf-8"))["data_shape"]
    if shape["x_type"] == "none":
        assert shape.get("has_worksheet") is False, (
            f"{name}: data_shape read failed (x_type=none 인데 워크시트 없음이 아니다)")
        return
    assert shape["x_type"] not in ("unknown", "none"), \
        f"{name}: data_shape read failed (x_type={shape['x_type']})"
    assert shape.get("has_worksheet") is True
    assert shape["rows"] > 0 and shape["cols"] > 0


@pytest.mark.parametrize("name", ["bar_labeled", "bar_grouped", "floating_bar"])
def test_categorical_donors_are_recorded_as_categorical(name):
    """pandas 3에서 문자열 dtype은 object가 아니다.

    `df.dtypes.iloc[0] == object` 로 판정하던 시절 이 세 donor는 범주형인데
    numeric으로 기록돼 있었다 — donor 추론 규칙의 근거가 거짓이었다는 뜻이다.
    """
    m = yaml.safe_load((DONORS / f"{name}.yaml").read_text(encoding="utf-8"))
    assert m["data_shape"]["x_type"] == "categorical"
