# deck_spec.json 스키마 — camp-talk

`${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/build_deck.js deck_spec.json out.pptx`가 읽는 입력. 모델은 슬라이드를 직접 그리지 않고 이 스펙만 쓴다. 좌표·폰트·색은 builder가 `layout-grid.md`대로 결정한다.

```json
{
  "meta": {
    "title": "A Cyclodextrin Co-Binder that ...",
    "subtitle": "소립을 선택적으로 결합시키는 사이클로덱스트린 공바인더",
    "presenter": "선세호 (Seho Sun)",
    "affiliation": "영남대학교 화학공학부 · CAMP Lab",
    "event": "2026 한국전기화학회 추계학술대회 · 2026. 11. · 구두발표",
    "lang": "ko",
    "theme": "navy",
    "footer": "camp.seho.prof"
  },
  "sections": [
    {"id": "Ⅰ", "label": "서론: 후막 건식 전극과 소립 문제"},
    {"id": "Ⅱ", "label": "문제 정의와 연구 전략"}
  ],
  "forbidden": ["-37%", "re-routing", "θ≈4"],
  "slides": [
    {"type": "title"},
    {"type": "toc"},
    {"type": "intro", "title": "발표자·연구실 소개: CAMP Lab", "bullets": ["..."], "notes": "..."},
    {"type": "section", "section": "Ⅱ"},
    {
      "type": "content",
      "section": "Ⅲ",
      "title": "Ⅲ-2. DEM result: granule size vs simulated peak contact force",
      "bottom_line": "granule 크기가 대립 지름과 같을 때 대립의 simulated peak force가 23.6 % 낮아진다 (3/3 seed)",
      "layout": "auto",
      "assets": [
        {"path": "figures_cropped/C07_fig1b_peakforce.png", "caption": "Fig. 1b — perL_p99 vs D_agg/D_L, 3 seeds", "ledger_id": "F03"}
      ],
      "bullets": ["Dispersed 4002 ± 361 nN → d100 3057 ± 102 nN", "..."],
      "callout": {"kind": "warn", "text": "simulated peak force의 감소이며 실제 균열 감소를 측정한 값이 아님"},
      "notes": "구술 스크립트 60–120단어"
    },
    {
      "type": "content", "section": "Ⅴ", "title": "Ⅴ-3. Ion transport & wettability", "bottom_line": "...",
      "layout": "figure-table",
      "assets": [{"path": "figures_cropped/C21_fig4e_nyquist.png", "caption": "Fig. 4e"}],
      "table": {"header": ["BCC", "R_ion (Ω)", "τ", "θ (°)"], "rows": [["0 %", "27.62", "1.26", "95.96"], ["25 %", "21.3", "1.23", "80.47"]], "highlight_row": 1},
      "notes": "..."
    },
    {"type": "conclusion", "title": "결론 및 향후 과제", "items": ["(1) ...", "(2) ...", "(3) ..."], "future": "granule 크기 실측 · PTFE add-on 대조 · ...", "notes": "..."},
    {"type": "thanks", "lines": ["감사합니다 · Q&A", "공동연구자: 오원진 외", "camp.seho.prof"]},
    {"type": "appendix", "title": "Appendix A. Load evenness (CV/Gini)", "layout": "figure-left", "assets": [{"path": "..."}], "bullets": ["..."], "notes": "..."}
  ]
}
```

## 필드 규칙

- `type`: `title` | `toc` | `intro` | `section` | `content` | `conclusion` | `thanks` | `appendix`
- `section`(content/appendix): `sections[].id`와 일치. band 좌측에 "Ⅲ. 계산: granule 크기 처방(DEM)"으로 찍힌다. appendix는 band에 "Appendix".
- `section` 타입 슬라이드는 builder가 목차를 다시 그리되 해당 절만 진하게 표시한다(사용자 습관: 절 전환 시 목차 재삽입). 별도 텍스트 불필요.
- `layout`: `auto` 또는 `layout-grid.md` §2의 이름.
- `assets[].caption`: 한 문단·**60자 이하**(넘으면 QA가 본문으로 분류해 10.5 pt 캡션이 FONT_MIN fail이 된다). 긴 설명은 불릿이나 노트로.
- `assets[].path`: 스펙 파일 기준 상대경로 또는 절대경로. `crop: [x0, y0, x1, y1]`(원본 px)을 주면 builder가 잘라서 `_build/` 아래에 저장하고 그것을 배치한다. `ledger_id`는 `asset_ledger.json`의 id로, 있으면 `min_text_px`·해상도 게이트에 쓴다.
- `bullets`: 최대 5개. `callout`: `kind` = `warn` | `note` | `key`, 그림 아래 또는 불릿 아래 한 줄 카드.
- `table`: header + rows(문자열), `highlight_row` 선택.
- `diagram`(assets 대신 쓸 수 있음, 빌더가 네이티브 도형으로 그려 편집 가능): 그림 상자 자리에 들어간다.
  - `{"kind": "flow", "steps": [{"label": "DEM 처방", "sub": "granule 크기"}, ...]}` — 가로 화살표 흐름 2–5단계.
  - `{"kind": "axis", "min": "0", "max": "2.0", "ticks": ["0", "0.6", "1.0", "2.0"], "zones": [{"from": 0, "to": 0.35, "label": "너무 작음"}, {"from": 0.35, "to": 0.65, "label": "적정", "accent": true}, {"from": 0.65, "to": 1, "label": "너무 큼"}], "caption": "설계 변수: D_agg / D_L"}` — 구간이 표시된 수직선.
  - `{"kind": "cards", "items": [{"title": "불용성", "body": "..."}, ...]}` — 2–4개 요건 카드.
  - `{"kind": "compare", "left": {"title": "...", "lines": [...]}, "right": {...}}` — 좌우 대비.
- `notes`: 발표자 노트. 모든 content/appendix/conclusion 슬라이드에 필수(builder가 비어 있으면 경고).
- `forbidden`: builder가 모든 텍스트 필드에서 검사해 발견 시 빌드를 거부한다.

## builder 출력

- `out.pptx`, `out.build.json`(슬라이드별 선택된 layout, 그림 배치 좌표·배율·ppi, 경고 목록), 종료 코드 0(경고 허용) / 2(forbidden 또는 스키마 오류).
