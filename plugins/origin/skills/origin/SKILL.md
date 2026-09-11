---
name: origin
description: 정리된 csv/xlsx 데이터로 OriginLab(Origin 2021) 그래프를 만들고, 논문급 house style(축제목 32pt / 눈금라벨 24pt 볼드 / 축두께 4 / tick In)을 강제 적용해 PNG·.opju로 내보내며 PowerPoint에 편집 가능한 OLE 객체로 붙이는 워크플로를 다룬다. 스타일은 기존 논문 덱에서 복원한 donor .opj 9종(bar_labeled, bar_grouped, double_y, broken_axis, log_axis, waterfall, line_symbol, errorbar, annotated)과 새로 저작한 floating_bar(범위 막대 — 전기화학 안정성 윈도우 등)에서 상속하고, donor는 데이터 형태로 자동 추론한다. 트리거 - "Origin 그래프 만들어줘", "이 데이터로 그래프 그려줘", "논문 figure 만들어줘", "오리진으로 플롯", "그래프 PPT로 붙여줘", .opj/.opju 파일 언급, Origin/OriginLab/originpro 언급. 쓰지 않을 때 - 사용자가 matplotlib·plotly·seaborn·Excel 차트 등 다른 도구를 명시한 경우, 웹/인터랙티브 차트가 목적인 경우, Origin이 설치되지 않은 환경.
---

# /origin — 데이터 → Origin 그래프 → PPT OLE

기존 논문 덱(`Origin graph list.pptx`)에 임베드돼 있던 Origin 그래프 35개를 `.opj`로 복원해
**donor(공여체)** 로 쓴다. donor를 열어 **워크시트 데이터만 갈아끼우면 그래프 스타일이
그대로 따라온다.** 그 위에 house style을 강제 적용한다.

이 설계는 취향이 아니라 관측의 결과다. Origin의 템플릿 저장(`template_saveas`), 테마 저장
(`theme_save`), `save -t`, `save -i` 는 **예외도 없이 파일을 만들지 않는다.** 스타일을
파일로 추출할 수 없으니, 프로젝트 안에 둔 채 상속하는 수밖에 없다.
(→ `references/labtalk_props.md` §4)

```
csv/xlsx  ──▶  레시피 검증  ──▶  donor .opj 개방  ──▶  워크시트 데이터 주입
                                                            │
   PPT (OLE) ◀── AddOLEObject(.opju) ◀── PNG/.opju ◀── house style + 축범위 + 장식
```

---

## 사전 조건 (하나라도 어기면 사고가 난다)

| 조건 | 이유 |
|---|---|
| **Origin 2021 설치** (`Origin64.exe`) | COM 자동화 대상 |
| **Origin이 실행 중이 아닐 것** | 단일 인스턴스라 사용자 작업 프로젝트를 덮어쓴다. 실행 중이면 `OriginBusyError` 로 착수를 거부한다 |
| **PowerPoint를 닫아 둘 것** | 단일 인스턴스라 사용자가 쓰던 PowerPoint에 붙는다. 우리가 띄운 경우에만 종료한다 |
| **병렬 실행 금지** | 같은 Origin 인스턴스를 다툰다 (클립보드는 더 이상 쓰지 않는다 — `AddOLEObject` 경로) |
| 파이썬 패키지 | `originpro`, `pandas`, `PyYAML`, `olefile`(복원용), `Pillow`+`numpy`(테스트용) |

플러그인으로 설치한 직후 파이썬 패키지를 한 번만 넣는다. Origin 2021 본체는 별도 설치이며
(`originpro` 는 Origin의 COM 서버에 붙는 얇은 래퍼일 뿐 Origin을 대신하지 않는다),
Origin이 없는 PC에서는 `recover.py`(pptx OLE → `.opj`) 외에는 아무것도 돌지 않는다.

```bash
pip install originpro pandas PyYAML olefile Pillow numpy
```

이 문서의 `references/` · `donors/` · `data/` · `tests/` 경로는 모두
`${CLAUDE_PLUGIN_ROOT}/skills/origin/` 기준이다. 테스트는 그 폴더에서
`pytest` 로 돌린다 (레시피의 `data:` 가 상대경로다).

---

## 사용법

### 1) 레시피(YAML)를 쓴다

```yaml
output: water_solubility
style: house
graphs:
  - id: solubility
    donor: bar_labeled
    data: C:/.../water_solubility.csv
    x: cyclodextrin
    y: solubility
    y_title: "g / 100 mL"
    y_range: auto

    title: "Water solubility (25 °C)"
    colors:
      base: "#808080"
      highlight:
        category: "β-CD"
        color: "#B22222"
    annotation:
      text: "lowest → asset\nonce crosslinked"
      at: "β-CD"
      color: "#B22222"
```

