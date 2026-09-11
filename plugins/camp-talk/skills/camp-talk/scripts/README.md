# camp-talk deck builder

`build_deck.js`는 모델이 쓴 `deck_spec.json` 하나를 읽어 편집 가능한 16:9 pptx를 만드는 결정론적 빌더다.
좌표·폰트·색을 모델이 매번 손으로 잡지 않는다. 제목·상단 띠·결론문 위치는 모든 슬라이드에서 같고,
그림은 원본 비율을 유지한 채 상단 정렬로 상자에 맞춰지며, 채움률·해상도·글자 크기는 게이트로 검사된다.

정본은 `../references/layout-grid.md`(그리드·fit 규칙·색 토큰)와 `../references/spec-schema.md`(입력 스키마)다.
이 문서는 실행법 요약이다.

## 설치

```bash
cd .claude/skills/camp-talk/scripts
npm install          # pptxgenjs 3.12.0, sharp(크롭), image-size(원본 px 측정)
```

`node_modules/`는 `.gitignore`에 있다. `sharp` 설치가 실패한 환경에서는 크롭이 있는 자산에서만 에러가 나고,
크롭 없는 빌드는 `image-size`만으로 정상 동작한다.

## 실행

```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/build_deck.js <spec.json> <out.pptx> [--strict]
```

* `out.pptx` — 덱
* `out.build.json` — 슬라이드별 `{index, type, number_label, layout_chosen, layout_auto, diagram("<kind>"|null), assets[{path, native_px, native_ar, placed_in, placed_ar, scale_ppi, fill_ratio}], warnings[]}` + 총 슬라이드 수·본편 수·경고 목록
* `<out dir>/_build/crops/` — `crop`이 지정된 자산의 잘린 PNG

종료 코드

| 코드 | 뜻 |
|---|---|
| 0 | 빌드 완료(경고 있어도 0) |
| 2 | 스키마 오류 또는 `forbidden` 문자열 발견 — 아무것도 쓰지 않고 위치를 출력 |
| 3 | `--strict`인데 경고가 하나라도 있음 |

예:

```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/build_deck.js examples/sample_spec.json examples/sample.pptx
```

## 스키마 요약

전체 필드는 `../references/spec-schema.md`가 정본이다. 빌더가 강제하는 것만 적는다.

| 키 | 필수 | 비고 |
|---|---|---|
| `meta.title` | ✔ | `lang`은 `ko`(Malgun Gothic) 또는 `en`(Arial). 기본 `ko` |
| `sections[].id` / `.label` | ✔ | id 중복 불가. band 좌측에 `"{id}. {label}"`로 찍힘 |
| `slides[].type` | ✔ | `title` `toc` `intro` `section` `content` `conclusion` `thanks` `appendix` |
| `slides[].title` | content·intro·appendix·conclusion 필수 | 26 pt 한 줄 폭이 12.0 in 초과면 22 pt로 축소(제목은 두 줄 금지) |
| `slides[].section` | content·section 필수 | `sections[].id`와 일치해야 함 |
| `slides[].layout` | — | `auto` 또는 layout-grid §2의 9종 |
| `slides[].assets[].path` | 자산 있으면 필수 | 스펙 파일 기준 상대경로 또는 절대경로 |
| `slides[].assets[].crop` | — | `[x0, y0, x1, y1]`(원본 px), `x1>x0` `y1>y0` |
| `slides[].table` | — | `header` + `rows`(열 수 일치), `highlight_row`는 rows 인덱스 |
| `slides[].diagram` | — | 아래 참조. content·intro·appendix에서만 |
| `forbidden` | — | 모든 사람이 읽는 텍스트 필드를 검사(경로·id 제외) |

본문 크기는 상자 폭을 따라간다. 그림 옆 4.63 in 상자의 불릿은 16 pt, 전폭 `text-only` 슬라이드는
11.0 in 폭에 20 pt·줄간격 1.25·문단 뒤 8 pt(12.33 in 줄에 16 pt를 놓으면 성글어 보인다).
`conclusion`의 번호 항목은 18 pt·줄간격 1.25·항목 간 10 pt, Future work 줄은 14 pt다.
표는 그림과 함께면 우측 5.63 in에 12 pt, **표만 있으면 content 존 전폭에 행 높이 0.45 in·16 pt**로 놓인다.

`figure-top`의 텍스트 상자는 고정 y가 아니라 **그림 하단 + 캡션 + 0.20 in에서 시작해 6.45 in까지**다.
납작한 그림이 상자(h 3.10)를 다 못 채울 때 그림과 본문 사이에 죽은 띠가 생기지 않게 한다.
캡션은 아래에 있는 상자(다음 그림 상자·텍스트 상자·표 상자, 없으면 6.45 in)를 침범하지 않으며,
자리가 모자라면 캡션을 줄이는 대신 **그림을 캡션 높이만큼 줄여** 캡션 자리를 만든다.

