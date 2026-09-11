# /origin 트러블슈팅

**실제로 겪은 것만** 적는다. 각 항목은 증상 → 원인 → 대응.
일반론이나 "혹시 모르니" 항목은 넣지 않는다.

---

## 1. `OriginBusyError: Origin is already running`

**증상** — 세션을 열자마자 예외. 그래프는 하나도 안 만들어진다.

**원인** — 의도된 거부다. Origin은 **단일 인스턴스**로 동작한다. 사용자가 Origin에서
작업 중인데 자동화가 끼어들면 열려 있는 프로젝트를 덮어쓸 수 있다.
`originsession.origin_session()` 이 착수 전에 `tasklist` 로 확인하고 막는다.

**대응** — Origin을 **닫고** 다시 실행한다. 우회하지 마라. 저장 안 한 사용자 작업이
날아가는 종류의 사고다.

### 1-1. 프로세스 이름 함정 (`Origin64.exe`)

**증상** — 가드가 영원히 발동하지 않는다. Origin이 떠 있는데도 자동화가 그대로 진입한다.

**원인** — Origin 2021 64-bit의 이미지 이름은 **`Origin64.exe`** 다.
`"Origin.exe"` 는 `"Origin64.exe"` 의 부분 문자열이 **아니므로**, `Origin.exe` 만 찾는
탐지기는 아무것도 못 잡는다. 이 모듈의 존재 이유가 통째로 무력화된다.

**대응** — `ORIGIN_IMAGES = ("Origin64.exe", "Origin.exe")` 로 **둘 다** 확인한다
(32-bit 설치본 대비). 그리고 세션 테스트는 반드시 **"세션이 살아 있는 동안 탐지기가
발동하는지"** 를 먼저 확인해야 한다 — 그 확인 없이 종료 후 부재만 보면
"원래부터 그런 이름의 프로세스가 없었다"와 구분되지 않는 **항진명제 테스트**가 된다
(`tests/test_session.py::test_session_opens_and_closes` 가 이 형태로 고정돼 있다).

---

## 2. 좀비 Origin 프로세스

**증상** — Origin을 분명히 닫았는데 `OriginBusyError`. 또는 세션이 끝났는데 다음 실행이
계속 막힌다.

**원인** — COM 종료가 깨져 숨겨진(`set_show(False)`) 인스턴스가 화면 없이 살아남았다.
숨김 실행이라 작업 표시줄에도 안 보인다.

**대응**

```powershell
tasklist /FI "IMAGENAME eq Origin64.exe"    # 살아 있는지 확인
taskkill /F /IM Origin64.exe                # 강제 종료
```

죽이기 전에 **사용자가 진짜로 Origin을 쓰고 있는 중은 아닌지** 확인할 것 —
숨김 인스턴스와 사용자 인스턴스는 이 명령으로 구분되지 않는다.

---

## 3. `op.exit()` 가 0x800706BE → **다음 세션이 죽는다**

**증상** — 첫 세션은 정상인데, 이어서 도는 두 번째 세션이
`RPC server unavailable` 로 터진다. 단발 실행에서는 절대 재현되지 않는다.

**원인** — `originpro` 의 APP 래퍼는 `self._app.Exit()` 가 **성공해야** `_app` 을 비운다.
종료가 COM 예외(관측값: `0x800706BE`)로 깨지면 **죽은 핸들이 모듈에 남는다.**
다음 세션은 Origin을 새로 띄우지 않고 그 시체 핸들을 재사용한다.

**대응** — `originsession._drop_stale_handle()` 이 처리한다:

```python
from originpro import config as cfg
if getattr(cfg, "oext", False) and getattr(cfg.po, "_app", None) is not None:
    cfg.po._app = None
```

`origin_session()` 은 이걸 **두 군데**서 부른다 — ① `finally` 에서 `op.exit()` 직후
(성공/실패 무관), ② `set_show()` 가 실패했을 때 한 번 비우고 재시도. 세션을 직접
열지 말고 항상 `origin_session()` 컨텍스트 매니저를 써라.

---

## 4. 상대 경로가 **예외 없이** 조용히 실패한다

**증상** — `op.open("donors/bar_labeled.opj")` 가 `False` 를 돌려주거나, 열린 것처럼
보이는데 그래프가 없다. 예외는 안 난다. 원인을 못 찾는다.