범위 막대(floating bar)를 쓰는 전체 예시는 `tests/fixtures/esw_window.yaml` 에 있다
(`y_low`/`y_high`, `subtitle`, `x_labels`, `bands`, `value_labels`, `colors.series`,
`annotation.at: top_center` 를 모두 쓴다).

### 2) 돌린다

레시피 → pptx 는 `paste.py` 가 끝까지 돌린다 (CLI 있음).

```bash
# 레시피 하나 → <out>/<output>.pptx (그래프마다 편집 가능한 OLE 객체)
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/paste.py path/to/recipe.yaml -o output_dir
```

파이프라인은 두 단계로 나뉘고, **클립보드를 경유하지 않는다.**

1. **Origin 세션 하나**로 그래프를 순서대로 빌드하고 **각각 독립된 `.opju`** 로
   저장한다 (`<out>/_<output>_projects/<id>.opju`). `build_graph` 가 매번 donor를
   `op.open` 해 현재 프로젝트를 통째로 교체하므로, 저장본에는 그 그래프 하나만 담긴다.
   저장은 `op.save()` **반환값과 파일 존재를 모두** 확인한다 — 목적지를 먼저 지우므로
   이전 실행의 잔재가 새 덱에 섞이지 않는다.
2. Origin을 닫은 뒤 PowerPoint에서 `Shapes.AddOLEObject(FileName=..., Link=0)` 로
   임베드하고, `layout` 격자에 비율을 유지한 채 배치한 다음 `SaveAs` 한다.
   그러고 나서 임베드가 띄운 **창 없는 Origin OLE 서버만** 골라 거둔다
   (`reap_origin_servers`, 창이 있는 프로세스는 사용자 것이므로 건드리지 않는다).
   덱은 이미 저장된 뒤라 임베드는 멀쩡하다.

**부분 실패는 실행을 멈추지 않는다.** 그래프 하나가 실패하면 이유를 모아 두고 다음
그래프로 넘어가며, 끝에 `n/total` 로 보고한다. 하나도 못 넣었을 때만
`NoGraphsError` 로 죽고 **덱을 쓰지 않는다** (빈 덱을 성공으로 넘기면 호출자가
성공과 실패를 구분할 수 없다). 종료 코드는 실패 시 `1`.

Origin COM 세션은 그래프 수에 따라 몇 분씩 조용히 돈다. 그동안 아무 말이 없으면 사용자는
멈춘 것인지 도는 것인지 구분할 수 없으므로, 착수 한 줄·중간 갱신·마지막 요약을 낸다
(추론된 donor 보고와 `n/total` 결과가 이 요약에 들어간다):

```text
Before you start, say in a line what you're about to do; brief updates while you work help the user follow along. Close with a short recap that stands on its own — what you found, what you did, and what's next — so a reader who only sees the last message has the full picture.
```

```bash
# 레시피 하나 → PNG (tests/_acceptance/<output>.png)
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/_acceptance.py path/to/recipe.yaml
```

```python
import sys
from pathlib import Path
sys.path.insert(0, r"${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts")

from build import build_graph, load_recipe
from originsession import origin_session

recipe = load_recipe("recipe.yaml")          # 여기서 전부 검증된다 (그래프 만들기 전)
with origin_session() as op:                 # Origin 실행 중이면 여기서 거부
    for spec in recipe["graphs"]:
        if spec.get("donor_inferred"):
            print(f"[추론] {spec['id']}: donor={spec['donor']}")   # ← 반드시 사용자에게 보고
        page = build_graph(op, spec, style_mode=recipe["style"])
        gp = op.find_graph(page)

        out = Path(f"{recipe['output']}.png").resolve()
        if not gp.save_fig(str(out).replace("\\", "/"), width=1000) or not out.exists():
            raise RuntimeError("save_fig produced nothing")

        # PPT에 편집 가능한 OLE로 붙이는 것은 paste.py 가 한다:
        #   op.save(<개별 .opju>)  →  Origin 종료  →
        #   slide.Shapes.AddOLEObject(FileName=<.opju>, Link=0)
        # 클립보드를 경유하지 않는다 (copy_page('OLE') 는 이 환경에서 무반응).
```

`load_recipe()` 는 **그래프를 하나도 만들기 전에** 다음을 전부 검증한다.
잘못된 레시피는 Origin을 띄우기도 전에 죽는다.

* `style` 이 `house`/`inherit` 인가
* `donor` 이름이 실재하는가 (없으면 사용 가능한 목록을 예외 메시지에 담아 준다)
* `x` / `y` 컬럼이 데이터 파일에 있는가
* `colors.highlight.category` / `annotation.at` 이 실제 x 값에 있는가

