# LabTalk / originpro 속성 사전 (검증본)

Origin 2021 64-bit (`Origin64.exe`) + `originpro` 로 **실제 실행해서 확인한 것만** 적는다.
여기 없는 이름은 "아직 확인 안 됨"이지 "동작함"이 아니다. 추측해서 쓰지 마라.

측정 근거: `scripts/survey.py`(PROPS 전수 판독), `scripts/style.py`(적용 후 재측정),
`scripts/decorate.py`(그래프 오브젝트 실측), `tests/test_style.py`·`tests/test_survey.py`(회귀 고정).

---

## 0. 읽기·쓰기 규약

| 하는 일 | 호출 | 주의 |
|---|---|---|
| 수치 읽기 | `op.lt_float("layer.y.from")` | **미해결 이름은 예외가 아니라 `nan`** 이다. 오타가 조용히 통과한다 |
| 문자열 읽기 | `op.get_lt_str("YL.text$")` | `op.lt_str` 라는 함수는 **없다** (AttributeError) |
| 실행 | `op.lt_exec("layer.y.from = 0; doc -uw;")` | 여러 명령을 `;` 로 이어 붙일 수 있다 |
| 그래프 활성화 | `op.lt_exec(f"win -a {gname};")` | `layer.*` / `XB.*` 는 **활성 그래프**를 가리킨다. 활성화 없이 쓰면 엉뚱한 페이지가 바뀐다 |
| 변경 반영 | `op.lt_exec("doc -uw;")` | 텍스트 객체의 `dy`(높이) 같은 값은 flush 전에는 갱신되지 않는다 |

`lt_float`가 `nan`을 돌려주는 성질 때문에, 새 속성을 쓸 때는 **쓰고 나서 다시 읽어**
값이 실제로 앉았는지 확인해야 한다 (`test_style.py::test_house_style_actually_lands` 방식).
픽셀 비교는 house style 검증에 쓰지 않는다 — 속성 재측정이 정본이다.

---

## 1. 읽고 쓸 수 있는 속성

`<ax>` 는 `x` 또는 `y`.

| 속성 | 뜻 | R | W | 비고 |
|---|---|:--:|:--:|---|
| `layer.<ax>.from` | 축 시작값 | O | O | 역방향 축은 from > to (waterfall donor: 4000 → 600) |
| `layer.<ax>.to` | 축 끝값 | O | O | |
| `layer.<ax>.inc` | 주눈금 간격 | O | O | 역방향 축은 음수 |
| `layer.<ax>.type` | 축 스케일 | O | — | `1` = linear, `2` = log10 (log_axis donor로 확인) |
| `layer.<ax>.thickness` | 축선 두께 | O | O | house = 4. donor 실측 최빈값은 3 |
| `layer.<ax>.ticks` | 눈금 방향 비트마스크 | O | O | §2 참조 |
| `layer.<ax>.label.pt` | **눈금 라벨** 글자 크기 | O | O | house = 24 |
| `layer.<ax>.label.bold` | 눈금 라벨 볼드 | O | O | `1`/`0`. house = 1 |
| `layer.<ax>.label.dataset$` | 범주형 눈금 라벨이 참조하는 컬럼 | O | (미시도) | 텍스트 x 컬럼을 숫자로 갈아끼우면 라벨이 1,2,3으로 무너지는 이유가 이것 |
| `XB.fsize` / `YL.fsize` / `YR.fsize` | **축 제목** 글자 크기 | O | O* | \*제목 텍스트가 비어 있는 축에 쓰면 COM 예외 (§5) |
| `XB.text$` / `YL.text$` / `YR.text$` | 축 제목 문자열 | O | O | 치환 토큰일 수 있다 (§6) |
| `page.nLayers` | 레이어 수 | O | — | double_y / broken_axis / errorbar donor = 2 |
| `page.width` / `page.height` | 페이지 크기 | O | — | donor마다 다르다 (3390×2362 ~ 14100×4724) |
| `@V` | Origin 버전 | O | — | 세션 생존 확인용 (`test_session.py`) |