**원인** — **Origin COM은 상대 경로를 자기 작업 디렉터리 기준으로 푼다.** 파이썬
프로세스의 `cwd` 가 아니다. 그 디렉터리가 어디인지는 보장되지 않는다.

**대응** — Origin에 넘기는 **모든** 경로는 `Path(...).resolve()` 로 절대화한다.
저장 계열(`save_fig`)은 구분자도 정리한다:

```python
target = str(png.resolve()).replace("\\", "/")
```

그리고 저장은 **반환값만 믿지 말고 파일 존재를 확인**한다:

```python
if not gp.save_fig(target, width=1000) or not png.exists():
    raise RuntimeError("save_fig produced nothing")
```

---

## 5. OLE 임베드 (클립보드 경로는 폐기됨)

**증상** — `PasteSpecial(ppPasteOLEObject)` 이 "data type unavailable" 로 실패한다.

**원인** — `gp.copy_page('OLE')` 가 이 Origin(2021 / 9.8)에서 **클립보드에 아무것도
올리지 못한다.** 실패 시점에 클립보드 포맷을 열거하면 0개다 — 붙여넣기가 아니라
복사가 범인이다 (반증 실험으로 확정).

**대응** — 클립보드를 아예 쓰지 않는다. `paste.py` 는 그래프마다 개별 `.opju` 로
저장한 뒤 `slide.Shapes.AddOLEObject(FileName=..., Link=0)` 로 임베드한다.
진짜 편집 가능한 OLE다 (`Type=7`, `ProgID='Origin95.Graph'`, `ppt/embeddings/*.bin` 생성).

### 5-1. 임베드 후 Origin 좀비 (반드시 회수할 것)

**증상** — 중간산물 `.opju` 삭제가 `WinError 32` 로 실패하고, **그 다음 실행부터**
`OriginBusyError: Origin is already running` 이 뜬다. 사용자는 Origin을 켠 적이 없다.

**원인** — `AddOLEObject` 는 임베드마다 **창 없는 `Origin64.exe`** 를 OLE 서버로 띄우고,
그 프로세스가 소스 파일을 계속 붙들고 있다. 창이 없어 `WM_CLOSE`(taskkill 기본,
`CloseMainWindow`)는 먹지 않는다.

**대응** — PowerPoint를 잡기 **직전에** Origin PID를 스냅샷하고, 덱을 저장·종료한 뒤
**두 조건의 교집합**만 `taskkill /F` 한다 (`paste.reap_origin_servers`):

1. 스냅샷에 없던 PID (= 우리가 도는 동안 생겼다)
2. **주 창이 없는 프로세스** (`paste._windowless_pids`, PowerShell `MainWindowHandle`)

1번만으로는 위험하다. 조립 중에 사용자가 Origin을 열면 그 PID도 "새 PID"라 강제
종료 대상이 되어 **저장 안 된 사용자 프로젝트가 날아간다.** 사용자가 대화형으로 띄운
Origin은 항상 주 창을 갖고 OLE 서버는 창이 없다 — 둘을 가르는 유일하게 신뢰할 수 있는
신호다. 창 유무를 **판정하지 못하면 아무도 죽이지 않는다**: 남은 프로세스는 중간산물
삭제 실패와 다음 실행의 busy 가드로 드러나지만 그건 되돌릴 수 있고, 사용자의 미저장
작업은 되돌릴 수 없다.

덱은 이미 디스크에 내려간 뒤라 서버를 죽여도 임베드는 멀쩡하다
(검증: 임베드 2개 + `progId="Origin95.Graph"` 유지).

**규칙**

* `/origin` 실행을 **병렬로 돌리지 마라.** Origin이 단일 인스턴스라 두 번째는
  `OriginBusyError` 로 막힌다.
* 붙여넣을 **PowerPoint는 닫아 둔다.** 열려 있는 덱에 COM이 끼어들면 사용자 편집분과
  충돌한다.

---

## 6. 그래프에서 데이터가 잘린다 (축 범위)

**증상** — 새 데이터의 최댓값이 플롯 영역 위로 삐져나가거나 잘려 보인다.

**원인** — donor는 **자기 원본 데이터에 맞는 축 범위**를 갖고 있고, 워크시트를 갈아끼워도
그 범위가 **그대로 남는다** (검증됨). Origin이 알아서 다시 맞춰 주지 않는다.

**대응** — 레시피에 `y_range: auto` 를 준다. `style.compute_range()` 가 데이터에서
1/2/5×10ⁿ 눈금으로 범위를 다시 계산한다 (최대/최소를 **절대 자르지 않는** 것이 계약이고,
`test_style.py::test_compute_range_never_clips_data` 가 이를 고정한다).