---

## 레시피 스키마 (전체)

`build.py` / `decorate.py` 가 **실제로 읽는 필드만** 적었다. 여기 없는 키는 무시된다.

### 최상위

| 필드 | 타입 | 필수 | 읽는 곳 | 뜻 |
|---|---|:--:|---|---|
| `output` | str | 러너에서 필수 | `paste.run_recipe`, `_acceptance*.py` | 출력 파일 basename (`<output>.pptx`). **`load_recipe`/`build_graph` 는 읽지 않는다** |
| `style` | `house` \| `inherit` | 아니오 (기본 `house`) | `load_recipe` → `build_graph(style_mode=)` | 아래 참조. 다른 값이면 `ValueError` |
| `graphs` | list | **예** | `load_recipe` | 그래프 스펙 목록 |
| `layout.cols` | int | 아니오 (기본 `4`) | `paste.run_recipe` | 덱 격자의 열 개수. `1` 미만이면 `ValueError` |
| `layout.gap_in` | float | 아니오 (기본 `0.15`) | `paste.run_recipe` | 격자 칸 사이 여백(인치) |

* `style: house` — donor 스타일 위에 house 표준값을 **덮어쓴다** (기본값).
* `style: inherit` — **donor를 픽셀 그대로.** 요청하지 않은 것은 하나도 건드리지 않는다.
  (단 `colors` 를 주면 이 약속이 깨진다 — 아래 참조)

> `layout` 은 **덱 조립(`paste.py`)에서만** 쓰인다. 그래프 하나만 만드는 경로
> (`build_graph`)는 읽지 않는다. 격자는 줄바꿈만 하고 **페이지는 나누지 않으므로**,
> 슬라이드 아래로 넘어가는 그래프가 생기면 `paste.py` 가 경고를 찍는다
> (기본 셀 3.0×2.1in + `cols: 4` 기준 13번째부터).

### `graphs[]` 항목

| 필드 | 타입 | 필수 | 뜻 |
|---|---|:--:|---|
| `id` | str | 러너에서 필수 | 로그·에러 메시지용 식별자이자 **중간 `.opju` 파일 이름**. 레시피 안에서 **유일**해야 한다 (중복이면 `ValueError`). `build_graph` 는 읽지 않는다 |
| `donor` | str | 아니오 | 아키타입 이름(파일 stem). **생략하면 데이터로 추론**하고 `donor_inferred: true` 를 스펙에 심는다 |
| `data` | str | **예** | `file.csv` / `file.xlsx` / `file.xlsx#Sheet1` (`#` 뒤는 시트명) |
| `x` | str | **예** | x축 컬럼명 |
| `y` | str \| list[str] | `y_low`/`y_high` 를 안 쓰면 **예** | y축 컬럼명. 리스트면 다중 계열 |
| `y_low` / `y_high` | str | 범위 막대를 그릴 때 **둘 다** | 막대의 아래끝/위끝 컬럼. **`y` 와 상호배타** — 섞으면 `ValueError` |
| `y_title` | str | 아니오 | 좌측 y축 제목 (`YL`) |
| `x_title` | str | 아니오 | 하단 x축 제목 (`XB`) |
| `y_range` | `auto` \| `inherit` \| `[lo, hi]` | 아니오 (기본 `auto`) | `auto` = 데이터로 재계산 / `inherit` = donor 범위 유지 / 리스트 = 고정. **그 외 값은 `ValueError`** |
| `title` | str | 아니오 | 플롯 영역 위 가운데 그래프 제목 (볼드, `axis_title_pt`) |
| `subtitle` | str | 아니오 | **범위 막대 전용.** 제목 **바로 아래** 작은 줄 (제목의 65% 크기). `title` 이 한 칸 위로 올라간다 |
| `x_labels` | map | 아니오 | **범위 막대 전용.** `{범주: "두 줄\n라벨"}`. 눈금 라벨 텍스트를 치환한다 |
| `bands` | list | 아니오 | **범위 막대 전용.** 가로 음영 밴드. 아래 |
| `value_labels` | map | 아니오 | **범위 막대 전용.** 막대 위/아래 값 라벨. 아래 |
| `colors` | map | 아니오 | 아래 (`colors.series` 만 범위 막대 전용) |
| `annotation` | map | 아니오 | 아래 |

> **"범위 막대 전용"은 문서상의 권고가 아니라 강제다.** 이 필드들을 그리는 코드는
> floating 경로(`y_low`/`y_high`)에만 있다. 일반 donor에 적으면 `load_recipe` 가
> `ValueError` 로 **거부한다** — 검증만 통과시키고 렌더에서 조용히 사라지는 것이
> 가장 나쁘기 때문이다. 일반 donor에서 쓸 수 있는 것은 `title` / `colors`(`series` 제외) /
> `annotation` 이다.