`layout: "auto"`는 첫 자산의 AR로 고른다: AR ≥ 2.4 → `figure-top`, 1.2 ≤ AR < 2.4 → `figure-left`,
AR < 1.2 → `figure-right`. 자산 2개는 AR ≥ 1.5면 `figure-stack` 아니면 `two-up`, 3개는 `three-up`,
표가 있으면 `figure-table`, 자산이 없으면 `text-only`.

## 경고 코드

경고는 빌드를 막지 않는다(`--strict`일 때만 종료 코드 3). 전부 `out.build.json`의 `warnings`에 남는다.

| 코드 | 조건 | 대응 |
|---|---|---|
| `FILL_LOW` | 맞춘 그림 면적이 상자 면적의 55 % 미만 | layout을 그림 모양에 맞게 바꾸거나 그림을 크롭한다. 억지로 늘리지 않는다 |
| `PPI_LOW` | 배치 폭 기준 원본 해상도가 110 ppi 미만 | `figure-stack`·`two-up`으로 작게 놓거나 원본을 재플롯한다 |
| `TEXT_TINY` | 자산의 `min_text_px`가 슬라이드 상 0.12 in 미만으로 축소됨(`0`·`"none"`은 "그림에 글자 없음"이므로 검사하지 않음) | 축 라벨이 안 보이는 몽타주다. 두 장으로 나눈다 |
| `BULLET_OVERFLOW` | 불릿이 5개 초과 / 기본 크기로 상자에 안 들어가 2 pt 내림 / 내려도 넘침 / callout이 불릿 아래 0.15 in에 놓이면 6.45 in을 넘음 / 텍스트 상자 없는 레이아웃에 불릿을 넣음 | 슬라이드를 나눈다 |
| `NOTES_MISSING` | content·appendix·conclusion에 `notes`가 없음 | 구술 스크립트를 채운다 |
| `TITLE_LONG` | 제목이 26 pt 한 줄로 12.0 in을 넘음(22 pt로 자동 축소) | 명사구로 줄인다 |
| `TITLE_OVERFLOW` | 22 pt로도 12.0 in을 넘음 | 제목은 두 줄로 흘리지 않는다. 반드시 줄인다 |
| `ASSET_EXTRA` | 자산 수가 선택된 레이아웃의 그림 상자 수보다 많아 초과분이 버려짐 | 레이아웃을 바꾸거나 슬라이드를 나눈다 |
| `DIAGRAM_NO_BOX` | 그림 상자를 자산이 다 써서 diagram을 그릴 자리가 없음 | 자산을 줄이거나 diagram을 별도 슬라이드로 뺀다 |

`FORBIDDEN`은 경고가 아니라 **빌드 거부**다. 종료 코드 2와 함께 `slides[4].bottom_line: "23.6 %"` 형태로
위치를 출력하고 pptx를 쓰지 않는다. 검사 대상은 스펙의 텍스트뿐이다 — **그림 파일 안에 박힌 문구는
검사하지 못하므로** 철회된 주장이 figure 안에 남아 있는지는 자산 원장 단계에서 눈으로 확인해야 한다.

## diagram — 부족한 자산을 편집 가능한 도형으로 만들기

`assets` 대신 `diagram`을 주면 빌더가 그림 상자 자리에 네이티브 pptxgenjs 도형으로 그린다(이미지가 아니므로
PowerPoint에서 그대로 편집된다). 색·폰트는 layout-grid §5 토큰을 쓴다. 불릿이나 표가 함께 있으면 선택된
레이아웃의 그림 상자를 쓰고, diagram만 있는 슬라이드는 content 존 전체(12.33 × 4.95 in)를 쓴다.

**diagram은 배정된 상자를 채운다.** 상단 1 in만 쓰고 아래를 비우는 도식은 고정 그리드가 막으려는
바로 그 "세로로 비는 슬라이드"이므로, 각 종류가 상자 높이를 끝까지 쓰도록 크기를 계산한다
(sample 기준 content 존 채움률 63–98 %). 자산의 55 % 채움률 게이트는 diagram에 적용하지 않는다.