* 고정 범위가 필요하면 `y_range: [0, 30]`.
* donor 범위를 그대로 두려면 `y_range: inherit`.
* `y_range` 는 **화이트리스트로 검증된다.** `auto` / `inherit` / 2원소 숫자 리스트만
  받고, `atuo` 같은 오타는 `load_recipe` 에서 `ValueError` 다
  (`test_build_golden.py::test_load_recipe_rejects_an_unknown_y_range_keyword`).
  조용히 "donor 범위 유지"로 흘러가지 않는다.
* `inherit` 이나 고정 리스트가 데이터를 잘라 내면 `AxisClipWarning` 이 뜬다
  (그래프는 만들어진다). 경고를 보면 범위를 다시 정하거나 `auto` 로 바꾼다.

**x축은 경로에 따라 다르다.**

* **범위 막대(`y_low`/`y_high`) 경로는 범주 수에 맞춰 x축을 다시 계산한다** —
  `build.category_x_range(n)` → `0.5 ~ n+0.5`. donor(`floating_bar`)에 구워진
  `[0.5, 2.5]` 를 그대로 두면 범주 3개부터 뒤쪽 막대가 축 밖으로 나가 잘렸다.
* **일반 donor 경로는 여전히 x축을 재계산하지 않는다.** 범주 개수가 donor와 다르면
  x축이 어긋난다 (`bar_labeled` donor는 3개 기준). 아직 남아 있는 한계다.

---

## 7. 골든 이미지가 깨진다 (`golden image drift`)

**증상** — `tests/test_build_golden.py::test_golden_inherit_matches_donor` 실패.
`tests/_debug/ref.png` 와 `got.png` 가 남는다.

**원인 — 먼저 이것부터 확인하라**: 골든을 `style: house` 로 돌린 것 아닌가?
**골든은 반드시 `style: inherit` 이다.** house는 폰트·두께·눈금을 전부 덮어쓰므로
donor와 픽셀이 같을 수가 없다. house 모드의 검증은 픽셀 비교가 아니라
**속성 재측정**(`test_house_mode_lands_style`)이 담당한다.

그다음 의심할 것:

| 확인 | 뜻 |
|---|---|
| `spec` 에 `colors` 가 들어갔는가 | `colors` 가 있으면 `inherit` 라도 값 라벨 홀더를 지우고 직접 그린다 → 픽셀이 달라진다. **`inherit` = donor 그대로** 라는 약속을 깨는 유일한 합법 경로 |
| `title` / `annotation` 을 넣었는가 | 오브젝트가 추가되므로 당연히 달라진다. 골든 레시피에는 넣지 않는다 |
| `y_range` 를 `auto` 로 바꿨는가 | 골든 레시피는 `inherit` 이다. `auto` 는 축을 다시 계산한다 |
| `data` 가 donor 원본 데이터와 같은가 | 골든은 `fixtures/pugh.csv` (donor 원본값) 기준이다 |
| `_decorate` / `style.py` 를 건드렸는가 | 요청 없는 필드에 손대면 안 된다는 계약이 깨졌을 수 있다 |

`inherit` 경로는 **"요청이 없으면 아무것도 건드리지 않는다"** 가 계약이다.
이 테스트를 통과시키려고 골든 이미지를 갱신하는 선택은 하지 마라 — 계약이 깨진
쪽을 고쳐야 한다.

---

## 8. 막대 위에 약 2px 잔점이 남는다

**증상** — house 모드로 렌더하면 우리가 그린 값 라벨 말고, 막대 위 어딘가에 아주 작은
점 같은 것이 보인다.

**원인** — 상속된 값 라벨(`Style`/`Style1`/`Style2` 홀더)을 **완전히 못 지우고 축소만**
했기 때문이다. `fsize` 를 **0.1 이하로 낮추면 Origin이 무시하고 기본 크기로 되돌린다.**
실질 하한이 0.5이고, 그 크기가 렌더에서 1~2px로 남는다.
(자세한 실측은 `references/labtalk_props.md` §8.)

**대응** — 레시피에 `colors` 를 지정한다. 색 지정 경로는 홀더를 **삭제**하므로
(`drop_point_styles`) 잔점도 함께 사라진다. `colors.base` 하나만 줘도 된다:

```yaml
colors:
  base: "#808080"
```