`colors`:

| 필드 | 타입 | 뜻 |
|---|---|---|
| `base` | `"#RRGGBB"` | 첫 번째 plot 전체 색 |
| `highlight.category` | str | 강조할 **x 범주 이름**. 데이터에 없으면 즉시 `ValueError` |
| `highlight.color` | `"#RRGGBB"` | 강조 색 |
| `series` | `{범주: {line, fill}}` | **범위 막대 전용.** 계열별 테두리(`line`)·채움(`fill`) 색. 없는 범주면 즉시 `ValueError` |

`annotation`:

| 필드 | 타입 | 뜻 |
|---|---|---|
| `text` | str | 주석 문구 (`\n` 로 줄바꿈) |
| `at` | str | 가리킬 **x 범주 이름**, 또는 위치 키워드 `top_center` / `top_left` / `top_right`. 둘 다 아니면 즉시 `ValueError` |
| `color` | `"#RRGGBB"` | 선택. 텍스트와 화살표에 함께 적용 |

범주를 주면 지금까지처럼 화살표가 달린 주석이 되고, **위치 키워드를 주면 화살표 없이
플롯 안쪽 상단에** 놓인다.

`bands[]` (가로 음영):

| 필드 | 타입 | 뜻 |
|---|---|---|
| `from` / `to` | float | 밴드의 y 구간. **`from < to` 가 아니면 즉시 `ValueError`** |
| `fill` | `"#RRGGBB"` | 음영 색 (테두리도 같은 색) |
| `alpha` | 0~1 | **불투명도.** Origin의 `transparency` 와 반대라 내부에서 뒤집는다 |
| `label` | str | 선택. 플롯 **바깥**에 놓이는 설명 (`\n` 로 줄바꿈) |
| `label_side` | `right` \| `left` | 기본 `right`. 그 밖의 값은 `ValueError` |
| `label_color` | `"#RRGGBB"` | 선택 |

밴드는 **막대 위에 겹쳐** 그린다 — 반투명이 의미를 가지려면 그래야 한다.

`value_labels` (막대 끝 라벨):

| 필드 | 타입 | 뜻 |
|---|---|---|
| `top.source` / `bottom.source` | str | 찍을 값이 들어 있는 **컬럼명**. 없으면 즉시 `ValueError` |
| `top.format` / `bottom.format` | str | 예: `"Eox {v:.2f} V"`. **`{v}` 를 참조하지 않으면 `ValueError`** |

라벨 색은 `colors.series[범주].line` 을 따라간다.

### 스키마에 관해 반드시 알아야 할 것

* **`y_range` 는 화이트리스트로 검증된다.** `auto` / `inherit` / 2원소 숫자 리스트만
  받는다. `atuo` 같은 오타는 `load_recipe` 에서 `ValueError` 다.
* **`y_range` 가 데이터를 자르면 경고한다.** `inherit` 이나 고정 리스트가 데이터를
  범위 밖으로 밀어내면 `AxisClipWarning` 이 뜬다 (그래프는 만들어진다).
* **막대 축은 0을 앵커로 잡는다.** 데이터가 전부 한쪽 부호여도 축이 0을 문다 —
  안 그러면 막대 길이가 크기를 나타내지 못한다. 범위 막대(`y_low`/`y_high`)는
  바닥이 0이 아니므로 이 앵커를 쓰지 않는다.
* **빈 셀(NaN)은 라벨을 건너뛴다.** 축 계산에서도 빠진다. 그래프는 정상적으로 나온다.
* **`colors` 는 `inherit` 의 픽셀 동일성을 깬다.** 색을 지정하면 점별 스타일 홀더를
  삭제하고 값 라벨을 직접 그린다 (그렇게 안 하면 색 지정 자체가 안 먹는다).
* **값 라벨은 첫 번째 y 컬럼에만** 붙고, donor가 점별 라벨을 갖고 있을 때만 그려진다
  (현재 `bar_labeled` 만 해당).
* **`y_title` 은 워크시트 2번째 컬럼(y 첫 계열)의 Long Name을 갈아끼우는 방식**으로
  들어간다 (donor 제목이 `%(?Y)` 치환 토큰일 때). 다중 y에서 두 번째 이후 계열 이름은
  건드리지 않는다.
* **범주 매칭은 문자열 그대로**다. `beta-CD` 와 `β-CD` 는 다른 것이다. 데이터 파일에
  적힌 표기를 그대로 쓴다 (그리스 문자는 Origin까지 살아서 간다 — 검증됨).

---

## donor 아키타입 10종

