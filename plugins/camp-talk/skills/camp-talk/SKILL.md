---
name: camp-talk
description: 논문·원고·연구 결과를 학회 구두발표(세미나·초청강연·학위심사 포함) 슬라이드 덱으로 만드는 스킬. 사용자가 "학회 발표자료 만들어줘", "이 논문으로 발표 슬라이드", "20분 발표 30장", "conference talk", "seminar slides", "발표 덱", "구두발표 준비" 또는 논문 폴더·원고 파일을 주며 발표·슬라이드·PPT를 언급하면 반드시 이 스킬을 사용하라. 논문 figure를 그대로 쓰는 발표라면 사용자가 스킬 이름을 말하지 않아도 트리거한다. 핵심은 자산(그림) 원장 → 고정 그리드 빌더(pptxgenjs) → 자동 QA의 3단 파이프라인으로, 그림 비율·크기·위치를 먼저 재고 레이아웃을 고르며, 제목·띠·결론문 위치가 모든 슬라이드에서 같고, 원고의 철회 주장이 텍스트와 그림 안 문구 어디에도 들어가지 않게 한다. 강의 슬라이드(15주 수업자료)는 이 스킬이 아니라 marp-slide를 쓴다.
---

# camp-talk — 학회 구두발표 덱

이 스킬은 2026-09-10 비교테스트(academic-pptx / marp-slide / scholar-slides / 스킬 없음, 같은 논문·같은 개요)에서 사용자가 좋게 본 것과 싫어한 것을 구조로 옮긴 것이다. 좋았던 것: Marp의 깨끗한 타이포와 남색 띠, academic-pptx의 "한 슬라이드 한 exhibit, 데이터를 크게". 싫었던 것: 소제목 위치가 매번 바뀌고, 세로 가운데 정렬로 위아래가 비고, 그림이 늘려지거나 줄여져 깨지고, 그림 크기를 재지 않고 배치하는 것. 그래서 이 스킬에서는 **모델이 좌표를 잡지 않는다.** 모델은 자산을 재고, 사실을 확인하고, `deck_spec.json`을 쓴다. 좌표·비율·정렬은 `${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/build_deck.js`가 고정 그리드로 결정하고, `${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/deck_qa.py`가 결과를 검사한다.

## 설치 후 처음 한 번 (의존성)