축 제목(`XB`/`YL`/`YR`)은 **layer 속성이 아니라 독립 텍스트 오브젝트**다. 그래서 축과
같은 배치에 묶어 쓰면 안 된다 (§5).

`layer.*` 는 **활성 레이어 1개**에만 걸린다. `page.nLayers == 2` 인 donor(double_y,
broken_axis, errorbar)는 두 번째 레이어가 house style을 못 받는다 — 현재 알려진 한계.

---

## 2. 눈금 방향 비트마스크 (`layer.<ax>.ticks`)

렌더 비교로 확정 (2026-07-28). `data/house_style.yaml`의 `tick_bitmask`가 이 표의 사본이다.

| bit | 뜻 |
|---|---|
| bit0 (1) | major tick **in** |
| bit1 (2) | major tick **out** |
| bit2 (4) | minor tick **in** |
| bit3 (8) | minor tick **out** |

조합값:

| 값 | 결과 | house style |
|---|---|---|
| `0` | 눈금 없음 | |
| `5` | major+minor 모두 **In** | ← `tick_direction: in` |
| `10` | major+minor 모두 **Out** | |
| `15` | In & Out (양방향) | |

donor 실측: bar_labeled = x:0 / y:5, bar_grouped = 1, double_y = 10, waterfall = x:5 / y:0.
즉 **donor마다 제각각**이라 house style이 통일해 준다.

---

## 3. 해결되지 않는 이름 (전부 `nan`)

아래는 그럴듯하지만 **존재하지 않는** 속성이다. `lt_float`가 예외 없이 `nan`을 돌려주므로,
"값을 못 읽었다"를 "0이다"로 착각하기 쉽다. 다시 시도하지 마라.

| 시도한 이름 | 결과 | 대신 쓰는 것 |
|---|---|---|
| `layer.x.majorTicks` | nan | `layer.x.inc` (간격) / `layer.x.ticks` (방향) |
| `layer.frame.width` | nan | `layer.x.thickness` / `layer.y.thickness` |
| `layer.axisWidth` | nan | 같음 |
| `layer.nplots` | nan | `gl.plot_list()` 길이 (Python 쪽에서 센다) |

교훈: **`nan`은 "그 이름이 없다"는 뜻이다.** 값이 0으로 보이면 그건 진짜 0이지만,
nan이면 경로 자체가 틀린 것이다.

---

## 4. 동작하지 않는 X-Function (설계가 donor 기반인 이유)

"스타일을 템플릿으로 뽑아 재사용한다"는 정공법은 **전부 실패했다**. 아래 호출들은
예외도 내지 않고 성공한 척하지만 **파일을 만들지 않는다**.

| 호출 | 관측 | |
|---|---|---|
| `template_saveas` | .otpu 파일 생성 안 됨 | |
| `save -t` | 파일 생성 안 됨 | |
| `theme_save` | 파일 생성 안 됨 | |
| `save -i` | 프로젝트 파일 생성 안 됨 | 프로젝트 저장은 `op.save(path)` (.opju) 가 정본 |

그래서 이 스킬은 **.otpu 템플릿을 쓰지 않는다.** 대신 원본 논문 덱에서 복원한
`.opj` 프로젝트 자체를 donor로 열어 워크시트 데이터만 갈아끼운다. 스타일은
"파일로 추출"하는 게 아니라 **"프로젝트 안에 그대로 둔 채 상속"** 한다.
이 설계 결정 하나가 위 4줄에서 나왔다.

프로젝트 저장·재오픈이 실제로 왕복하는지는 `scripts/_prove_roundtrip.py` 가 증명한다.

---

## 5. 축 제목에 크기를 줄 때 (배치 유실 함정)

