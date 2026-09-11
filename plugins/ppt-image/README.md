# ppt-image

마크다운 슬라이드 초안(`## Slide N`)을 읽어 Gemini(기본) 또는 OpenAI 이미지 모델로 4K 슬라이드 이미지·다이어그램·인포그래픽을 만드는 스킬.

## 설치

```bash
claude plugin marketplace add SHSUN76/sehosun
claude plugin install ppt-image@sehosun
```

## 전제 조건

- Node 18 이상. 스크립트는 Node 내장 모듈만 쓰므로 `npm install`이 필요 없다.
- API 키는 다음 순서로 해석된다: 프로세스 환경변수 → `${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/.env` → `~/.ppt-image.env`.
  - `GEMINI_API_KEY` — 기본 경로(flash/pro). Claude Code `~/.claude/settings.json`의 `env` 블록에 넣는 것이 가장 간단하다.
  - `OPENAI_API_KEY` — `--model openai`.
  - `TAVILY_API_KEY` — `--ref`(참조 이미지 검색).

## 사용

"슬라이드 이미지 만들어줘", "인포그래픽 만들어줘", "3D scheme 그려줘" 같은 요청에 자동 트리거된다. 3D scheme·과학 도식은 `--model pro`를 쓰고, 실행은 컨텍스트 오염을 막기 위해 subagent로 격리한다.

MIT License · Seho Sun (CAMP Lab, Yeungnam University)