9종은 실제 논문 덱에서 복원·큐레이션한 것이고 서로 다른 원본에서 왔다
(`curated_from` 으로 고정, `tests/test_donors.py` 가 중복을 막는다).
**`floating_bar` 만 예외로 새로 저작했다** — 원본 덱 35개에 범위 막대가 없었다.

| donor | 실물 | 레이어 | 축 | 언제 쓰나 |
|---|---|:--:|---|---|
| `bar_labeled` | 막대 + **막대 위 값 라벨** | 1 | linear | 범주 3~5개 비교. **유일하게 실전 검증된 donor** |
| `bar_grouped` | 그룹 막대 | 1 | linear | 범주 × 여러 계열 (DFT vs MD 등) |
| `double_y` | 좌우 y축 2개 | **2** | linear | 단위가 다른 두 물리량을 겹칠 때 |
| `broken_axis` | y축 절단 | **2** | linear | 값 차이가 커서 한 축에 못 담을 때 |
| `log_axis` | x축 log10 | 1 | **x: log** | 주파수·농도 등 수 자릿수 스윕 (EIS 등) |
| `waterfall` | 다중 스펙트럼 적층 | 1 | **x 역방향** (4000→600) | FTIR/Raman 스펙트럼 겹쳐 보기 |
| `line_symbol` | 선 + 심볼 | 1 | linear | 일반적인 x-y 추이 |
| `errorbar` | 오차막대 | **2** | linear | 반복 측정 평균 ± 편차 |
| `annotated` | 주석·가이드가 얹힌 플롯 | 1 | linear | 영역 표시·설명 텍스트가 필요한 그림 |
| `floating_bar` | **범위 막대** (0에서 시작하지 않는 뜬 막대) | 1 | linear | 전기화학 안정성 윈도우, 밴드갭 정렬, 온도 구간 등 "구간"을 그릴 때. **저작본** |

각 donor의 실측 스타일 수치는 `donors/<name>.yaml` 에 있다 (감사·override용 기록이며,
house style이 덮어쓰므로 **결과 스타일과 같지 않다**). 예외로 `floating_bar` 는
저작하면서 house style을 구워 넣었다 — 물려받을 원본 그림이 없으므로 이 donor의 고유
스타일이 곧 house style이어야 `style: inherit` 도 말이 된다.

### `floating_bar` — 어떻게 만들었나

Origin 내장 템플릿 **`FloatCol.otp`** 을 열고 `plotxy ... plot:=230` 로 그린 진짜
floating column이다 (렌더로 확인). 데이터는 이렇게 펼친다:

```
molecule | lo_1  hi_1 | lo_2  hi_2      ← 범주마다 (아래,위) 컬럼 쌍 하나
M1       | -1.25 5.55 | NaN   NaN
M2       | NaN   NaN  | -0.58 5.61
```

Origin은 **Y 컬럼을 앞에서부터 둘씩 묶어 막대 하나**로 그린다. 범주마다 쌍을 나누고
자기 행 외에는 `NaN`을 넣으면 막대마다 plot이 분리돼 **계열별 색**을 줄 수 있다
(점별 색 지정 경로는 Origin에서 전부 죽어 있다 → `labtalk_props.md` §7).

`colors.series[..].line`(테두리)만은 plot 속성으로 지정할 수 없다 — **막대의 테두리
색 속성이 Origin에 없다.** 그래서 막대와 같은 자리·같은 크기의 `Rect` 오브젝트를
겹쳐 그린다 (폭 = 범주 간격의 0.8배, 실측 상수 `decorate.BAR_WIDTH`).
자세한 근거는 `references/labtalk_props.md` §12.

재저작:

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/_author_floating_bar.py     # donors/floating_bar.opj + .yaml
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/_acceptance_esw.py          # 인수 산출물 PNG + .opju
```

---

## donor 자동 추론

`donor` 를 생략하면 데이터 형태로 고른다. 판정 순서가 곧 우선순위다:

0. `y_low` / `y_high` 를 썼으면 → **`floating_bar`** (`build.is_floating`)
1. y 컬럼명이 `_err` / `_sd` / `_std` 로 끝나는 것이 하나라도 있으면 → **`errorbar`**
2. x가 **숫자가 아니면** → y가 2개 이상이면 **`bar_grouped`**, 1개면 **`bar_labeled`**
3. x의 양수값이 2개 이상이고 `max/min ≥ 1000` 이면 → **`log_axis`**
4. 그 외 → **`line_symbol`**

> x가 범주형인지 판정할 때 `dtype == object` 로 보면 안 된다. **pandas 3부터 문자열 컬럼은
> `StringDtype`** 이라 범주형 x를 통째로 놓친다. `pd.api.types.is_numeric_dtype()` 이 정본이다.

### 원칙: 추론 결과는 **항상 사용자에게 보고한다**

추론은 편의지 권위가 아니다. `load_recipe` 는 추론했을 때 스펙에 `donor_inferred: true` 를
심는다. 그래프를 그리기 **전에** 어떤 아키타입을 골랐는지 사용자에게 말하고,
의도와 다르면 레시피에 `donor:` 를 명시하게 한다.

```python
if spec.get("donor_inferred"):
    print(f"[추론] {spec['id']}: donor={spec['donor']}")