```python
op.lt_exec("XB.fsize = 32; YL.fsize = 32; YR.fsize = 32;")   # 하지 마라
```

`bar_labeled` donor에는 `XB`(하단 x 제목) 텍스트가 아예 없다. 없는 오브젝트에 `fsize`를
쓰면 COM이 예외를 던지고, **한 배치로 묶여 있으면 그 뒤 명령이 통째로 유실된다.**
`YL`까지 같이 날아간다.

정본 (`style.apply_house_style`):

```python
for title in ("XB", "YL", "YR"):
    try:
        if not op.get_lt_str(f"{title}.text$"):   # 글자 없는 제목은 건드리지 않는다
            continue
        op.lt_exec(f"{title}.fsize = {pt};")      # 제목마다 따로 실행
    except Exception:
        pass
```

---

## 6. 축 제목의 치환 토큰

donor의 `YL.text$` 는 리터럴이 아니라 **치환 토큰 + 서식 이스케이프**다.

```
bar_labeled 의 YL.text$  ==  \p127(\b(%(?Y)))
```

읽는 법: `\p127(...)` = 기준 대비 127% 크기, `\b(...)` = 볼드, `%(?Y)` = **그 레이어 Y축
데이터 컬럼의 Long Name (Units)** 로 런타임 치환.

따라서 축 제목을 리터럴로 덮어쓰면 **글자는 맞아도 서식이 죽는다.** 대응
(`build._set_axis_title`):

```python
current = op.get_lt_str(f"{obj}.text$") or ""
if _TITLE_TOKEN[obj] in current:      # XB→"%(?X)", YL/YR→"%(?Y)"
    wks.set_label(col_index, text, "L")   # 컬럼 Long Name을 갈아끼운다
else:
    op.lt_exec(f'{obj}.text$ = "{text}";')  # 리터럴 제목이면 직접 대입
```

부작용 주의: `wks.from_df()` 는 Long Name은 갈아끼우지만 **Units는 남긴다.** donor의
단위가 새 데이터에 눌러앉아 `val (B/G)` 같은 거짓 제목이 나오므로, 주입 직후 모든
컬럼의 Units를 명시적으로 비운다 (`wks.set_label(i, "", "U")`).

---

## 7. 점별 막대색 — 실패 경로와 우회

**전부 먹지 않았다** (실측):

| 시도 | 결과 |
|---|---|
| `colorlist` 계열 LabTalk 경로 | 반영 안 됨 |
| `cmap` 계열 | 반영 안 됨 |
| `fillcolor` (plot / 홀더 양쪽) | 반영 안 됨. 홀더의 읽기값은 실제 렌더 색과도 다르다 |

**실제로 쓰는 우회** (`decorate.apply_colors`):

1. 점별 스타일 홀더를 먼저 지운다 (`drop_point_styles`). 홀더가 살아 있으면 **plot 색 지정
   자체가 무시된다.**
2. `plots[0].color = base` 로 전체 색을 준다 (여기는 정상 동작).
3. 강조는 색이 아니라 **plot을 하나 더 겹쳐서** 만든다 — 강조할 인덱스만 값이 있고 나머지는
   `nan`인 컬럼을 워크시트에 추가하고, `gl.add_plot(wks, coly=col, colx=0, type="c")`
   (column plot)로 같은 자리에 그린 뒤 `plot.color = highlight_color`.
4. 새 컬럼의 Long Name은 **원래 Y와 같게** 준다. 안 그러면 `%(?Y)` 치환 축 제목에
   새 컬럼 이름이 새어 나온다.
5. plot 추가 후 `gl.group(False)` (그룹 자동 색상화 방지) 하고, `layer.y.from/to/inc` 를
   **미리 읽어 두었다가 되돌린다** — plot 추가가 축 범위를 흔든다.

---

## 8. 값 라벨 = `Style` / `Style1` / `Style2` 홀더