| kind | 상자를 채우는 방식 | 글자 |
|---|---|---|
| `flow` | 상자 AR < 1.3(세로로 긴 상자)이면 단계를 세로로 쌓고 아래 화살표로 잇는다(높이 n등분, 간격 0.25 in). 그 밖에는 한 줄로 배치하되 상자 폭이 2.0 in 미만이 되면 두 줄로 접는다(Z 순서: 오른쪽 → 아래, 높이 ≥ 1.8 in) | label 18 pt · sub 14 pt |
| `axis` | zone 띠가 상자 높이에서 눈금·캡션 몫(1.0 in)을 뺀 만큼 차지한다(≥ 0.9 in). 축선 4 pt | zone·tick·caption 14 pt |
| `cards` | 2개 → 2열, 3개 → 3열, 4개 → 2 × 2. 카드는 항상 상단 정렬. **그림·표와 figure 영역을 나눠 쓰면** 본문 2줄 이하일 때 카드 높이를 내용 기준(최소 1.6 in)으로 줄인다("빈 카드"가 채움률보다 나쁘다). **cards가 figure 영역을 혼자 쓰면**(불릿이 옆 텍스트 상자에 있어도 해당) 상자 높이를 그대로 쓰고 줄간격 1.3으로 카드 안을 채우며, 내용이 2줄 이하일 때만 상자 높이의 60 %까지 줄인다 | title 20 pt · body 16 pt |
| `compare` | 좌우 패널이 상자 전체 높이. 머리띠 0.60 in | title 20 pt · lines 16 pt |

diagram 안 모든 텍스트는 12 pt 이상이다. 캡션 10.5 pt와 footer 9 pt는 diagram 밖이므로 그대로 둔다.

```jsonc
// flow — 가로 화살표 흐름 2–5단계 (연구 흐름, 공정 순서)
"diagram": {"kind": "flow", "steps": [{"label": "DEM 처방", "sub": "granule 크기 창"}, {"label": "물성 검증", "sub": "저항·접촉각"}]}

// axis — 설계 변수의 적정 구간을 보이는 수직선(number line). zones의 from/to는 축 길이의 0–1 분수
"diagram": {"kind": "axis", "ticks": ["0", "0.6", "1.0", "2.0"], "zones": [{"from": 0, "to": 0.3, "label": "너무 작음"}, {"from": 0.3, "to": 0.5, "label": "적정 구간", "accent": true}], "caption": "설계 변수: D_agg / D_L"}

// cards — 2–4개 요건 카드. 상자가 좁으면 자동으로 세로로 쌓임
"diagram": {"kind": "cards", "items": [{"title": "불용성", "body": "카보네이트 전해액에 녹지 않을 것"}, {"title": "선택 결합", "body": "소립 표면에만 흡착할 것"}]}

// compare — 좌우 대비(대조군 vs 실험군). 우측이 accent 색 머리띠
"diagram": {"kind": "compare", "left": {"title": "PTFE 단독", "lines": ["이온 저항 27.62 Ω"]}, "right": {"title": "PTFE + BCC 25 %", "lines": ["이온 저항 21.30 Ω"]}}
```

## examples/

* `sample_spec.json` — 24장 스펙. 9종 레이아웃 전부, diagram 4종 전부, 크롭, 표, callout, appendix를 한 번씩 쓴다
* `forbidden_spec.json` — 위 스펙에 금칙어를 심은 것. 종료 코드 2 회귀 확인용
* 두 스펙이 가리키는 figure 파일은 저자 작업 폴더의 것이라 배포판에 없다. 스펙은 스키마 예시로 읽고, 빌드를 돌려 볼 때는 `assets` 경로를 본인 그림으로 바꾼다
* 플러그인 배포판에는 스펙 JSON 둘만 들어 있다. `sample.pptx`와 `render/slide_NN.png`은 용량(39 MB) 때문에 빠져 있으므로, 검수용 렌더가 필요하면 아래 명령으로 직접 만든다

렌더 재생성:

```bash
"/c/Program Files/LibreOffice/program/soffice.exe" --headless --convert-to pdf --outdir examples/render examples/sample.pptx
python -c "import pymupdf; d=pymupdf.open('examples/render/sample.pdf'); [d[i].get_pixmap(dpi=110).save('examples/render/slide_%02d.png'%(i+1)) for i in range(d.page_count)]"
```

왜곡 회귀 검사(원본 px AR 대 배치 AR):

```bash
python -c "
from pptx import Presentation; from PIL import Image; import io
p=Presentation('examples/sample.pptx'); w=0
for s in p.slides:
    for sh in s.shapes:
        if sh.__class__.__name__=='Picture':
            im=Image.open(io.BytesIO(sh.image.blob))
            w=max(w, abs(sh.width/sh.height - im.size[0]/im.size[1])/(im.size[0]/im.size[1])*100)
print('max AR deviation %.4f%%'%w)"
```

현재 최대 편차는 0.0125 %(EMU 반올림 한계)다. 1 %를 넘으면 fit 로직이 깨진 것이다.