```

추론이 도달할 수 있는 donor는 **6종**이다 (`bar_labeled`, `bar_grouped`, `log_axis`,
`line_symbol`, `errorbar`, `floating_bar`). `double_y` / `broken_axis` / `waterfall` /
`annotated` 는 **반드시 명시**해야 쓸 수 있다.

---

## house style — 무엇을 덮어쓰고, 무엇을 대가로 치르는가

`data/house_style.yaml`:

| 항목 | 값 | 적용 경로 |
|---|---|---|
| 축 제목 | **32 pt** | `XB/YL/YR.fsize` (텍스트가 있는 제목만) |
| 눈금 라벨 | **24 pt, 볼드** | `layer.<ax>.label.pt`, `layer.<ax>.label.bold` |
| 축선 두께 | **4** | `layer.<ax>.thickness` |
| 눈금 방향 | **In** (비트마스크 `5`) | `layer.<ax>.ticks` |

**대가**: donor의 실측 최빈값은 축제목 28 / 눈금라벨 24 / 두께 3 이다. house style을
적용하면 **같은 논문의 기존 figure와 폰트·두께가 달라진다.** 새로 만드는 그림들끼리는
통일되지만, 예전 그림 옆에 나란히 놓으면 눈에 띈다.

**탈출구**: `style: inherit`. donor 스타일을 그대로 쓰고 house 값을 적용하지 않는다.
기존 figure와 섞어 써야 하는 상황이면 이쪽을 고른다.

house style이 실제로 앉았는지는 **픽셀 비교가 아니라 속성 재측정**으로 확인한다
(`op.lt_float("layer.x.thickness") == 4.0` 식). 픽셀 비교는 `inherit` 골든 전용이다.

산출 PNG를 눈으로 검수할 때(축 라벨·눈금 숫자·범례·값 라벨이 겹치거나 잘리지 않았는지)는
축소된 전체 이미지 한 장으로 판정하지 마라. **필요하면 PIL로 해당 영역을 잘라 확대해서 다시 봐라** —
납득될 때까지 잘라 보는 것을 반복해도 된다. 1000 px 폭 산출물에서 24 pt 눈금 라벨은
전체 뷰로는 판독되지 않는다.

---

## donor 라이브러리 재구축

donor를 새 덱에서 다시 만들거나 아키타입을 추가할 때. `donors/_unused/` 는 중간산물이고
`.gitignore` 되어 있다 — 플러그인 배포판에는 들어 있지 않으며 언제든 재생성한다.

```bash
# 1) pptx의 OLE 임베드에서 .opj 전수 복원 (Origin 불필요)
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/recover.py "C:/.../Origin graph list.pptx" -o donors/_unused

# 2) 각 .opj의 스타일 수치를 manifest YAML로 판독 (Origin 필요, 세션 1개 재사용)
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/survey.py donors/_unused -o donors/_unused