bar_labeled donor의 막대 위 숫자는 **데이터 라벨이 아니다.** `layer.plot1.label.show == 0`
인데도 그려진다. 실체는 레이어의 그래프 오브젝트 `Style`, `Style1`, `Style2` — Origin이
'점별 스타일'을 저장할 때 만드는 홀더다 (이름 규칙: `^Style\d*$`).

실측 성질:

| 조작 | 결과 |
|---|---|
| 홀더 하나 숨김 | 해당 **막대와 값 라벨이 함께** 사라진다 |
| 홀더 삭제 (`o.Destroy()`) | 막대는 plot 기본색으로, 값 라벨은 소멸 |
| `o.SetNumProp("fsize", 72)` | 그 점의 **값 라벨만** 커진다 → fsize = 값 라벨 글자 크기 |
| `fillcolor` / `color` 설정 | 먹지 않음 (읽기값도 실제 색과 불일치) |
| **세로 위치** | **어떤 속성으로도 노출되지 않는다** |

위치가 안 나오는 게 치명적이다. donor의 2번째 점은 라벨이 막대 top **아래**에 박혀 있고,
이건 데이터·축 범위와 무관하게 **점 인덱스를 따라간다** (값을 25/14.5/1.85로 바꿔도
2번째가 어긋난다). 그래서 상속 라벨을 고칠 방법이 없다 — **무력화하고 직접 그린다.**

* `fsize = 0.5` 로 낮춰 렌더에 1px 이하만 남긴다 (`mute_point_labels`).
  **0.1 이하는 Origin이 무시하고 기본 크기로 되돌린다** — 0.5가 실질 하한이다.
  그래서 `colors`를 지정하지 않으면 약 2px 잔점이 남는다 (알려진 잔여 결함).
* `colors`를 지정한 경우엔 아예 삭제한다 (`drop_point_styles`) — 홀더가 살아 있으면
  plot 색이 안 먹기 때문. 이 경로에서는 잔점도 사라진다.

읽어 오는 크기(`value_label_pt`)는 홀더들의 `fsize` 중 **1보다 큰 값의 최대치**다.
1 이하는 우리가 이미 죽여 놓은 값이라 재사용하면 안 된다.

---

## 9. 그래프 오브젝트 (텍스트 / 선) 조작

`gl = op.find_graph(gname)[0]` (레이어) 기준.

| 하는 일 | 호출 |
|---|---|
| 오브젝트 전수 | `gl.obj.GraphObjects` → `o.Name`, `o.Text`, `o.GetNumProp/SetNumProp`, `o.Destroy()` |
| 텍스트 추가 | `gl.add_label(text, x, y)` → 실패 시 `None` (예외 아님, 반드시 검사) |
| 선/화살표 추가 | `gl.add_line(x0, y0, x1, y1)` |
| plot 목록 / 색 | `gl.plot_list()`, `plot.color = "#RRGGBB"` (읽으면 `(r, g, b)` 튜플) |
| plot 추가 | `gl.add_plot(wks, coly=, colx=, type="c")` — `"c"` = column(막대) |
| 그룹 해제 | `gl.group(False)` |

텍스트/선 객체 속성:

| 속성 | 값 | 비고 |
|---|---|---|
| `attach` | `2` | **데이터 좌표에 고정.** 안 주면 페이지 좌표라 축이 바뀌면 어긋난다 |
| `x` / `y` | float | **중심 좌표다** (좌상단이 아니다 — 실측) |
| `dx` / `dy` | float (읽기) | 객체 폭/높이. `doc -uw;` 로 flush **한 뒤**에 읽어야 유효 |
| `fsize` | float | 글자 크기 |
| `color` | `"#RRGGBB"` | |
| `bold` | — | **먹지 않는다.** `set_int` / LabTalk 양쪽 실패 |
| `arrowendshape` | `2` | 선 끝에 화살촉 |
| `width` | int | 선 두께 |

