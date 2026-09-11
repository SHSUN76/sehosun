---
name: ppt-image
description: PPT 슬라이드 이미지를 Gemini/OpenAI 이미지 모델로 생성하는 스킬. 마크다운 초안(## Slide N)을 읽어 슬라이드별 4K 이미지를 만든다. 사용자가 "PPT 슬라이드 이미지 생성", "/ppt-image", "슬라이드 이미지 만들어줘", "목업 이미지", "다이어그램 이미지 만들어줘", "infographic", "계획서 인포그래픽", "3D scheme 그려줘", "발표 이미지 생성"을 말하거나 이미지 사양 마크다운(image-specs.md)을 주며 이미지 생성을 요청하면 반드시 이 스킬을 사용하라. 쓰지 않을 때 - 결정구조 렌더(vesta), Origin 그래프(origin), 편집 가능한 pptx 덱 조립(camp-talk).
---

# /ppt-image - PPT 슬라이드 이미지 생성 (v5.1)

> **v5.1: v5.0 + OpenAI 이미지 모델(`--model openai`) 지원**

PPT 초안 마크다운 파일을 기반으로 Gemini(기본) 또는 OpenAI 이미지 모델을 사용해 고해상도 슬라이드 이미지를 생성합니다.

**버전 이력**
- **v5.1**: OpenAI 이미지 모델(`--model openai`, `gpt-image-2`) 지원
- **v5.0**: v3.1의 모델 선택/재시도/참조 이미지 체계 + v4의 Agent Enrichment/슬라이드별 비율 혼합/infographic 모드 통합
- **v3.1**: 모델 선택 — `--model flash` (기본, `gemini-3.1-flash-image-preview`, ~$0.03/장) / `--model pro` (`gemini-3-pro-image-preview`, ~$0.24/4K)
- **v4**: Agent Enrichment (문서 컨텍스트 기반 프롬프트 강화), 슬라이드별 비율 지정(16:9/9:16/1:1 혼합), `infographic` 모드
- **v3**: 내용 유형 자동 감지 (flowchart/table/chart/hierarchy/equation/title/bullet), thinkingConfig high, exponential backoff 자동 재시도 (429/500/503/timeout, 최대 3회)
- **v2**: `--ref` 옵션 — Tavily API로 웹에서 관련 다이어그램/그래프를 검색하여 참조 이미지로 활용

## 필수 제약 (사용자 지정)

1. **3D scheme / scientific figure 생성 시 반드시 `--model pro` (flash 금지)**
2. **/ppt-image는 반드시 subagent에서 격리 실행 (context 오염 방지), 병렬 실행 시 파일명 충돌 주의** — 이미지 생성 로그·프롬프트가 메인 세션 컨텍스트를 오염시키지 않도록 전체 실행을 subagent에 위임하고, 병렬 배치는 `--slides` 집합이 겹치지 않게 분리할 것 (같은 슬라이드를 두 배치가 동시에 쓰면 `{style}_slide_{number}_{ratio}.png`가 충돌)

## API 키 설정 (처음 한 번)

키는 다음 순서로 해석된다. 앞에서 찾으면 뒤는 보지 않는다.

1. 프로세스 환경변수 — Claude Code `~/.claude/settings.json` 의 `env` 블록에 `GEMINI_API_KEY` 를 넣는 것이 가장 간단하다
2. `${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/.env`
3. `~/.ppt-image.env` (홈 폴더, `KEY=value` 한 줄씩)

필요한 키: `GEMINI_API_KEY`(기본 경로), `OPENAI_API_KEY`(`--model openai`), `TAVILY_API_KEY`(`--ref`).
Node 18 이상이면 추가 설치 없이 돈다 (스크립트는 Node 내장 모듈만 쓴다).

## 사용법

```
/ppt-image <markdown_file_path> [options]
```

## 실행 워크플로우

### Step 1: 입력 확인 및 옵션 결정

마크다운 파일에서 `## Slide N` / `## 섹션명` 패턴으로 슬라이드를 인식하고 개수를 보고합니다. 인라인으로 지정되지 않은 옵션은 AskUserQuestion으로 확인:

1. **모델**: `flash` (기본, ~$0.03/장, 4K 지원) vs `pro` (~$0.24/장, 고밀도 텍스트·포토리얼 우수) vs `openai` (~$0.21/장, GPT Image 2)
   - 텍스트 중심 / 카드 레이아웃 / 타이포 → **flash** 충분
   - 3D scheme, 포토리얼 인물, 복잡 합성, 고밀도 텍스트 렌더링 → **pro**
   - 슬라이드 내 정확한 문자열 렌더링(다국어 라벨·수식·표 텍스트)이나 지시 준수가 최우선 → **openai** (단 `--size`/`--ref` 미지원, 최대 1536×1024)
2. **모드**: `full-slide` (전체 슬라이드) / `diagram` (다이어그램만) / `infographic` (계획서/보고서용, 밀도 높음)
3. **스타일**: professional / academic / tech / minimal / science
4. **언어**: en / kr
5. **참조 이미지**: `--ref` 활성화 여부
6. **문서 컨텍스트**: `--context <폴더경로>` — Enrichment agent가 참조할 원본 문서 폴더
7. **특정 슬라이드만?**: 전체 또는 특정 번호 지정

기본값: `--model flash --mode full-slide --size 4K --ratio 16:9 --style professional --lang en`

### Step 2: Agent Enrichment (조건부 — 스크립트 실행 전)

이미지 프롬프트를 원본 문서 내용으로 강화하는 단계. 실행 조건:
- `--context <폴더>` 옵션이 있으면 항상
- `--mode infographic`이면 항상
- 슬라이드 프롬프트가 5줄 미만으로 짧으면 실행 제안

**Enrichment agent의 목표**: image-specs.md의 슬라이드별 의도 + context 폴더의 문서(*.md)를 읽고, 각 프롬프트를 다음 기준으로 강화하여 `{원본폴더}/image-specs-enriched.md`로 저장한다.

- 이미지에 들어갈 모든 텍스트/수치를 프롬프트에 명시 (Gemini는 프롬프트에 있는 텍스트만 그림)
- 추상적 지시("~처럼") 대신 구체적 레이아웃 기술 (상단/중단/하단, 좌/우 컬럼)
- 표는 행/열 내용 전부 나열
- 숫자는 원본 문서에서만 추출 — 추정치 금지, 원본에 없으면 빈칸
- 비공식 코멘트(PI 코멘트, 대화 내용) 제거 — 공식 문서 내용만
- 모드별 밀도: `full-slide/diagram`은 간결(키워드 중심), `infographic`은 밀도 높음(표+차트+텍스트 복합) — 프롬프트 길이 가이드: 일반 15줄+, infographic 30줄+
- 슬라이드별 비율 감지: 프롬프트에 "A4", "세로", "portrait", "9:16" 키워드가 있으면 해당 슬라이드를 9:16으로 분류

Enrichment는 Agent 도구로 별도 subagent(executor급)에 위임: 입력 = image-specs.md + context 폴더의 .md 파일들, 출력 = image-specs-enriched.md + 비율별 배치 실행 계획.

### Step 3: 비율별 배치 분할

image-specs-enriched.md (또는 원본)를 비율별로 분류하여 배치별 `--ratio`로 실행:

- **9:16 배치**: "A4", "세로", "portrait", "9:16" 키워드가 있는 슬라이드
- **1:1 배치**: 정사각형 지정 슬라이드
- **16:9 배치**: 나머지

배치는 병렬 실행(백그라운드) 가능 — 단, 필수 제약 2 참조: 배치 간 `--slides` 집합이 겹치지 않아야 한다.

### Step 4: 스크립트 실행

#### 기본 (Flash)
```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/generate_ppt_slides.js "<markdown_path>" --model <model> --mode <mode> --size 4K --ratio 16:9 --style <style> --lang <lang>
```

#### Pro 모델 (고품질 / 3D scheme)
```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/generate_ppt_slides.js "<markdown_path>" --model pro --mode <mode> --size 4K --ratio 16:9 --style <style> --lang <lang>
```

#### OpenAI 모델 (GPT Image 2 — 정확한 텍스트 렌더링)
```bash
# --size/--ref 는 무시됨. 해상도는 --ratio 로 결정 (16:9·4:3 → 1536×1024, 9:16 → 1024×1536, 1:1 → 1024×1024)
node ${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/generate_ppt_slides.js "<markdown_path>" --model openai --mode <mode> --ratio 16:9 --style <style> --lang <lang>
```

#### 참조 이미지 모드 (웹 검색 + multimodal)
```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/generate_ppt_slides.js "<markdown_path>" --model <model> --mode <mode> --size 4K --ratio 16:9 --style <style> --lang <lang> --ref --ref-count <N> --ref-save
```

#### 비율별 배치 (enriched 파일 기준)
```bash
# 9:16 배치
node ${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/generate_ppt_slides.js "image-specs-enriched.md" --model <model> --mode <mode> --size 4K --ratio 9:16 --style <style> --lang <lang> --slides 1,2,3

# 16:9 배치
node ${CLAUDE_PLUGIN_ROOT}/skills/ppt-image/scripts/generate_ppt_slides.js "image-specs-enriched.md" --model <model> --mode <mode> --size 4K --ratio 16:9 --style <style> --lang <lang> --slides 8,11,12
```

#### 혼합 전략 (비용 최적화)
전체는 flash, 중요 슬라이드만 pro로 재생성:
```bash
# 1차: 전체를 flash로
node ... "draft.md" --model flash

# 2차: 특정 슬라이드만 pro로 덮어쓰기 (파일명이 달라지므로 수동 교체)
node ... "draft.md" --model pro --slides 8,28
```

### Step 5: 결과 보고

생성 이미지 목록·저장 경로, 성공/실패 수, 비율별 분류를 보고. 실패한 슬라이드는 원인과 함께 재시도를 제안.

**생성 결과 검수**: 이미지 전체를 한 번 보는 것만으로는 글자 깨짐이나 환각으로 들어간 기관명·대학명을 놓친다. 라벨·수식·표 텍스트가 의심스러우면 PIL로 그 영역만 잘라 확대해 다시 보라 — 조밀한 도표는 잘라서 확대해 보는 반복이 있을 때 가장 정확하게 읽힌다. 판독에 필요한 만큼 crop을 반복해도 된다.

```python
from PIL import Image
im = Image.open(path)
w, h = im.size
im.crop((int(w*0.0), int(h*0.0), int(w*0.5), int(h*0.3))).resize((w, int(h*0.6))).save(crop_path)
```

---

## 옵션 상세

### 기본 옵션

| 옵션 | 값 | 설명 |
|------|---|------|
| `--model` | `flash` | **기본** · `gemini-3.1-flash-image-preview` (Nano Banana 2) · 4K 지원 · ~$0.03/장 |
| `--model` | `pro` | `gemini-3-pro-image-preview` (Nano Banana Pro) · 고품질/고밀도 텍스트 · ~$0.24/4K · **3D scheme 필수** |
| `--model` | `openai` | `gpt-image-2` (GPT Image 2, 2026-04-21) · 강한 텍스트 렌더링/지시 준수 · 최대 1536×1024 · ~$0.21/장(high) · **`--size`/`--ref` 미지원** |
| `--mode` | `full-slide` | 제목+내용+다이어그램 포함 전체 슬라이드 |
| `--mode` | `diagram` | 핵심 다이어그램/일러스트만 (PPT 삽입용) |
| `--mode` | `infographic` | 계획서/보고서용 밀도 높은 인포그래픽 (Enrichment 자동) |
| `--size` | `4K` | 4K 해상도 (기본값, 권장) |
| `--size` | `2K` | 2K 해상도 (빠른 생성) |
| `--ratio` | `16:9` | PPT 와이드스크린 (기본값) |
| `--ratio` | `9:16` | A4 세로 (계획서/보고서 풀페이지) |
| `--ratio` | `4:3` | PPT 표준 |
| `--ratio` | `1:1` | 정사각형 |
| `--ratio` | `auto` | 슬라이드별 프롬프트에서 비율 자동 감지 |
| `--style` | `professional` | 기업 발표용 깔끔한 디자인 |
| `--style` | `academic` | 학술 발표용 |
| `--style` | `tech` | 테크/스타트업 (다크 배경) |
| `--style` | `minimal` | 미니멀 (최대 여백) |
| `--style` | `science` | 과학/연구 발표용 |
| `--lang` | `en` | 영어 텍스트 |
| `--lang` | `kr` | 한국어 텍스트 |
| `--slides` | `1,2,3` | 특정 슬라이드만 생성 |
| `--context` | `<폴더경로>` | Enrichment agent가 참조할 원본 문서 폴더 |
| `--parallel` | - | 병렬 생성 (API rate limit 주의) |
| `--dry-run` | - | 프롬프트만 확인, 이미지 미생성 |

### 참조 이미지 옵션

| 옵션 | 값 | 설명 |
|------|---|------|
| `--ref` | - | 참조 이미지 검색 활성화 (Tavily API 사용) |
| `--ref-count` | `2` (기본) | 슬라이드당 참조 이미지 수 (최대 4) |
| `--ref-save` | - | 다운로드한 참조 이미지를 `_ref_images/` 폴더에 저장 |

### 참조 이미지 작동 원리

```
슬라이드 내용 분석
    ↓
키워드 자동 추출 (제목 + 볼드 텍스트 + 기술 용어)
    ↓
Tavily API로 관련 다이어그램/그래프 이미지 검색
    ↓
이미지 다운로드 (최대 4MB/장, 자동 필터링)
    ↓
Gemini multimodal input으로 [참조 이미지 + 텍스트 프롬프트] 결합
    ↓
참조 스타일을 반영한 정확한 기술적 시각화 생성
```

**참조 이미지는 직접 복사되지 않습니다** — Gemini가 참조 이미지의 시각 스타일, 차트 유형, 다이어그램 레이아웃을 학습하여 새로운 원본 시각화를 생성합니다.

---

## 마크다운 형식 요구사항

슬라이드 구분은 다음 패턴 중 하나를 사용:

```markdown
## Slide 1: Title Here
(content)

## Slide 2: Another Title
(content)
```

또는:

```markdown
## 슬라이드 1: 제목
(내용)

## 슬라이드 2: 다른 제목
(내용)
```

일반 `## 섹션명` 헤딩도 자동 인식됩니다.

### 슬라이드별 비율 지정 (선택)

프롬프트 내에 비율 키워드를 포함하면 `--ratio auto` 모드에서 자동 감지:

```markdown
## Slide 1: 비전 체계도
비율: 9:16 (A4 세로)
(내용)

## Slide 2: 비교표
비율: 16:9
(내용)
```

---

## 출력

- 기본 모드: `{style}_slide_{number}_{ratio}.png`
- 참조 모드: `{style}_slide_{number}_{ratio}_ref.png`
- 참조 이미지 (--ref-save): `_ref_images/slide_{number}_ref_{n}.{ext}`
- enriched 프롬프트: `image-specs-enriched.md` (Enrichment agent가 생성)
- 로그: `slide_generation_log.json`
- 저장 위치: 원본 마크다운과 같은 폴더

## 기술 사양

- **모델 (기본)**: `gemini-3.1-flash-image-preview` (Nano Banana 2, 2026.02 출시)
- **모델 (옵션)**: `gemini-3-pro-image-preview` (Nano Banana Pro) — `--model pro`로 전환
- **모델 (옵션)**: `gpt-image-2` (OpenAI GPT Image 2, 2026-04-21 출시) — `--model openai`로 전환
- **해상도**: Gemini는 4K (최대 4096x4096px) 지원 / **OpenAI는 `--size` 무시** — 종횡비→고정 해상도 매핑 사용 (16:9·4:3 → 1536×1024, 9:16 → 1024×1536, 1:1 → 1024×1024, 최대 3840×2160 지원이나 안정성 위해 표준값 사용)
- **Google Search**: Gemini 경로만 활성화 (기술 컨텐츠 참조용) — **OpenAI 경로에서는 미사용**
- **Thinking**: high (고수준 추론, Gemini 경로)
- **내용 유형 감지**: flowchart, table, chart, hierarchy, equation, title, bullet-list (provider 공통)
- **자동 재시도**: exponential backoff, 최대 3회 (429/500/503/timeout) — Gemini/OpenAI 공통 래퍼
- **참조 이미지 검색**: Tavily API (include_images) — **OpenAI 경로에서는 `--ref` 미지원(경고 후 참조 없이 진행)**
- **Multimodal Input**: inlineData (base64) + text prompt (Gemini 경로) / OpenAI는 텍스트→이미지, 응답은 b64_json PNG
- **비용 (1장 기준, 2026-04)**:
  - Flash (기본): ~$0.03 (4K) / 참조 포함 ~$0.04
  - Pro: ~$0.24 (4K) / 참조 포함 ~$0.30
  - OpenAI (`gpt-image-2`): ~$0.21 (high, 1024×1024 기준) — 토큰 과금($8/1M 입력, $30/1M 출력)
- **50장 기준 총비용**: Flash ~$1.5 / Pro ~$12 / OpenAI ~$10.5

## 모드 비교

### 콘텐츠 모드

| 항목 | full-slide | diagram | infographic |
|------|-----------|---------|-----------------|
| 용도 | PPT 발표 | PPT 삽입 다이어그램 | 계획서/보고서 풀페이지 |
| 정보 밀도 | 중간 | 낮음 | **높음** |
| 텍스트 양 | 제목+불릿 | 최소 | **표+차트+텍스트 복합** |
| Agent Enrichment | 선택 | 선택 | **자동** |
| 비율 | 주로 16:9 | 16:9 또는 1:1 | **9:16(A4) + 16:9 혼합** |
| 프롬프트 길이 | 5-10줄 | 3-7줄 | **15-40줄** |

### 입력 모드

| 항목 | 기본 모드 | 참조 이미지 모드 (`--ref`) |
|------|----------|--------------------------|
| 입력 | 텍스트 프롬프트만 | 참조 이미지 + 텍스트 프롬프트 |
| 시각화 정확도 | Google Search grounding (텍스트만) | 실제 다이어그램/그래프 참조 |
| 소요 시간 | ~15초/슬라이드 | ~25초/슬라이드 (검색+다운로드 포함) |
| 비용 | 낮음 | 약간 높음 (Tavily API 추가) |
| 적합한 용도 | 일반 발표, 텍스트 중심 | 기술/과학 발표, 정확한 그래프 필요 시 |
| 필수 API Key | GEMINI_API_KEY | GEMINI_API_KEY + TAVILY_API_KEY |

## 예시

```
# 기본 사용 (Flash = 기본, 4K, 전체 슬라이드, professional)
/ppt-image "path/to/PPT_Draft.md"

# Pro 모델 명시 (3D scheme / 고품질 필요 시)
/ppt-image "path/to/draft.md" --model pro

# OpenAI GPT Image 2 (정확한 문자열 렌더링 / 지시 준수 우선, --size·--ref 무시됨)
/ppt-image "path/to/draft.md" --model openai --style academic

# 혼합 전략: 전체 flash + 특정 슬라이드만 pro로 재생성
/ppt-image "path/to/draft.md" --model flash
/ppt-image "path/to/draft.md" --model pro --slides 8,28

# 계획서 인포그래픽 — 문서 내용 기반 Enrichment
/ppt-image "path/to/image-specs.md" --mode infographic --context "path/to/sections/" --lang kr

# 비율 자동 감지 (A4 세로 + 16:9 혼합)
/ppt-image "path/to/specs.md" --ratio auto --mode infographic

# 참조 이미지 활용 (웹에서 관련 그래프/다이어그램 검색)
/ppt-image "path/to/draft.md" --ref

# 참조 이미지 3장 + 로컬 저장 + science 스타일
/ppt-image "path/to/draft.md" --ref --ref-count 3 --ref-save --style science

# 다이어그램만 + 참조 이미지
/ppt-image "path/to/draft.md" --mode diagram --ref --style science

# 한국어, 특정 슬라이드만, 참조 이미지
/ppt-image "path/to/draft_kr.md" --lang kr --slides 1,3 --ref

# 프롬프트만 미리보기 (참조 이미지 포함)
/ppt-image "path/to/draft.md" --ref --dry-run
```