플러그인으로 설치한 직후에는 빌더의 Node 의존성이 아직 없다. 덱을 처음 만들기 전에 한 번만 실행한다.

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts && npm install --omit=dev
pip install -r ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/requirements.txt
```

- Node 18 이상 (`npm install`이 `pptxgenjs` 3.12.0 · `sharp` · `image-size`를 받는다)
- Python 3.11 이상 (`requirements.txt` = python-pptx · pillow · pymupdf · numpy)
- LibreOffice — `render_deck.py`가 pptx를 PDF로 바꿀 때만 쓴다. 없으면 렌더·QA의 픽셀 검사를 건너뛰고 빌더 경고만 본다.

`npm install`이 실패하면(사내망 프록시·sharp 바이너리) 빌더는 돌지 않는다. 렌더 단계만 빠지는 LibreOffice 부재와 다르다.

## 파일 지도

| 읽을 때 | 파일 |
|---|---|
| 슬라이드 순서·장수·언어·제목 형식 정할 때 | `${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/references/deck-conventions.md` (사용자 과거 덱 12건 실측 관례) |
| 그림 상자 좌표·레이아웃 이름·fit 규칙·색 | `${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/references/layout-grid.md` |
| `deck_spec.json` 필드 | `${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/references/spec-schema.md` |
| 빌더·QA 실행법과 경고 코드 | `${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/README.md` |

## 파이프라인 (순서대로, 건너뛰지 말 것)

### 0. 입력 확인 (30초)
- 원고(md/docx/pdf), 그림 원본(figure set pptx, SI pptx, mockup PNG), 논문 폴더의 `_paper.md`류 트래커.
- 발표 길이·학회 종류(국내/국제)·언어. 말이 없으면: 20분·국내·`lang: ko`(서론·결론 한글, 결과 슬라이드 영어). 장수는 0.8분/장 → 20분이면 본편 30장 + Appendix 5장.
- 산출 폴더: 논문 폴더 아래 `talk/[YYMMDD_v_n]/` (paper-autopilot 버전 관례). 그 안에 `source_pack.md`, `asset_ledger.json`, `figures_cropped/`, `deck_spec.json`, `deck.pptx`, `render/`, `qa_report.json`, `notes.md`.

### 1. 소스 팩 — 사실·수치·철회 주장
원고를 읽고 `source_pack.md`를 쓴다: 한 문단 요약, 핵심 메시지 3개, 주장–증거 원장(값·단위·조건·출처·신뢰도 확정/soft/제안), **쓰지 말 것 표**(트래커의 철회·폐기 서사, 단일 seed artifact, 미측정 주장, 축이 원고와 다른 패널), Methods 5줄, 예상 Q&A 5개. 신뢰도가 soft인 수치는 "consistent with"로만, 제안 단계 메커니즘은 "we propose"로만 쓴다. 이 표의 금지 문자열은 나중에 `deck_spec.json`의 `forbidden` 배열이 된다.

원고를 다시 읽지 않아도 덱을 만들 수 있을 만큼 자기완결적으로 쓴다. 이 단계를 대충 하면 뒤의 모든 슬라이드가 원고를 잘못 인용한다.

### 2. 자산 원장 — 그림을 먼저 잰다 (이 스킬의 핵심)
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/asset_ledger.py <figures_dir> --out asset_ledger.json [--crops crops.json] [--autotrim]
```
원본을 고르는 순서가 먼저다. 논문 폴더에 figure set pptx(패널이 EMF/OLE 그래프로 들어 있는 것)가 있으면 이미 있는 2400 px 렌더를 쓰지 말고 **`render_deck.py --dpi 600`으로 다시 렌더**해 4500 px급 원본을 만든다(pptx→PDF 단계에서 EMF/OLE 그래프가 벡터로 남으므로 dpi를 올리면 글자가 그대로 선명해진다). 2400 px 렌더에서 잘라낸 패널은 축 눈금이 8–14 px라 해상도 게이트(110 ppi)와 글자 게이트(0.12 in)를 동시에 만족할 수 없고(교집합 조건 = 원본 최소 글자 13.2 px, `layout-grid.md` §3-6), 그 뒤에 무엇을 해도 흐리거나 작다. crop 상자 좌표는 **원본 px 기준**이며 autotrim보다 먼저 적용된다(trim 사본을 보고 잰 좌표는 `--crops-from-trim`으로).
원장은 그림마다 px·AR·class(wide/landscape/square/tall)·권장 layout·110 ppi 기준 최대 배치 폭·여백 비율·캡션 밴드 의심 여부를 준다. `--autotrim`은 항상 켠다: SI 덱이나 figure set의 슬라이드 렌더는 그림 주위에 흰 여백과 인쇄된 캡션("Figure S21. Contact angle…")이 있어서 그대로 놓으면 사진이 슬라이드의 한 귀퉁이에 작게 박힌다(빌드 게이트 TEXT_TINY·FILL_LOW가 잡지만, 원장 단계에서 잘라 두는 것이 순서다). 여백 비율이 15%를 넘거나 캡션 밴드가 의심되면 trim 사본이나 crop 패널을 쓰고, 원본은 쓰지 않는다. 그 다음 **모델이 직접 그림을 하나씩 열어(Read)** 두 필드를 채운다:
- `min_text_px`: 그림 안 가장 작은 글자 높이(px). 글자가 없으면 `0`. 축 라벨이 작으면 큰 상자에 놓아도 안 보이고, 13.2 px 미만이면 재플롯이나 고해상 원본 외에는 답이 없다.
- `embedded_text_check`: 그림 안에 인쇄된 문구 확인. 철회 주장·폐기 어휘(예: "load re-routing", "fines")·이전 버전 캡션 밴드가 있으면 `"contains: ..."`로 적고 크롭으로 잘라낸다. 비교테스트에서 4개 워커 중 2개만 이 배너를 잡았고, 텍스트 검사로는 절대 잡히지 않는다. QA는 `embedded_text_check`가 `ok`가 아닌 자산을 쓴 슬라이드를 fail로 낸다.

조립 figure(패널 a–l 한 장)는 통째로 쓰지 않는다. `crops.json`에 패널별 상자를 적어 잘라내고, 잘라낸 패널이 800 px 안팎이면 폭 7 in 이상 배치는 흐려진다는 것을 원장의 최대 배치 폭에서 확인한다. 그림 하나가 한 장의 exhibit이다. 패널이 9개 몰린 몽타주는 두세 장으로 나눈다.

### 2b. 자산 계획 — 있는 것 / 만들 것 / 어디에 놓을 것
개요(3단계)를 잡기 전에 `asset_plan.md`를 쓴다. 세 표로 이루어진다.

1. **있는 자산**: 원장의 id 중 발표에 쓸 것. 각각 용도(Main/Backup)와 손질(crop·autotrim·배너 제거).
2. **만들 자산(gap)**: 개요의 슬라이드가 요구하지만 원고에 없는 그림. 종류별로 만드는 방법을 정한다.
   - 개념 도식(문제 정의, 연구 전략 지도, 조성 흐름): `deck_spec.json`의 `diagram` 블록으로 빌더가 네이티브 도형으로 그리거나(편집 가능, 기본), 복잡하면 `/ppt-image`(3D scheme은 `--model pro`) 또는 vesta 플러그인(결정구조).
   - 재플롯: 원고 본문 값과 축이 다른 패널(예: tortuosity bar)은 원고 값으로 matplotlib 재플롯하고 캡션에 "re-plot of manuscript values, not a paper panel"을 적는다.
   - 표: 수치가 3행 이상이면 그림 대신 `table` 블록.
   - 만든 자산도 원장에 넣고(`origin: replot | diagram | generated`) 같은 게이트를 통과시킨다.
3. **배치 지도**: 슬라이드 번호 ← 자산 id 1–3개 + layout. 한 자산이 두 슬라이드에 들어가면(표지 배경과 개념 슬라이드처럼) 명시한다. 어느 슬라이드에도 배정되지 않은 Main 자산과, 자산이 없는 결과 슬라이드는 여기서 드러난다.

이 계획이 있어야 "그림을 먼저 재고 레이아웃을 고른다"가 실제로 일어난다. 계획 없이 개요부터 쓰면 슬라이드가 그림을 부르고, 그림이 없으면 텍스트로 때우게 된다.

### 3. 개요 — 사용자 골격에 얹는다
`${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/references/deck-conventions.md`의 순서를 따른다: 표지 → 목차 → (국내) 소개 → Ⅰ 산업 배경 → Ⅱ 문제·전략 → Ⅲ~ 결과 블록 → 텍스트 결론 → 감사 → Appendix. 절이 바뀔 때 `{"type":"section"}` 슬라이드를 넣으면 빌더가 목차를 다시 그린다. 슬라이드마다 다음을 정한다: 명사구 제목, 하단 한 줄 결론문(완전한 문장), 자산 1–3개(원장 id), 불릿 ≤5, 노트 60–120단어. 20분 덱의 시간 배분은 서론 3분 / 문제 2.5분 / 결과 12분 / 결론 1.5분 / 감사 0.5분.

수치를 넣을 때는 소스 팩의 신뢰도를 그대로 옮긴다. "simulated", "3/3 seed", "consistent with" 같은 수식어는 슬라이드 본문에 남긴다. 청중은 원고를 못 보므로 슬라이드가 곧 주장이다.

### 4. deck_spec.json 작성
`${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/references/spec-schema.md` 그대로. `layout`은 원장의 권장값을 쓰되 그림이 둘이면 `two-up`/`figure-stack`, 수치 표가 있으면 `figure-table`. `forbidden`에 소스 팩의 금지 문자열 전부. 모든 content/appendix/conclusion에 `notes`.

### 5. 빌드 → 렌더 → QA
```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/build_deck.js deck_spec.json deck.pptx          # 편집 가능 pptx + deck.build.json(경고)
python ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/render_deck.py deck.pptx --out render --sheet 1,2,14,20,25,29
python ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/deck_qa.py deck.pptx --spec deck_spec.json --ledger asset_ledger.json --build deck.build.json --render render --out qa_report.json
```
`deck_qa.py`의 `--forbidden` 값이 `-`로 시작하면(예 `-37%`) `--forbidden=-37%,re-routing`처럼 `=`를 붙인다. 스펙에 `forbidden`을 넣었으면 이 옵션은 필요 없다.

빌더 경고(FILL_LOW, PPI_LOW, TEXT_TINY, BULLET_OVERFLOW)는 스펙을 고쳐서 없앤다: 채움률이 낮으면 layout을 바꾸거나 그림을 크롭, ppi가 낮으면 상자를 줄이거나 재플롯, 불릿이 넘치면 슬라이드를 나눈다. 폰트를 줄이거나 그림을 늘려서 해결하지 않는다. QA fail(TITLE_Y_FIXED, IMAGE_AR, IMAGE_TOP_ALIGNED, FORBIDDEN, LEDGER_TEXT_CHECK)은 빌더 버그가 아니면 스펙 오류다.

그 다음 `render/contact_sheet.png`와 지정 슬라이드 6장 이상을 Read로 열어 눈으로 본다: 한글 깨짐, 그림 안 잘린 라벨, 캡션 겹침, 빈 아래쪽. 자동 검사는 좌표만 보고 내용은 못 본다.

### 6. 산출과 보고
- `deck.pptx`(발표·편집용), `render/`(검토용), `notes.md`(pptx 노트와 동일 내용), `qa_report.json`.
- 사용자에게는 contact sheet 경로, QA 요약(pass/warn/fail 수), 소스 팩 §"쓰지 말 것"에 걸려 뺀 항목, 미확정 자리표시자(학회명·세션·지원기관)를 보고한다. 검토는 html 아티팩트(같은 슬라이드 나란히 보기 + 결정 체크박스)로 주는 것이 사용자 관례다.

## 하지 말 것
- pptxgenjs `sizing: contain`이나 직접 좌표로 그림을 놓는 것 — 빌더를 우회하면 정렬·비율 게이트가 빠진다.
- 슬라이드 전체를 이미지로 굽는 것(Marp 기본 pptx, 이미지 생성 모델) — 발표 직전 수정이 불가능하다.
- 문장형 action title을 제목에 쓰는 것 — 사용자 관례는 명사구 제목 + 하단 결론문이다.
- 결론 뒤에 감사 없이 끝내는 것, Appendix를 감사 앞에 두는 것.
- 원장에서 `embedded_text_check`를 안 채우고 그림을 쓰는 것.

## 의존성
Node 18+ (`${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/package.json`: pptxgenjs, sharp), Python 3.11+ (python-pptx, pillow, pymupdf, numpy), LibreOffice(렌더). 공식 `pptx` 스킬의 `pptxgenjs.md`는 빌더를 고칠 때만 참고한다.
