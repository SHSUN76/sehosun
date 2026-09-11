# camp-talk

논문·원고를 학회 구두발표 덱으로 만드는 스킬. 자산(그림) 원장 → 고정 그리드 빌더(pptxgenjs) → 자동 QA의 3단 파이프라인이며, 좌표·비율·정렬은 모델이 아니라 빌더가 결정한다.

## 설치

```bash
claude plugin marketplace add SHSUN76/sehosun
claude plugin install camp-talk@sehosun
```

## 전제 조건 (설치 후 한 번)

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts && npm install --omit=dev
pip install -r ${CLAUDE_PLUGIN_ROOT}/skills/camp-talk/scripts/requirements.txt
```

- Node 18 이상 — 빌더(`build_deck.js`)가 `pptxgenjs` 3.12.0 · `sharp` · `image-size`를 쓴다.
- Python 3.11 이상 — `python-pptx` · `pillow` · `pymupdf` · `numpy`.
- LibreOffice(선택) — `render_deck.py`의 pptx→PDF 렌더에만 필요하다. 없으면 픽셀 검사를 건너뛰고 빌더 경고만 본다.

## 사용

발표 자료를 만들어 달라고 말하면 스킬이 자동으로 트리거된다. 예: "이 논문으로 20분 학회 발표 덱 30장 만들어줘".

MIT License · Seho Sun (CAMP Lab, Yeungnam University)