# 3) 눈으로 고르기 위한 PNG 미리보기 (Origin 필요)
python ${CLAUDE_PLUGIN_ROOT}/skills/origin/scripts/_render_all.py        # → donors/_unused/_preview/*.png
```

**4) 수동 큐레이션** — 자동화하지 않는다. 미리보기를 보고 9종을 고른 뒤:

* `donors/_unused/oleObjectNN.opj` → `donors/<archetype>.opj` 로 복사
* `donors/_unused/oleObjectNN.yaml` → `donors/<archetype>.yaml` 로 복사하고
  **`archetype: <이름>` 과 `curated_from: oleObjectNN.bin` 두 키를 추가**
  (`tests/test_donors.py` 가 provenance 없는 manifest를 거부한다)

`tests/test_donors.py` 는 이름과 실물이 맞는지도 검사한다 (`double_y`/`broken_axis` 는
`page.nLayers == 2`, `log_axis` 는 `layer.x.type == 2`). 라벨만 바꿔 붙이는 실수를 막는다.

**원본에 없는 아키타입을 새로 저작할 때** (`floating_bar` 가 첫 사례):

* 저작 스크립트를 `scripts/_author_<archetype>.py` 로 남긴다 — 손으로 만든 donor는
  다시 만들 수 없으면 유지보수가 불가능하다.
* manifest의 `curated_from` 은 **`authored:<archetype>`** 으로 쓴다. 그냥 `authored` 로
  쓰면 두 번째 저작 donor가 생기는 순간 중복 판정이 나서 중복 검사가 무력화된다.
* `ARCHETYPES` 목록에 이름을 추가한다.

---

## 알려진 한계

* **`gp.copy_page('OLE')` 는 이 환경에서 아무것도 하지 않는다.** 클립보드에 올라오는
  포맷이 0개라 `PasteSpecial(ppPasteOLEObject)` 이 "data type unavailable" 로 실패한다
  (반증 실험으로 확정). 그래서 `paste.py` 는 그래프마다 개별 `.opju` 로 저장한 뒤
  `slide.Shapes.AddOLEObject(FileName=...)` 로 임베드한다 — 클립보드를 안 쓴다.
* **`AddOLEObject` 는 임베드마다 창 없는 `Origin64.exe` 를 띄운다.** 그 프로세스가
  소스 `.opju` 를 붙들고 있어 중간산물이 지워지지 않고, 더 나쁘게는 `origin_session`
  의 "Origin이 이미 실행 중" 가드가 **다음 실행부터** 발동한다. `paste.py` 가
  덱 저장 후 **"새로 생긴 PID" ∩ "주 창이 없는 프로세스"** 만 골라 강제 종료한다
  (`reap_origin_servers`). 조립 중에 사용자가 Origin을 열면 그것도 새 PID이므로
  창 유무로 가른다. 창을 판정하지 못하면 **아무도 죽이지 않는다** — 남은 프로세스는
  되돌릴 수 있지만 사용자의 미저장 작업은 되돌릴 수 없다.
  덱은 이미 저장된 뒤라 임베드는 멀쩡하다.
* **10종 중 `bar_labeled` / `floating_bar` / `bar_grouped` 만 실전 검증됐다.**
  (`log_axis` / `errorbar` 는 아래 항목대로 빌드 불가.) 나머지는
  파일·manifest·구조 검사만 통과한 상태다. 데이터 주입까지 돌려 본 적이 없다.
* **`floating_bar` 의 막대 폭 `0.8` 은 실측 상수다.** LabTalk으로 읽을 수 없어
  (`layer.gap` 등 전부 nan) 렌더 픽셀에서 재 확정했다. donor를 다른 gap으로 다시
  저작하면 테두리 사각형이 막대와 어긋난다 — donor를 손대면 렌더로 재확인할 것.
* **`floating_bar` 의 막대 테두리는 plot이 아니라 Rect 오브젝트다.** 그래서 Origin에서
  데이터를 손으로 고치면 채움(=plot)은 따라오지만 테두리 사각형은 제자리에 남는다
  (값 라벨과 같은 성질).
* **`bands` 는 막대 위에 겹쳐 그린다.** 밴드 색이 불투명(`alpha: 1`)이면 막대를 가린다.
* **`log_axis` / `errorbar` 로는 빌드할 수 없다 — 워크시트가 없다.** 북 이름 후보가
  부족한 게 아니라 워크북이 통째로 없다 (실측 2026-07-29: `op.pages('w')` 가 비어
  있고 그래프 페이지 하나뿐이다. 원본 덱의 OLE에 Origin이 그래프만 임베드했고, 플롯이
  참조하던 데이터셋 자체가 프로젝트에 없다). manifest에 `has_worksheet: false` 로
  기록했다. **레시피에 명시하면** `load_recipe` 가 Origin을 띄우기 전에 `ValueError`
  로 막고, **추론이 골랐으면** 그 그래프만 `build_graph` 에서 실패시키고 나머지 그래프는
  계속 만든다 (우리가 고른 donor 때문에 사용자의 멀쩡한 그래프까지 잃을 수는 없다).
  되살리려면 donor를 다시 저작하는 수밖에 없다.
  → 자동 추론이 이 둘을 고르는 입력(로그 스케일 x, `_err` 컬럼)은 현재 막다른 길이다.
* **`colors` 를 지정하지 않으면 막대 위에 약 2px 잔점이 남는다.** 상속된 값 라벨을
  완전히 지우지 못하고 `fsize=0.5` 로 축소만 하기 때문 (0.1 이하는 Origin이 무시하고
  기본 크기로 되돌린다). `colors.base` 하나만 줘도 홀더가 삭제되면서 사라진다.
* **다중 레이어 donor의 2번째 레이어는 house style을 못 받는다.** `layer.*` 는 활성
  레이어 하나에만 걸린다 (`double_y`, `broken_axis`, `errorbar` 해당).
* **일반 donor 경로는 x축 범위를 자동 재계산하지 않는다.** 범주 개수가 donor와 다르면
  x축이 어긋난다 (`bar_labeled` donor는 3범주 기준). **범위 막대 경로는 재계산한다**
  (`build.category_x_range` → `0.5 ~ N+0.5`).
* **덱 격자는 페이지를 나누지 않는다.** 슬라이드 높이를 넘으면 그래프가 캔버스 밖으로
  나가고, `paste.py` 는 경고만 찍는다 (기본 셀 + `cols: 4` 기준 13번째부터).
  그래프가 많으면 `layout.cols` 를 늘리거나 레시피를 나눠라.
* **`_acceptance*.py` 는 일회성 러너지 제품 진입점이 아니다.** 레시피 → pptx 의
  진입점은 `scripts/paste.py` 다 (PNG만 필요하면 `_acceptance.py`).

---

## 절대 규칙

* **git 명령을 절대 실행하지 마라.** 커밋은 사람이 한다.
* **`tests/test_build_golden.py::test_golden_inherit_matches_donor` 를 깨뜨리지 마라.**
  이 테스트는 "`inherit` = donor 그대로"라는 계약을 지킨다. 깨졌다면 골든 이미지를
  갱신하지 말고 계약을 깬 쪽을 고쳐라 (→ `references/troubleshooting.md` §7).
* **요청하지 않은 것은 건드리지 않는다.** `title`/`colors`/`annotation` 이 없으면
  donor 상속 경로가 그대로 남아야 한다.
* **고칠 때는 고칠 곳만 고친다.** 이미 있는 `.opju`·레시피·`scripts/*.py` 를 손볼 일이 생기면
  전체를 다시 만들거나 파일을 새로 써서 덮지 말고, 문제의 레이어·축·필드·함수만 건드린다.
  통짜 재생성은 손으로 맞춰 둔 축범위·주석 위치·저작 donor의 실측 상수를 조용히 날린다.

  ```text
  The number of tokens used to edit files is best minimized, all else being equal. Therefore, when it will not affect the end result, try to surgically edit a file rather than rewrite the entire thing.
  ```
* **Origin에 넘기는 모든 경로는 절대 경로.** 상대 경로는 예외 없이 조용히 실패한다.

---

## 레퍼런스

* **`references/labtalk_props.md`** — 검증된 LabTalk 속성 사전. 눈금 비트마스크,
  읽고/쓸 수 있는 속성 표, **해결되지 않는 이름 목록**(전부 `nan`), 동작하지 않는
  X-Function, 점별 색 실패 경로와 우회, 값 라벨 홀더의 정체. **새 속성을 쓰기 전에 여기부터
  본다. 여기 없는 이름은 "동작함"이 아니라 "확인 안 됨"이다.**
* **`references/troubleshooting.md`** — 실제로 겪은 함정만 증상 → 원인 → 대응으로.
  `OriginBusyError`, `Origin64.exe` 이름 함정, 좀비 프로세스 정리, `op.exit()` 0x800706BE →
  다음 세션 RPC 사망, 상대 경로의 침묵 실패, 클립보드 경합, 축 잘림, 골든 이미지 드리프트,
  2px 잔점.

### 파일 지도

| 경로 | 역할 |
|---|---|
| `scripts/recover.py` | pptx OLE → `.opj` 복원 (**Origin 불필요**, CLI 있음) |
| `scripts/survey.py` | `.opj` → 스타일 manifest YAML (CLI 있음) |
| `scripts/originsession.py` | COM 세션 가드 — 선점 확인 + 확실한 종료 + 죽은 핸들 정리 |
| `scripts/build.py` | 레시피 검증 · donor 추론 · 데이터 주입 · 그래프 조립 |
| `scripts/paste.py` | 레시피 → pptx (**진입점**, CLI 있음) — 개별 `.opju` 저장 → OLE 임베드 → 격자 배치 → OLE 서버 회수 |
| `scripts/style.py` | house style 적용 + 축 범위 재계산 |
| `scripts/decorate.py` | title / subtitle / colors / bands / annotation / 값 라벨 직접 렌더 |
| `scripts/_author_floating_bar.py` | `floating_bar` donor 저작 (**donor를 만드는 유일한 코드**) |
| `scripts/_acceptance*.py`, `_prove_roundtrip.py`, `_render_all.py` | 일회성 검증 러너 (제품 진입점 아님) |
| `data/house_style.yaml` | 표준 스타일 수치 + 눈금 비트마스크 |
| `donors/*.opj` + `*.yaml` | 아키타입 10종과 실측 manifest |
| `tests/` | 207 passed (Origin/PowerPoint가 필요한 것은 `@pytest.mark.origin` / `@pytest.mark.powerpoint`) |