**볼드는 속성이 아니라 이스케이프로 넣는다** — donor 축 제목이 쓰는 방식과 같다:

```python
def bold(text): return f"\\b({text})"     # decorate.bold
```

배치 관용구 (`decorate._center`): `add_label` → `attach=2`, `fsize` → `doc -uw;` →
`dy` 읽기 → `y = 값 + dy * 계수` 로 다시 중심을 놓는다. 값 라벨은 계수 `0.8`
(라벨 절반 0.5 + donor 기준 간격 0.3), 그래프 제목은 `0.75`.

---

## 10. 워크시트

| 하는 일 | 호출 | 함정 |
|---|---|---|
| 시트 잡기 | `op.find_sheet("w", "Book1")` | `'w'` 는 타입(worksheet)이고 **북 이름이 없으면 *활성* 시트**를 뜻한다. 그래프를 활성화한 뒤엔 항상 `None` — 두 호출이 상호배타적이다. `Book1`~`Book5` 를 순회해서 잡는다 |
| 데이터 주입 | `wks.from_df(df, addindex=False)` | 텍스트 컬럼도 그대로 들어간다 (범주형 x 유지). Long Name은 갱신, **Units는 남는다** |
| 컬럼 하나 추가 | `wks.from_list(col, values, long_name)` | 강조 오버레이용 |
| 라벨 쓰기 | `wks.set_label(i, text, "L" \| "U")` | `L`=Long Name, `U`=Units |
| 라벨 읽기 | `wks.get_labels("L")` | |
| 형태 | `wks.shape`, `wks.to_df()`, `wks.lt_range()` | |

---

## 11. 렌더 / 복사 / 저장

| 하는 일 | 호출 | 비고 |
|---|---|---|
| PNG 저장 | `gp.save_fig(path, width=1200)` | `gp = op.find_graph(name)`. 경로는 **절대 경로 + `/` 구분자**. 성공해도 파일 존재를 따로 확인할 것 |
| 클립보드 OLE 복사 | `gp.copy_page('OLE')` | **쓰지 마라 — 이 환경에서 무반응이다.** 클립보드에 올라오는 포맷이 0개라 `PasteSpecial` 이 실패한다 (반증 실험 확정) |
| PPT에 OLE 임베드 | `slide.Shapes.AddOLEObject(FileName=<.opju>, Link=0)` | 정본 경로. 클립보드를 안 쓴다. 결과 `Type=7`, `ProgID='Origin95.Graph'`. **임베드마다 창 없는 Origin64.exe 가 뜨고 소스 파일을 붙든다 — 회수 필요** |
| 프로젝트 저장 | `op.save(path)` | `.opju`. LabTalk `save -i` 는 파일을 안 만든다 (§4) |
| 프로젝트 열기 | `op.open(str(Path(p).resolve()), readonly=False)` → bool | **상대 경로 금지** (§ troubleshooting) |
| 그래프 목록 | `op.graph_list()` → `.name` 보유 | |
| 숨김 실행 | `op.set_show(False)` | |
| 종료 | `op.exit()` | 실패 시 뒤처리 필요 (troubleshooting §3) |

---

## 12. floating bar (범위 막대) — 2026-07-29 실측

### 12.1 플롯 만들기

Origin 내장 템플릿 **`FloatCol.otp`** 이 정본이다 (`FLOATBAR.OTP` 는 가로 버전).
설치 경로에 실재한다: `C:\Program Files\OriginLab\Origin2021\FloatCol.otp`.

| 방법 | 결과 |
|---|---|
| `op.new_graph(template="FloatCol")` + `plotxy iy:=[Book]sht!(1,2:N) plot:=230 ogl:=[G]1!;` | **동작** (정본) |
| `worksheet -s 1 0 N 0; worksheet -p 230 FloatCol;` | 동작 (워크시트가 활성일 때) |
| `gl.add_plot("[Book]1!(1,2:3)", type="?")` | **Origin 프로세스가 죽는다** (0xC0000409). 쓰지 마라 |