색을 굳이 바꾸기 싫다면 donor의 원래 막대색과 같은 값을 `base` 로 주면 된다.
**색을 지정하지 않는 한 이 잔점은 현재 제거 불가**이며, 알려진 잔여 결함이다.

---

## 9. `donor ... has no worksheet` / 데이터가 안 들어간다

**증상** — `ValueError: requested donor 'log_axis' has no worksheet, ...` (레시피에
적었을 때) 또는 `RuntimeError: inferred donor 'log_axis' has no worksheet, ...`
(추론이 골랐을 때, 그 그래프를 빌드하는 순간).

**원인** — `log_axis` 와 `errorbar` 는 **워크북이 통째로 없다** (실측 2026-07-29:
`op.pages('w')` 가 비어 있고 그래프 페이지 하나뿐이다). 북 이름 후보가 부족한 게
아니다 — 원본 덱의 OLE에 Origin이 그래프만 임베드했고, 플롯이 참조하던 데이터셋
자체가 프로젝트에 없다. manifest에 `data_shape.has_worksheet: false` 로 기록돼 있다.

**두 경로가 다르게 동작한다** (`build.load_recipe`):

| 어떻게 골랐나 | 언제 | 무엇이 일어나나 |
|---|---|---|
| 레시피에 `donor:` 로 **명시** | `load_recipe` (Origin 기동 전) | 즉시 `ValueError`. 사용자가 틀린 것을 골랐으니 알려야 한다 |
| 데이터 형태로 **추론** | 해당 그래프의 `build_graph` | 스펙에 `build_error` 를 심어 두었다가 그 그래프만 `RuntimeError`. **나머지 그래프는 계속 만든다** |

추론 경로에서 레시피 전체를 죽이면 `paste.py` 의 "부분 실패는 건너뛰고 n/total로
보고한다" 계약이 깨진다 — 우리가 고른 donor 때문에 사용자의 멀쩡한 그래프까지
잃을 수는 없다.

**대응** — 쓸 수 있는 donor는 예외 메시지에 목록으로 나온다 (`buildable_donors()`).
`log_axis` / `errorbar` 를 되살리려면 donor를 다시 저작하는 수밖에 없다
(`scripts/_author_floating_bar.py` 가 저작 사례).

**워크시트를 찾는 방법** — `build.find_worksheet()` 는 먼저 `Book1`~`Book5` 를
순회하고, 못 찾으면 `op.pages('w')` 로 실제 워크북을 열거한다. donor가 `Draw1` 처럼
다른 이름을 달고 있어도 잡힌다. 두 경로가 모두 비면 워크북이 정말 없는 것이다.

### 9-1. 범주형 x축 눈금 라벨이 1, 2, 3 으로 무너진다

**원인** — 범주형 x축은 텍스트 컬럼을 **데이터셋으로 참조**한다
(`layer.x.label.dataset$`). 텍스트를 숫자로 치환해 넣으면 참조가 깨져 행 번호가 뜬다.

**대응** — `wks.from_df()` 에 **원본 dtype 그대로** 넘긴다. 텍스트 컬럼도 그대로 들어간다
(실측). 숫자로 변환하지 마라.

---

## 10. 축 제목이 `val (B/G)` 처럼 거짓말을 한다

**증상** — 새 데이터인데 donor의 단위가 제목에 붙어 나온다.

**원인** — `wks.from_df()` 는 Long Name은 갈아끼우지만 **Units는 남긴다.** 축 제목이
`%(?Y)` 치환 토큰이면 `Long Name (Units)` 로 렌더되므로 옛 단위가 그대로 새어 나온다.

**대응** — 주입 직후 모든 컬럼의 Units를 비운다. `build.build_graph` 가 이미 한다:

```python
for i in range(len(new.columns)):
    wks.set_label(i, "", "U")
```

단위를 제목에 넣고 싶으면 `y_title: "g / 100 mL"` 처럼 **제목 문자열에 직접** 쓴다.

---

## 11. `find_sheet('w')` 가 항상 `None`

**증상** — 그래프를 활성화한 뒤 워크시트를 잡으려 하면 `None`.

**원인** — `find_sheet('w')` 의 `'w'` 는 타입이지만, **북 이름을 안 주면 *활성* 시트**를
뜻한다. 그래프를 활성화한 순간 활성 워크시트는 없다 — **두 호출이 상호배타적**이다.