`plot:=230` 은 "템플릿의 플롯 타입을 그대로" 라는 뜻이다 (originpro가 `type='?'` 에 쓰는 값).

**Y 컬럼은 앞에서부터 둘씩 묶여 막대 하나가 된다.** 컬럼 4개 → 막대 2개.
범주마다 독립된 (아래,위) 쌍을 주고 자기 행 외에는 `NaN`으로 채우면 막대마다 plot이
분리된다 → **점별 색 지정 없이 계열별 색이 가능해진다** (§7의 우회와 같은 발상).

### 12.2 삭제의 하한

`plot.remove()` = `dp.Destroy()`. 두 가지 함정:

* 미리 뽑아 둔 `plot_list()` 를 앞에서부터 돌면 **일부만 지워진다** (핸들이 무효가 된다).
  매번 목록을 다시 읽고 **뒤에서부터** 지운다.
* floating column 레이어는 **plot 2개 밑으로는 안 지워진다** (4→2까지만, 그 뒤로는
  조용히 무시). 그래서 `build._build_floating` 은 "전부 지우고 다시 그리기"가 아니라
  **"2개만 남기고 나머지를 이어 붙이기"** 로 간다.
* `layer -d;` 는 데이터 plot이 아니라 **레이어 자체를 지운다.** 쓰지 마라.

### 12.3 막대 색 — 채움은 되고 테두리는 안 된다

| 속성 | 결과 |
|---|---|
| `layer.plotN.color` | **채움색** (동작). `plot.color` 와 같은 경로 |
| `layer.plotN.transparency` | 동작 (0~100). 100이면 테두리까지 사라진다 |
| `fillcolor` / `patterncolor` / `patternwidth` / `pattern` / `linecolor` / `bordercolor` / `edgecolor` / `linewidth` | **전부 nan** (존재하지 않음) |
| `set <dataset> -c` / `-cf` / `-b` | 성공하지만 **전부 채움색으로 간다** |
| `layer.gap` / `gapamount` / `bargap` / `barwidth` / `colwidth` / `plotN.gap` | **전부 nan** — 막대 폭을 읽지도 쓰지도 못한다 |

→ **막대 테두리 색을 지정할 LabTalk 경로가 없다.** 대응: 막대와 같은 자리·같은 크기의
`Rect` 그래프 오브젝트를 겹쳐 그린다 (§12.4). 막대 폭은 렌더 픽셀 측정으로 확정한
**범주 간격의 0.8배** (`decorate.BAR_WIDTH`, 기본 gap 20%). 겹쳐 그리면 plot의 검은
테두리는 Rect 밑으로 완전히 가려진다 (1000px 렌더에서 잔여 검정 픽셀 0개).

### 12.4 Rect / 도형 그래프 오브젝트

`gl.obj.GraphObjects.Add(<type>)` 의 타입 ID (실측):

| ID | 객체 | ID | 객체 |
|---|---|---|---|
| 2 | Text | 8 | **Rect** |
| 4, 5 | Line | 9 | Circle |
| 6 | Polyline | 11 | Polygon |
| 7 | Curve | 0/1/3/10/12 | COM 예외 |

Rect 속성 (LabTalk `<Name>.<prop>`, 이름은 `Rect`, `Rect1`, …):

| 속성 | 뜻 |
|---|---|
| `color` | **테두리 색** — plot에는 없는 이 속성이 존재 이유다 |
| `fillcolor` | 채움 색 |
| `transparency` | 0~100. 채움에만 걸리고 테두리는 그대로 |
| `linewidth` | 테두리 두께 |
| `x` / `y` / `dx` / `dy` | 중심 좌표와 크기 (`attach = 2` 면 데이터 좌표) |
| `pattern` | **nan** (없음) |