**대응** — 북 이름을 명시하고 순회한다 (`build._find_wks`, `survey._describe_data` 가
같은 패턴). 워크시트 작업을 먼저 끝내고 나서 `win -a <graph>;` 로 그래프를 활성화한다.

---

## 12. LabTalk 명령을 줬는데 아무 일도 안 일어난다

**증상** — 예외도 없고 값도 안 바뀐다.

**원인 후보 3가지**

1. **속성 이름이 존재하지 않는다.** `op.lt_float(name)` 이 `nan` 이면 그 이름은 없는 것이다
   (예: `layer.x.majorTicks`, `layer.frame.width`, `layer.axisWidth`, `layer.nplots`).
   → `references/labtalk_props.md` §3.
2. **배치가 중간에서 죽었다.** 한 `lt_exec` 안의 명령 하나가 COM 예외를 내면 **그 뒤가
   통째로 유실된다.** 대표 사례: 텍스트가 없는 축 제목에 `fsize` 쓰기 → §labtalk_props §5.
3. **활성 그래프가 다르다.** `layer.*` / `XB.*` 는 활성 페이지를 가리킨다.
   `op.lt_exec(f"win -a {gname};")` 를 먼저 부른다.

**대응** — 쓰고 나서 **다시 읽어** 확인한다. house style 검증이 픽셀 비교가 아니라
속성 재측정인 이유가 이것이다.

---

## 13. 같은 프로세스에서 `.opju` 재오픈이 **간헐적으로** False

**증상** — 저장까지 끝난 `.opju` 를 같은 파이썬 프로세스의 **두 번째 세션**에서 열면
`op.open()` 이 `False`. 예외는 없다. 파일은 멀쩡하다.

**관측 (2026-07-29)** — `scripts/_acceptance_full.py` 의 재오픈 단계에서 1회 발생.
같은 파일을 **새 프로세스**에서 열자 즉시 `True` 였고, 스크립트를 다시 돌리자 같은
경로가 그대로 통과했다. 재현 조건은 아직 모른다 (Origin 종료 직후의 COM 상태로 의심).

**대응** — 열기 실패만 **세션을 새로 잡아 재시도**한다 (`_acceptance_full.reopen`,
최대 3회). **검증 실패는 재시도하지 않는다** — 재시도로 가리면 검증이 무의미해진다.
재오픈이 꼭 독립적이어야 하는 검증이라면 별도 프로세스로 돌려라.

---

## 14. 강조/주석이 조용히 무시된다

**증상** — `colors.highlight.category` 나 `annotation.at` 에 적은 범주가 그래프에 안 나타난다.

**원인** — 오타이거나, 실제 데이터의 범주 표기와 다르다 (`beta-CD` vs `β-CD` 가 대표적).

**대응** — 조용히 무시되지 않는다. `load_recipe()` 가 **그래프를 만들기 전에** 검증하고
가진 범주 목록과 함께 즉시 실패한다:

```
ValueError: colors.highlight.category 'delta-CD' not found in x values; has ['α-CD', 'β-CD', 'γ-CD']
```

이 예외를 보면 레시피의 문자열을 **데이터 파일에 적힌 그대로** 고쳐라.
그리스 문자는 Origin까지 살아서 간다 (`scripts/_acceptance_greek.py` 로 확인).

## 2026-07-31 실측 함정 3건 (Island-pattern 논문 32그래프 캠페인에서 검증)

1. **심볼 채움색은 COM/LabTalk로 지정 불가** — `set -cf`, `plotN.symbol.fillcolor`, `symbol_interior` 등 4경로 전부 반증됨. `plotN.color`는 선·심볼 테두리만 변경. **회피: XY 플롯은 line-only로 통일**해 팔레트를 지킬 것.
2. **donor 범례 오브젝트는 범례 항목 수 < plot 수이면 남은 컬럼명을 자동으로 덧붙임** (예: 12 plot/3 항목 → 6줄 범례). **회피: 기존 범례 삭제 후 `\l(i)` 이스케이프를 담은 텍스트 오브젝트로 직접 작성** (스와치 정상 렌더).
3. **등축 Nyquist에서 레이어/페이지 기하를 수정하면 축 제목이 잘림.** **회피: donor 기하는 불변으로 두고 x·y 축 범위를 같은 값으로 맞춰 등축을 달성** (donor 원본 관례와 동일).
4. (부수) `bar_labeled` donor에는 XB 축제목 오브젝트가 없음 — 막대 그래프 x축 제목은 쓰지 말 것.