**크기를 먼저, 위치를 나중에 준다.** 반대로 하면 `dy` 를 줄 때 한쪽 모서리를 고정한 채
자라서 중심이 밀린다 (실측: `y=2.15` 뒤 `dy=6.8` → 중심이 3.69로 이동). 순서를 지키면
`x`/`y` 는 소수점 4자리까지 요청값 그대로 앉는다.

레시피의 `alpha`(불투명도 0~1)와 Origin의 `transparency`(투명도 0~100)는 **서로
반대**다. `decorate.transparency_of()` 가 변환한다.

### 12.5 그 밖

* **범례 삭제**: `label -r legend;` 가 정본이다. `legend -r;` 은 `True`를 돌려주지만
  지워지지 않는다.
* **2줄 눈금 라벨**: 범주형 x축 라벨은 텍스트 컬럼(`layer.x.label.dataset$`)을 그대로
  렌더한다. **셀 안에 `\n` 을 넣으면 두 줄로 그려진다.** 별도 속성이 필요 없다.
* **플롯 바깥 라벨**: `attach = 2` 인 텍스트를 `layer.x.to` 보다 오른쪽에 놓으면 그려지되
  **페이지 밖으로 나가면 잘린다.** `page.width` / `layer.left` / `layer.width` /
  `layer.top` / `layer.height` 는 전부 읽고 쓸 수 있으므로 레이어 폭을 줄여 여백을 만든다
  (floating_bar donor: page.width 9000, layer 13/22/55/60).
* **`op.save(".opj")` 는 동작한다.** `.opju` 뿐이라는 뜻이 아니었다 — 확장자를 `.opj` 로
  주면 레거시 포맷으로 저장되고 `op.open` 으로 plot·축 범위·치환 토큰까지 그대로
  왕복한다 (54KB, 검증됨). 그래서 저작 donor도 다른 9종과 같은 `.opj` 로 둔다.

---

## 13. 요약 — 왜 이 스킬이 이런 모양인가

* 템플릿(.otpu)·테마 저장이 **파일을 안 만든다** → donor `.opj` 상속 설계.
* 점별 색 LabTalk 경로가 **전부 죽어 있다** → 오버레이 plot으로 강조,
  floating bar는 범주별 컬럼 쌍으로 분리.
* 막대 **테두리 색 속성이 없다** → 같은 자리에 `Rect` 오브젝트를 겹친다.
* 값 라벨 위치가 **속성으로 안 나온다** → 상속 라벨 무력화 후 직접 렌더.
* `lt_float`가 오타에 **nan을 돌려준다** → 쓴 다음 다시 읽어 검증하는 습관이 필수.

### 12.5 산점(symbol) 채움색·테두리색·크기 (실측 2026-09-07, line_symbol donor + add_plot type 's')

| 경로 | 결과 |
|---|---|
| `plot.color` (originpro) / `set -c` | **테두리(edge)만** 바뀐다. 채움은 donor의 고정 채움색이 남는다 |
| `set %C -csf color(r,g,b)` | **채움색** 동작 |
| `set %C -cse color(r,g,b)` | **테두리색** 동작 |
| `set %C -cf` | 산점에는 무반응 (막대의 채움 경로) |
| `set %C -z n` | 무반응. 크기는 originpro `plot.symbol_size = n` 으로 |
| `layer.plotN.symbol.fillcolor` / `.edgecolor` / `.interior` 읽기 | **nan** (없거나 읽히지 않음) |
| `layer.clip = 0` | 동작 — 축 위에 걸친 점(x≈0)이 잘리지 않게 클리핑 해제 |

**옵션은 `set_cmd("-csf …", "-cse …")` 처럼 인자 하나에 옵션 하나씩** 넘겨야 한다.
한 문자열에 `-c … -kf 1 -csf … -z 24` 를 섞어 넘기면 전부 무시된다(렌더로 확인).
