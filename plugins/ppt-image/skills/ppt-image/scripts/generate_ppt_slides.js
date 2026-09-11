/**
 * generate_ppt_slides.js - PPT 슬라이드 이미지 생성 스크립트 (v3)
 *
 * PPT 초안 마크다운을 파싱하여 Gemini 3 Pro Image Preview로
 * 4K 해상도 슬라이드 이미지를 생성합니다.
 *
 * v3: 이미지 품질 고도화
 *   - thinkingConfig: "high" 적용 (Gemini 고수준 추론)
 *   - 슬라이드 내용 유형 자동 감지 (flowchart/table/chart/hierarchy/equation/title/bullet)
 *   - 감지된 유형별 프롬프트 보강으로 시각화 정확도 향상
 *   - API 실패 시 exponential backoff 자동 재시도 (최대 3회)
 *
 * v2: 참조 이미지 검색 기능 추가 (Tavily API)
 *   - --ref 플래그로 웹에서 관련 다이어그램/그래프를 검색하여 참조 이미지로 활용
 *   - Gemini multimodal input으로 참조 이미지 + 텍스트 프롬프트 결합
 *
 * 사용법:
 *   node generate_ppt_slides.js <markdown_path> [options]
 *
 * 옵션:
 *   --mode full-slide    전체 슬라이드 이미지 생성 (기본값)
 *   --mode diagram       다이어그램/일러스트만 생성
 *   --size 4K            해상도: 1K, 2K, 4K (기본: 4K)
 *   --ratio 16:9         비율: 16:9, 4:3, 1:1 등 (기본: 16:9)
 *   --lang en            언어: en, kr (기본: en)
 *   --style professional 스타일 프리셋 (기본: professional)
 *   --slides 1,2,3       특정 슬라이드만 생성 (콤마 구분)
 *   --output <path>      출력 경로 지정 (기본: 원본과 같은 폴더)
 *   --ref                참조 이미지 검색 활성화 (Tavily API)
 *   --ref-count <N>      슬라이드당 참조 이미지 수 (기본: 2, 최대: 4)
 *   --ref-save           참조 이미지를 로컬에 저장
 *   --dry-run            프롬프트만 출력, 이미지 생성 안함
 */

const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');
const os = require('os');

// ============================================================================
// 환경 설정
// ============================================================================

function loadEnv(envPath) {
    try {
        const envContent = fs.readFileSync(envPath, 'utf8');
        const env = {};
        for (const line of envContent.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith('#')) continue;
            const [key, ...valueParts] = trimmed.split('=');
            if (key && valueParts.length > 0) {
                env[key.trim()] = valueParts.join('=').trim().replace(/^["']|["']$/g, '');
            }
        }
        return env;
    } catch (e) {
        if (e.code !== 'ENOENT') console.error('[ENV] .env 파일 로드 실패:', e.message);
        return {};
    }
}

const SCRIPTS_DIR = __dirname;
// 키 해석 순서: 프로세스 환경변수 -> <스크립트 폴더>/.env -> ~/.ppt-image.env
const ENV_LOCAL = loadEnv(path.join(SCRIPTS_DIR, '.env'));
const ENV_HOME = loadEnv(path.join(os.homedir(), '.ppt-image.env'));
function resolveKey(name) {
    return process.env[name] || ENV_LOCAL[name] || ENV_HOME[name];
}
const API_KEY = resolveKey('GEMINI_API_KEY');              // Gemini (flash/pro)
const OPENAI_API_KEY = resolveKey('OPENAI_API_KEY');       // OpenAI (gpt-image)
const TAVILY_API_KEY = resolveKey('TAVILY_API_KEY');

// API 키 검증은 사용할 provider가 확정된 뒤(main) 수행한다.
// (Gemini 전용 실행에 OpenAI 키를 요구하거나 그 반대가 되지 않도록 지연 검증)

// ============================================================================
// 설정
// ============================================================================

// OpenAI 최신 이미지 모델 (향후 갱신 시 이 상수만 교체하면 됨)
// gpt-image-2: 2026-04-21 출시 SOTA (snapshot: gpt-image-2-2026-04-21)
const OPENAI_IMAGE_MODEL = 'gpt-image-2';

// 사용 가능한 모델 (별칭 → 실제 API 모델 ID)
const MODELS = {
    pro:    'gemini-3-pro-image-preview',       // Nano Banana Pro — 고품질, $0.24/4K
    flash:  'gemini-3.1-flash-image-preview',   // Nano Banana 2 — Flash, 4K 지원, ~$0.03/장
    openai: OPENAI_IMAGE_MODEL,                 // GPT Image 2 — 강한 텍스트 렌더링/지시 준수, ~$0.21/장(high)
};

// 참고용 1장당 대략 비용 (USD, 2026-04 기준)
const MODEL_COST_USD = {
    'gemini-3-pro-image-preview':     0.24,
    'gemini-3.1-flash-image-preview': 0.03,
    'gpt-image-2':                    0.21,     // 1024x1024 high quality 기준 (~$0.211)
};

// OpenAI Images API 설정 (gpt-image 계열 전용)
const OPENAI_CONFIG = {
    API_BASE: 'api.openai.com',
    API_PATH: '/v1/images/generations',
    QUALITY: 'high',                // 최고 품질 옵션 (low | medium | high | auto)
    DEFAULT_SIZE: '1536x1024',      // 종횡비 미지정 시 기본(가로 최대)
    // 종횡비 → 해상도 매핑
    // (gpt-image-2 지원: W/H 는 16 배수, 종횡비 1:3~3:1, 최대 3840x2160.
    //  표준 지원값 1024x1024 / 1536x1024 / 1024x1536 를 사용해 안정성 확보)
    RATIO_SIZE: {
        '16:9': '1536x1024',
        '4:3':  '1536x1024',
        '3:2':  '1536x1024',
        '9:16': '1024x1536',
        '3:4':  '1024x1536',
        '2:3':  '1024x1536',
        '1:1':  '1024x1024',
    },
};

const CONFIG = {
    MODEL: MODELS.flash,            // 기본: flash (비용 최적). --model pro 로 변경 가능.
    API_BASE: 'generativelanguage.googleapis.com',
    DEFAULT_MODE: 'full-slide',     // full-slide | diagram
    DEFAULT_SIZE: '4K',             // 1K | 2K | 4K
    DEFAULT_RATIO: '16:9',         // PPT 표준 비율
    DEFAULT_LANG: 'en',
    DEFAULT_STYLE: 'professional',
    REQUEST_DELAY_MS: 5000,         // API 호출 간 딜레이 (rate limit 방지)
};

/**
 * 모델 입력(별칭 또는 전체 ID)을 실제 API 모델 ID로 해석합니다.
 * 지원: 'pro' | 'flash' | 전체 ID ('gemini-3-pro-image-preview' 또는 'gemini-3.1-flash-image-preview')
 * 과거 호환을 위해 'gemini-3.1-flash-image' 처럼 -preview 가 빠진 입력도 자동 보정합니다.
 */
function resolveModel(input) {
    if (!input) return CONFIG.MODEL;
    const key = String(input).trim().toLowerCase();
    if (MODELS[key]) return MODELS[key];
    // 전체 ID 그대로 들어온 경우
    if (Object.values(MODELS).includes(key)) return key;
    // -preview suffix 누락 보정
    const withPreview = key.endsWith('-preview') ? key : `${key}-preview`;
    if (Object.values(MODELS).includes(withPreview)) return withPreview;
    const valid = [...Object.keys(MODELS), ...Object.values(MODELS)].join(', ');
    throw new Error(`Unknown --model '${input}'. Use one of: ${valid}`);
}

/** 현재 선택된 모델이 OpenAI(gpt-image) 계열인지 여부 */
function isOpenAIModel() {
    return String(CONFIG.MODEL).startsWith('gpt-image');
}

/** 로그/표시용 모델 라벨 */
function modelDisplayLabel() {
    if (isOpenAIModel()) return 'OpenAI (GPT Image 2)';
    return String(CONFIG.MODEL).includes('flash') ? 'Flash (Nano Banana 2)' : 'Pro (Nano Banana Pro)';
}

/** 종횡비를 OpenAI(gpt-image-2)가 지원하는 해상도 문자열로 변환 */
function resolveOpenAISize(ratio) {
    return OPENAI_CONFIG.RATIO_SIZE[ratio] || OPENAI_CONFIG.DEFAULT_SIZE;
}

const REF_CONFIG = {
    DEFAULT_COUNT: 2,               // 슬라이드당 기본 참조 이미지 수
    MAX_COUNT: 4,                   // 최대 참조 이미지 수
    MAX_IMAGE_SIZE_BYTES: 4 * 1024 * 1024,  // 4MB
    DOWNLOAD_TIMEOUT_MS: 15000,     // 다운로드 타임아웃
    MAX_REDIRECTS: 3,               // 최대 리다이렉트 횟수
    TAVILY_API_URL: 'https://api.tavily.com/search',
    SEARCH_DEPTH: 'basic',
};

// ============================================================================
// 스타일 프리셋
// ============================================================================

const STYLE_PRESETS = {
    professional: {
        name: 'Professional',
        prompt: 'Clean, professional corporate presentation slide. Modern flat design with subtle gradients. Navy blue (#1B2A4A), white (#FFFFFF), accent teal (#0EA5E9), light gray (#F1F5F9) color palette. Sans-serif typography (similar to Inter or Calibri). Balanced whitespace, clear visual hierarchy.',
    },
    academic: {
        name: 'Academic',
        prompt: 'Academic research presentation slide. Clean scholarly design with structured layout on a plain pure white (#FFFFFF) background. NO decorative backgrounds, NO gradients, NO patterns — only white. Deep blue (#1E3A5F) headings, gold accent (#D4A843) for highlights, charcoal (#374151) body text. Serif headings with sans-serif body text. Data-focused with clear labeling. All visual elements float on clean white.',
    },
    tech: {
        name: 'Tech/Startup',
        prompt: 'Modern tech presentation slide. Dark background (#0F172A) with vibrant accent colors. Electric blue (#3B82F6), cyan (#06B6D4), purple (#8B5CF6) neon-style accents on dark. Monospace code elements, geometric patterns, futuristic aesthetic.',
    },
    minimal: {
        name: 'Minimal',
        prompt: 'Ultra-minimal presentation slide. Maximum whitespace, extremely clean. Black (#111827) on white (#FFFFFF) with single accent color (#3B82F6). Large typography, intentional empty space, one focal element per slide.',
    },
    science: {
        name: 'Science/Research',
        prompt: 'Scientific research presentation slide. Clean white background with structured data presentation. Blue (#2563EB), green (#059669), orange (#EA580C) for data categories. Publication-quality figures, clear axis labels, professional notation.',
    },
    'crystal-bento': {
        name: 'Crystal Bento (Apple frosted-glass on white)',
        prompt: `Bento-grid presentation slide on a PURE WHITE background (#FFFFFF — no gradients, no patterns, no tinted backgrounds). Apple "Crystal"/Liquid-Glass aesthetic applied to bento cells.

LAYOUT:
- Asymmetric bento grid of rectangular cards (2-4 cells for content slides; single dominant hero panel for title/section-divider slides)
- Uniform rounded corners (~24px radius), ample gutters (32-48px), generous outer margins
- Cards float on white; use a strict 12-column layout for balance

CARD TREATMENT (frosted-glass / glassmorphism):
- Translucent white card surfaces with very subtle inner glow
- Soft diffused drop shadows (low-opacity, large blur radius) for depth
- Hairline 1px borders in light cool gray (#E5E7EB or rgba(15,23,42,0.06))
- Subtle light reflections / specular highlights on card edges, as if viewed through clear crystal
- Layered panels can gently overlap with refracted-light feel; NO heavy blur, NO colored glows

TYPOGRAPHY:
- Modern sans-serif (SF Pro / Inter feel), strong hierarchy
- Title: large, semibold, near-black (#0F172A)
- Subtitle/body: medium weight, charcoal (#334155)
- Captions/labels: small caps or micro-size, cool gray (#64748B)
- Korean Hangul rendered with Korean-optimized typography that matches the Latin stack in weight and spacing
- Generous whitespace; NEVER crowd text

COLOR PALETTE (restrained):
- Base: pure white #FFFFFF + near-black text #0F172A + cool grays
- Single primary accent: deep navy #1E3A8A or iOS-system blue #0A84FF
- Optional secondary accent: soft warm gold #C79C4E used sparingly for emphasis pills
- NO rainbow palettes, NO saturated chart colors

ICONOGRAPHY & IMAGERY:
- Flat-line or minimal 3D glassy icons (Apple SF Symbols feel)
- No stock-photo clutter
- If photographic references are used, render them as monochrome or desaturated behind a glass card

DO NOT:
- Use dark backgrounds
- Use gradient backgrounds behind the whole slide
- Use decorative borders or corner flourishes
- Use comic/cartoon iconography
- Use heavy drop shadows or neon glows

Final look: a calm, premium, editorial slide that feels like an Apple keynote frame rendered in bento-grid format on clean white.`,
    },
};

// ============================================================================
// 모드별 프롬프트 전략
// ============================================================================

const MODE_PROMPTS = {
    'full-slide': {
        system: `You are a presentation designer creating a complete slide image.
The output should look like a real PowerPoint slide with:
- Title area at top
- Content area with visual elements (diagrams, charts, tables, icons)
- Clean layout with proper margins and spacing
- Professional typography and color scheme
- NO placeholder text or lorem ipsum - use the ACTUAL content provided
- Render ALL text clearly and legibly at 4K resolution
- Text should be in the language specified in the content`,
        wrapper: (slideContent, style, ratio, lang, hasRefImages) => {
            let instructions = `Create a complete presentation slide image.

=== SLIDE CONTENT ===
${slideContent}
=== END CONTENT ===

=== DESIGN SPECS ===
${style.prompt}
Aspect Ratio: ${ratio} (standard presentation format)
Resolution: 4K ultra-high definition
Language: ${lang === 'kr' ? 'Korean (Hangul) - use Korean-optimized typography' : 'English'}

=== INSTRUCTIONS ===
1. Design this as a REAL presentation slide, not an illustration
2. Include the EXACT title from the content
3. Render tables, diagrams, and flow charts as clean vector-style graphics
4. All text must be sharp, legible, and properly sized for 4K
5. Use the color palette and style described above
6. Maintain proper visual hierarchy: Title > Subtitles > Body > Captions
7. Use web search to find accurate visual references for technical content if needed`;

            if (hasRefImages) {
                instructions += `

=== REFERENCE IMAGES ===
The attached images are reference diagrams/figures related to this slide's topic.
Use these as visual INSPIRATION and REFERENCE for creating accurate technical visualizations:
- Study the data visualization style, chart types, and diagram layouts in the references
- Incorporate similar visual patterns adapted to this slide's specific content
- Match the technical accuracy and scientific rigor shown in the references
- Do NOT copy the images directly — create NEW, original visuals inspired by them
- Adapt all visual elements to the specified slide design style and color palette
=== END REFERENCES ===`;
            }
            return instructions;
        }
    },
    'diagram': {
        system: `You are a technical illustrator creating diagram/infographic images for presentation slides.
Focus ONLY on the visual elements - diagrams, charts, flow charts, icons, illustrations.
Do NOT include slide titles or text blocks. Create clean, insertable graphics.`,
        wrapper: (slideContent, style, ratio, lang, hasRefImages) => {
            let instructions = `Create a clean diagram/infographic based on this slide content.

=== CONTENT TO VISUALIZE ===
${slideContent}
=== END CONTENT ===

=== DESIGN SPECS ===
${style.prompt}
Aspect Ratio: ${ratio}
Resolution: 4K ultra-high definition
Background: Transparent-friendly (light/white background, no dark edges)

=== INSTRUCTIONS ===
1. Create ONLY the diagram/visual element, NOT a full slide
2. Convert text descriptions into visual representations (flowcharts, arrows, icons)
3. Use clean vector-style graphics suitable for insertion into a PPT
4. Labels should be minimal (1-3 words each)
5. Use web search to find reference visuals for technical concepts if needed
6. Focus on clarity and visual impact over text density`;

            if (hasRefImages) {
                instructions += `

=== REFERENCE IMAGES ===
The attached images are reference diagrams/figures for this topic.
Use these as visual INSPIRATION:
- Replicate similar diagram styles and visual patterns
- Match the technical accuracy of the reference materials
- Create NEW original diagrams inspired by the references
- Adapt to the specified design style
=== END REFERENCES ===`;
            }
            return instructions;
        }
    }
};

// ============================================================================
// 참조 이미지 검색 (Tavily API)
// ============================================================================

/**
 * 슬라이드 내용에서 이미지 검색 쿼리를 추출합니다.
 */
function extractSearchQuery(slide) {
    const title = slide.title
        .replace(/^(?:Slide|슬라이드)\s*\d+[:\.\s]*/i, '')
        .replace(/[—–\-]+/g, ' ')
        .trim();

    // 마크다운 볼드(**text**) 및 헤딩(### text)에서 키워드 추출
    const boldTerms = (slide.content.match(/\*\*([^*]+)\*\*/g) || [])
        .map(t => t.replace(/\*\*/g, '').trim())
        .filter(t => t.length > 2 && t.length < 50);

    const headingTerms = (slide.content.match(/^###?\s+(.+)$/gm) || [])
        .map(t => t.replace(/^###?\s+/, '').trim());

    // 기술 용어 추출 (대문자 약어, 화학식 등)
    const techTerms = (slide.content.match(/\b[A-Z][A-Z\d]{1,}(?:[-/][A-Z\d]+)*\b/g) || [])
        .filter(t => !['THE', 'AND', 'FOR', 'NOT', 'END', 'KEY', 'MAX', 'NEW'].includes(t));

    // 고유 키워드 조합
    const allTerms = [...new Set([...headingTerms.slice(0, 2), ...boldTerms.slice(0, 3), ...techTerms.slice(0, 3)])];
    const keywordStr = allTerms.join(' ').substring(0, 100);

    return `scientific diagram ${title} ${keywordStr}`.trim();
}

/**
 * Tavily API로 이미지를 검색합니다.
 */
function searchImagesViaTavily(query, count) {
    return new Promise((resolve, reject) => {
        if (!TAVILY_API_KEY) {
            reject(new Error('TAVILY_API_KEY가 설정되지 않았습니다.'));
            return;
        }

        const requestData = JSON.stringify({
            api_key: TAVILY_API_KEY,
            query: query,
            include_images: true,
            include_image_descriptions: true,
            max_results: Math.max(count * 2, 5),  // 여유있게 검색
            search_depth: REF_CONFIG.SEARCH_DEPTH,
        });

        const url = new URL(REF_CONFIG.TAVILY_API_URL);
        const options = {
            hostname: url.hostname,
            port: 443,
            path: url.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(requestData),
            },
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);
                    if (json.error) {
                        reject(new Error(`Tavily API Error: ${json.error}`));
                        return;
                    }

                    const images = (json.images || []).slice(0, count * 2);
                    resolve(images.map(img => {
                        if (typeof img === 'string') return { url: img, description: '' };
                        return { url: img.url || img, description: img.description || '' };
                    }));
                } catch (e) {
                    reject(new Error(`Tavily response parse error: ${e.message}`));
                }
            });
        });

        req.on('error', (e) => reject(new Error(`Tavily request error: ${e.message}`)));
        req.setTimeout(20000, () => {
            req.destroy();
            reject(new Error('Tavily request timeout'));
        });

        req.write(requestData);
        req.end();
    });
}

/**
 * URL에서 이미지를 다운로드하여 Base64로 반환합니다.
 */
function downloadImage(imageUrl, redirectCount = 0) {
    return new Promise((resolve, reject) => {
        if (redirectCount > REF_CONFIG.MAX_REDIRECTS) {
            reject(new Error('Too many redirects'));
            return;
        }

        let parsedUrl;
        try {
            parsedUrl = new URL(imageUrl);
        } catch (e) {
            reject(new Error(`Invalid URL: ${imageUrl}`));
            return;
        }

        const client = parsedUrl.protocol === 'https:' ? https : http;

        const req = client.get(imageUrl, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (PPT-Slide-Generator/2.0)',
                'Accept': 'image/*,*/*;q=0.8',
            },
        }, (res) => {
            // 리다이렉트 처리
            if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
                const redirectUrl = new URL(res.headers.location, imageUrl).href;
                resolve(downloadImage(redirectUrl, redirectCount + 1));
                return;
            }

            if (res.statusCode !== 200) {
                reject(new Error(`HTTP ${res.statusCode} for ${imageUrl}`));
                return;
            }

            const contentType = res.headers['content-type'] || '';
            if (!contentType.startsWith('image/')) {
                reject(new Error(`Not an image: ${contentType}`));
                return;
            }

            const chunks = [];
            let totalSize = 0;

            res.on('data', (chunk) => {
                totalSize += chunk.length;
                if (totalSize > REF_CONFIG.MAX_IMAGE_SIZE_BYTES) {
                    req.destroy();
                    reject(new Error(`Image too large (>${REF_CONFIG.MAX_IMAGE_SIZE_BYTES / 1024 / 1024}MB)`));
                    return;
                }
                chunks.push(chunk);
            });

            res.on('end', () => {
                const buffer = Buffer.concat(chunks);
                const mimeType = contentType.split(';')[0].trim();
                resolve({
                    buffer: buffer,
                    base64: buffer.toString('base64'),
                    mimeType: mimeType,
                    size: buffer.length,
                });
            });

            res.on('error', (e) => reject(e));
        });

        req.on('error', (e) => reject(new Error(`Download error: ${e.message}`)));
        req.setTimeout(REF_CONFIG.DOWNLOAD_TIMEOUT_MS, () => {
            req.destroy();
            reject(new Error(`Download timeout for ${imageUrl}`));
        });
    });
}

/**
 * 슬라이드에 대한 참조 이미지를 검색하고 다운로드합니다.
 */
async function fetchReferenceImages(slide, count, saveDir = null) {
    const query = extractSearchQuery(slide);
    console.log(`    🔍 검색 쿼리: "${query.substring(0, 80)}..."`);

    let searchResults;
    try {
        searchResults = await searchImagesViaTavily(query, count);
    } catch (e) {
        console.warn(`    ⚠️  이미지 검색 실패: ${e.message}`);
        return [];
    }

    if (searchResults.length === 0) {
        console.log('    ⚠️  검색 결과 없음');
        return [];
    }

    console.log(`    📥 ${searchResults.length}개 이미지 발견, 다운로드 중...`);

    const downloaded = [];
    for (const img of searchResults) {
        if (downloaded.length >= count) break;

        try {
            const result = await downloadImage(img.url);
            downloaded.push({
                ...result,
                url: img.url,
                description: img.description,
            });

            const sizeMB = (result.size / 1024 / 1024).toFixed(2);
            console.log(`    ✅ ref${downloaded.length}: ${sizeMB}MB (${result.mimeType})`);

            // 로컬 저장 옵션
            if (saveDir) {
                const slideNum = String(slide.number).padStart(2, '0');
                const ext = result.mimeType.split('/')[1] || 'jpg';
                const refFilename = `slide_${slideNum}_ref_${downloaded.length}.${ext}`;
                fs.writeFileSync(path.join(saveDir, refFilename), result.buffer);
            }
        } catch (e) {
            console.log(`    ⏭️  스킵: ${e.message.substring(0, 60)}`);
        }
    }

    return downloaded;
}

// ============================================================================
// 마크다운 파서
// ============================================================================

function parseSlides(markdownContent) {
    const slides = [];
    // ## Slide N 또는 ## 슬라이드 N 패턴으로 분할
    const slidePattern = /^## (?:Slide|슬라이드)\s+\d+[:\.\s]*/gmi;
    const parts = markdownContent.split(slidePattern);
    const titles = markdownContent.match(slidePattern) || [];

    // 첫 부분은 헤더/메타 정보이므로 스킵
    for (let i = 0; i < titles.length; i++) {
        const title = titles[i].replace(/^## /, '').trim();
        const content = (parts[i + 1] || '').trim();

        if (content) {
            slides.push({
                number: i + 1,
                title: title,
                content: content,
                raw: `## ${title}\n\n${content}`
            });
        }
    }

    // fallback: ## 로 시작하는 모든 섹션을 슬라이드로 처리
    if (slides.length === 0) {
        const sections = markdownContent.split(/^## /gm).filter(s => s.trim());
        for (let i = 0; i < sections.length; i++) {
            const lines = sections[i].split('\n');
            const title = lines[0].trim();
            const content = lines.slice(1).join('\n').trim();

            // Design Summary, 디자인 요약 같은 메타 섹션 제외
            if (/design summary|디자인 요약|변경 이력|recommended|권장/i.test(title)) continue;

            if (content) {
                slides.push({
                    number: i + 1,
                    title: title,
                    content: content,
                    raw: `## ${title}\n\n${content}`
                });
            }
        }

        // Option A (ppt-image subagent): S-prefixed slide filter.
        // When markdown uses `## S1.` / `## S24b.` style, keep only those and
        // drop meta-sections like "Genspark 입력 사용법", "Sources", etc.
        // Re-number sequentially so filenames are 01..N.
        const sPrefixed = slides.filter(s => /^S\d+[a-z]?\./i.test(s.title));
        if (sPrefixed.length > 0) {
            sPrefixed.forEach((s, idx) => { s.number = idx + 1; });
            return sPrefixed;
        }
    }

    return slides;
}

// ============================================================================
// Gemini API 호출
// ============================================================================

/**
 * Gemini Image API 호출 (텍스트 전용 또는 멀티모달)
 * @param {string} prompt - 텍스트 프롬프트
 * @param {string} imageSize - 이미지 해상도
 * @param {string} aspectRatio - 가로세로 비율
 * @param {Array} referenceImages - 참조 이미지 배열 [{base64, mimeType}] (optional)
 */
function callGeminiImage(prompt, imageSize, aspectRatio, referenceImages = []) {
    return new Promise((resolve, reject) => {
        // parts 구성: 참조 이미지 → 텍스트 프롬프트 순서
        const parts = [];

        for (const ref of referenceImages) {
            parts.push({
                inlineData: {
                    mimeType: ref.mimeType,
                    data: ref.base64,
                }
            });
        }

        parts.push({ text: prompt });

        const requestBody = {
            contents: [{
                role: "user",
                parts: parts,
            }],
            generationConfig: {
                responseModalities: ["IMAGE", "TEXT"],
                temperature: 1.0,
                topP: 0.95,
                candidateCount: 1,
                imageConfig: {
                    aspectRatio: aspectRatio,
                    imageSize: imageSize
                },
                // thinkingConfig 비활성화 (현재 모델 미지원)
                // thinkingConfig: {
                //     thinkingLevel: "high"
                // }
            },
            tools: [{ googleSearch: {} }]
        };

        const requestData = JSON.stringify(requestBody);

        const options = {
            hostname: CONFIG.API_BASE,
            port: 443,
            path: `/v1beta/models/${CONFIG.MODEL}:generateContent?key=${API_KEY}`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(requestData)
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);

                    if (json.error) {
                        reject(new Error(`API Error: ${json.error.message}`));
                        return;
                    }

                    if (!json.candidates?.[0]?.content?.parts) {
                        reject(new Error('No content in response'));
                        return;
                    }

                    let imageBuffer = null;
                    let textResponse = '';

                    for (const part of json.candidates[0].content.parts) {
                        if (part.inlineData) {
                            imageBuffer = Buffer.from(part.inlineData.data, 'base64');
                        }
                        if (part.text) {
                            textResponse += part.text;
                        }
                    }

                    if (!imageBuffer) {
                        reject(new Error('No image in response. Text: ' + textResponse.substring(0, 200)));
                        return;
                    }

                    resolve({ imageBuffer, textResponse });
                } catch (e) {
                    reject(new Error(`Response parse error: ${e.message}\nRaw: ${data.substring(0, 300)}`));
                }
            });
        });

        req.on('error', (e) => reject(new Error(`Request error: ${e.message}`)));
        req.setTimeout(180000, () => {  // 멀티모달은 더 오래 걸릴 수 있음
            req.destroy();
            reject(new Error('Request timeout (180s)'));
        });

        req.write(requestData);
        req.end();
    });
}

// ============================================================================
// OpenAI Images API 호출 (gpt-image 계열)
// ============================================================================

/**
 * OpenAI Images API 호출 (텍스트 → 이미지)
 * POST https://api.openai.com/v1/images/generations, Authorization: Bearer.
 * 응답은 항상 b64_json(base64) 로 반환된다.
 * @param {string} prompt - 텍스트 프롬프트
 * @param {string} size - 해상도 문자열 (예: '1536x1024')
 * @param {string} quality - 품질 (low | medium | high | auto)
 * 주의: Gemini 전용 파라미터(googleSearch/thinkingConfig/참조 이미지)는 사용하지 않는다.
 */
function callOpenAIImage(prompt, size, quality) {
    return new Promise((resolve, reject) => {
        const requestBody = {
            model: CONFIG.MODEL,
            prompt: prompt,
            size: size,
            quality: quality,
            n: 1,
        };

        const requestData = JSON.stringify(requestBody);

        const options = {
            hostname: OPENAI_CONFIG.API_BASE,
            port: 443,
            path: OPENAI_CONFIG.API_PATH,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${OPENAI_API_KEY}`,
                'Content-Length': Buffer.byteLength(requestData),
            },
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);

                    if (json.error) {
                        const em = json.error.message || JSON.stringify(json.error);
                        // 재시도 래퍼가 상태코드를 인식하도록 status 를 메시지에 포함
                        reject(new Error(`OpenAI API Error (${res.statusCode}): ${em}`));
                        return;
                    }

                    const b64 = json.data?.[0]?.b64_json;
                    if (!b64) {
                        reject(new Error('No image (b64_json) in OpenAI response: ' + JSON.stringify(json).substring(0, 200)));
                        return;
                    }

                    const imageBuffer = Buffer.from(b64, 'base64');
                    // gpt-image 계열은 revised_prompt 를 돌려주기도 함
                    const textResponse = json.data?.[0]?.revised_prompt || '';
                    resolve({ imageBuffer, textResponse });
                } catch (e) {
                    reject(new Error(`OpenAI response parse error: ${e.message}\nRaw: ${data.substring(0, 300)}`));
                }
            });
        });

        req.on('error', (e) => reject(new Error(`OpenAI request error: ${e.message}`)));
        req.setTimeout(180000, () => {
            req.destroy();
            reject(new Error('OpenAI request timeout (180s)'));
        });

        req.write(requestData);
        req.end();
    });
}

// ============================================================================
// 재시도 로직 (Exponential Backoff)
// ============================================================================

/**
 * API 호출을 재시도합니다. 429/500/503 에러 시 exponential backoff 적용.
 * @param {Function} fn - 실행할 async 함수
 * @param {number} maxRetries - 최대 재시도 횟수 (기본: 3)
 * @param {number} baseDelay - 초기 대기 시간 ms (기본: 5000)
 */
async function withRetry(fn, maxRetries = 3, baseDelay = 5000) {
    let lastError;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            return await fn();
        } catch (error) {
            lastError = error;
            const msg = error.message || '';
            const isRetryable = /429|500|503|timeout|ECONNRESET|ETIMEDOUT|rate.?limit/i.test(msg);

            if (!isRetryable || attempt === maxRetries) {
                throw error;
            }

            const delay = baseDelay * Math.pow(2, attempt) + Math.random() * 2000;
            console.log(`    ⏳ 재시도 ${attempt + 1}/${maxRetries} (${(delay / 1000).toFixed(1)}초 후)... [${msg.substring(0, 60)}]`);
            await sleep(delay);
        }
    }
    throw lastError;
}

// ============================================================================
// 슬라이드 내용 유형 감지
// ============================================================================

/**
 * 슬라이드 내용을 분석하여 시각화 유형을 감지합니다.
 * 감지된 유형에 따라 프롬프트 보강 지시를 반환합니다.
 */
function detectContentType(slideContent) {
    const content = slideContent.toLowerCase();
    const types = [];

    // 플로우차트/프로세스 감지
    if (/→|↓|↑|←|⟶|flow|step\s*\d|단계|과정|순서|절차|pipeline|workflow/.test(content)) {
        types.push({
            type: 'flowchart',
            boost: `This slide describes a PROCESS or FLOW. Emphasize:
- Clear directional arrows showing sequence (left-to-right or top-to-bottom)
- Distinct boxes/nodes for each step with contrasting borders
- Numbered steps if applicable
- Connection lines with arrowheads showing flow direction`
        });
    }

    // 표/비교 감지
    if (/\|.*\|.*\|/.test(slideContent) || /비교|comparison|vs\.?|대비|차이점|장단점|pros.*cons/i.test(content)) {
        types.push({
            type: 'table',
            boost: `This slide contains a TABLE or COMPARISON. Emphasize:
- Clean grid layout with alternating row colors for readability
- Bold column headers with distinct background color
- Aligned columns with consistent cell padding
- Clear borders separating rows and columns`
        });
    }

    // 데이터/차트 감지
    if (/\d+\.?\d*\s*%|그래프|chart|graph|데이터|data|통계|statistic|증가|감소|trend|bar|pie|histogram/.test(content)) {
        types.push({
            type: 'chart',
            boost: `This slide contains DATA or STATISTICS. Emphasize:
- Accurate data visualization (bar chart, line graph, or pie chart as appropriate)
- Clearly labeled axes with units
- Data values displayed on or near data points
- Legend if multiple data series
- Use contrasting colors for different data categories`
        });
    }

    // 계층/분류/트리 감지
    if (/계층|hierarchy|분류|classification|카테고리|category|트리|tree|상위|하위|parent|child|구조/.test(content)) {
        types.push({
            type: 'hierarchy',
            boost: `This slide describes a HIERARCHY or CLASSIFICATION. Emphasize:
- Tree-like structure with clear parent-child relationships
- Indentation or levels showing depth
- Connecting lines between nodes
- Distinct visual treatment for different levels (size, color intensity)`
        });
    }

    // 수식/방정식 감지
    if (/[=∝∫∑∏√]|equation|수식|방정식|공식|formula|\^[{(]?\d/.test(slideContent)) {
        types.push({
            type: 'equation',
            boost: `This slide contains EQUATIONS or FORMULAS. Emphasize:
- Large, clearly rendered mathematical notation
- Proper subscript/superscript formatting
- Variable definitions listed nearby
- Box or highlight around key equations
- Use mathematical typography (not plain text for formulas)`
        });
    }

    // 타이틀 슬라이드 감지 (내용이 적을 때)
    if (slideContent.trim().split('\n').filter(l => l.trim()).length <= 4) {
        types.push({
            type: 'title',
            boost: `This is a TITLE or SECTION DIVIDER slide. Emphasize:
- Large, centered title text as the dominant element
- Generous whitespace around the title
- Subtle decorative element or background accent
- Minimal text — let the title breathe`
        });
    }

    // 목록/불릿 감지
    if ((slideContent.match(/^[\s]*[-*•]\s/gm) || []).length >= 4) {
        types.push({
            type: 'bullet-list',
            boost: `This slide is a BULLET LIST. Emphasize:
- Clean visual hierarchy with consistent bullet styling
- Adequate spacing between items
- Consider using icons instead of plain bullets for key points
- Group related items visually if there are sub-points`
        });
    }

    return types;
}

// ============================================================================
// 유틸리티
// ============================================================================

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function parseArgs(args) {
    const opts = {
        file: null,
        mode: CONFIG.DEFAULT_MODE,
        size: CONFIG.DEFAULT_SIZE,
        ratio: CONFIG.DEFAULT_RATIO,
        lang: CONFIG.DEFAULT_LANG,
        style: CONFIG.DEFAULT_STYLE,
        slides: null,       // null = 전체, [1,2,3] = 특정
        output: null,       // null = 원본과 같은 폴더
        dryRun: false,
        parallel: false,    // 병렬 처리
        ref: false,         // 참조 이미지 검색 활성화
        refCount: REF_CONFIG.DEFAULT_COUNT,  // 슬라이드당 참조 이미지 수
        refSave: false,     // 참조 이미지 로컬 저장
    };

    for (let i = 0; i < args.length; i++) {
        const arg = args[i];
        switch (arg) {
            case '--mode':      opts.mode = args[++i]; break;
            case '--size':      opts.size = args[++i]; break;
            case '--ratio':     opts.ratio = args[++i]; break;
            case '--lang':      opts.lang = args[++i]; break;
            case '--style':     opts.style = args[++i]; break;
            case '--output':    opts.output = args[++i]; break;
            case '--model':     opts.model = resolveModel(args[++i]); break;
            case '--dry-run':   opts.dryRun = true; break;
            case '--parallel':  opts.parallel = true; break;
            case '--ref':       opts.ref = true; break;
            case '--ref-count': opts.refCount = Math.min(parseInt(args[++i]) || REF_CONFIG.DEFAULT_COUNT, REF_CONFIG.MAX_COUNT); break;
            case '--ref-save':  opts.refSave = true; break;
            case '--slides':
                opts.slides = args[++i].split(',').map(n => parseInt(n.trim()));
                break;
            default:
                if (!arg.startsWith('--') && !opts.file) {
                    opts.file = arg;
                }
        }
    }

    // --model이 지정되면 전역 CONFIG.MODEL을 덮어써서 모든 API 호출에 반영
    if (opts.model) {
        CONFIG.MODEL = opts.model;
    }

    return opts;
}

function printUsage() {
    console.log(`
📊 PPT Slide Image Generator v3 (Gemini Image — Pro/Flash 선택 + Tavily Reference Search)

사용법:
  node generate_ppt_slides.js <markdown_path> [options]

기본 옵션:
  --model <model>     pro | flash | openai (기본: flash, ~$0.03/장)
                      pro    = gemini-3-pro-image-preview     (고품질, ~$0.24/4K)
                      flash  = gemini-3.1-flash-image-preview (Nano Banana 2, 4K 지원)
                      openai = gpt-image-2 (GPT Image 2, ~$0.21/장 high, --size/--ref 미지원)
  --mode <mode>       full-slide | diagram (기본: full-slide)
  --size <size>       1K | 2K | 4K (기본: 4K)
  --ratio <ratio>     16:9 | 4:3 | 1:1 등 (기본: 16:9)
  --lang <lang>       en | kr (기본: en)
  --style <style>     professional | academic | tech | minimal | science (기본: professional)
  --slides <nums>     특정 슬라이드만: 1,2,3
  --output <path>     출력 경로 (기본: 원본과 같은 폴더)
  --parallel          병렬 생성 (API rate limit 주의)
  --dry-run           프롬프트만 출력

참조 이미지 옵션 (v2):
  --ref               참조 이미지 검색 활성화 (Tavily API)
  --ref-count <N>     슬라이드당 참조 이미지 수 (기본: 2, 최대: 4)
  --ref-save          참조 이미지를 로컬에도 저장

예시:
  # 기본 (텍스트 기반)
  node generate_ppt_slides.js ./ppt_draft.md --style science

  # OpenAI GPT Image 2 (강한 텍스트 렌더링 / 지시 준수)
  node generate_ppt_slides.js ./ppt_draft.md --model openai --style academic

  # 참조 이미지 활용 (웹 검색 → 다이어그램 참조)
  node generate_ppt_slides.js ./ppt_draft.md --style science --ref

  # 참조 이미지 3개 + 로컬 저장
  node generate_ppt_slides.js ./ppt_draft.md --ref --ref-count 3 --ref-save

  # 다이어그램만 + 참조 이미지
  node generate_ppt_slides.js ./ppt_draft.md --mode diagram --ref --slides 3,5
`);
}

// ============================================================================
// 메인 실행
// ============================================================================

async function main() {
    const args = process.argv.slice(2);

    if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
        printUsage();
        process.exit(0);
    }

    const opts = parseArgs(args);

    if (!opts.file) {
        console.error('❌ 마크다운 파일 경로를 지정하세요.');
        printUsage();
        process.exit(1);
    }

    // provider별 API 키 검증 + OpenAI 미지원 옵션 안내 (사용할 모델 확정 시점)
    if (isOpenAIModel()) {
        if (!OPENAI_API_KEY) {
            console.error('❌ OPENAI_API_KEY가 설정되지 않았습니다. 환경변수 또는 ~/.ppt-image.env 를 확인하세요.');
            process.exit(1);
        }
        // OpenAI(gpt-image) 경로 미지원 옵션 → 경고 후 조정
        if (opts.ref) {
            console.warn(`⚠️  OpenAI(${CONFIG.MODEL})는 --ref(참조 이미지)를 지원하지 않습니다. 참조 없이 진행합니다.`);
            opts.ref = false;
        }
        console.warn(`⚠️  OpenAI 모델은 --size(${opts.size})를 무시하고 종횡비→해상도(${resolveOpenAISize(opts.ratio)})를 사용합니다.`);
    } else if (!API_KEY) {
        console.error('❌ GEMINI_API_KEY가 설정되지 않았습니다. 환경변수 또는 ~/.ppt-image.env 를 확인하세요.');
        process.exit(1);
    }

    // --ref 활성화 시 TAVILY_API_KEY 확인
    if (opts.ref && !TAVILY_API_KEY) {
        console.error('❌ --ref 사용하려면 TAVILY_API_KEY가 필요합니다. 환경변수 또는 ~/.ppt-image.env 를 확인하세요.');
        process.exit(1);
    }

    // 파일 읽기
    const filePath = path.resolve(opts.file);
    if (!fs.existsSync(filePath)) {
        console.error(`❌ 파일을 찾을 수 없습니다: ${filePath}`);
        process.exit(1);
    }

    const markdown = fs.readFileSync(filePath, 'utf8');
    const slides = parseSlides(markdown);

    if (slides.length === 0) {
        console.error('❌ 슬라이드를 파싱할 수 없습니다. ## Slide N 또는 ## 섹션 구분을 확인하세요.');
        process.exit(1);
    }

    // 스타일 설정
    const style = STYLE_PRESETS[opts.style] || STYLE_PRESETS.professional;
    const modeConfig = MODE_PROMPTS[opts.mode] || MODE_PROMPTS['full-slide'];

    // 출력 경로
    const outputDir = opts.output || path.dirname(filePath);
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
    }

    // 참조 이미지 저장 경로
    const refSaveDir = opts.refSave ? path.join(outputDir, '_ref_images') : null;
    if (refSaveDir && !fs.existsSync(refSaveDir)) {
        fs.mkdirSync(refSaveDir, { recursive: true });
    }

    // 대상 슬라이드 필터링
    const targetSlides = opts.slides
        ? slides.filter(s => opts.slides.includes(s.number))
        : slides;

    console.log(`
╔══════════════════════════════════════════════════╗
║  📊 PPT Slide Image Generator v3                ║
╚══════════════════════════════════════════════════╝

  📄 파일: ${path.basename(filePath)}
  🎨 모드: ${opts.mode} (${opts.mode === 'full-slide' ? '전체 슬라이드' : '다이어그램만'})
  📐 비율: ${opts.ratio}
  🖼️  해상도: ${opts.size}
  🎭 스타일: ${style.name}
  🌐 언어: ${opts.lang === 'kr' ? '한국어' : 'English'}
  📊 슬라이드: ${targetSlides.length}장 / 총 ${slides.length}장
  📁 출력: ${outputDir}
  🔍 참조 이미지: ${opts.ref ? `활성 (슬라이드당 ${opts.refCount}장, Tavily)` : '비활성'}
  ${opts.refSave ? '💾 참조 이미지 저장: ' + refSaveDir : ''}
  ${opts.dryRun ? '⚠️  DRY RUN 모드 (이미지 생성 안함)' : ''}
`);

    // 비율 문자열 (파일명용: 16:9 → 16x9)
    const ratioTag = opts.ratio.replace(':', 'x');

    // 슬라이드 1개 생성 함수
    async function generateSlide(slide) {
        const slideNum = String(slide.number).padStart(2, '0');
        const refTag = opts.ref ? '_ref' : '';
        const filename = `${opts.style}_slide_${slideNum}_${ratioTag}${refTag}.png`;
        const outputPath = path.join(outputDir, filename);

        console.log(`\n━━━ Slide ${slide.number}: ${slide.title} ━━━`);

        // Step 1: 참조 이미지 검색 (--ref 활성화 시)
        let refImages = [];
        if (opts.ref) {
            console.log('  📸 참조 이미지 검색 중...');
            refImages = await fetchReferenceImages(slide, opts.refCount, refSaveDir);
            console.log(`  📸 참조 이미지 ${refImages.length}개 준비 완료`);
        }

        // Step 2: 내용 유형 감지 + 프롬프트 생성
        const contentTypes = detectContentType(slide.content);
        const hasRefImages = refImages.length > 0;
        let prompt = `${modeConfig.system}\n\n${modeConfig.wrapper(slide.raw, style, opts.ratio, opts.lang, hasRefImages)}`;

        // 감지된 내용 유형에 따른 프롬프트 보강
        if (contentTypes.length > 0) {
            const typeNames = contentTypes.map(t => t.type).join(', ');
            console.log(`  🔎 내용 유형 감지: ${typeNames}`);
            const boosts = contentTypes.map(t => t.boost).join('\n\n');
            prompt += `\n\n=== CONTENT TYPE OPTIMIZATION ===\nDetected content types: ${typeNames}\n\n${boosts}\n=== END OPTIMIZATION ===`;
        }

        if (opts.dryRun) {
            const dryModel = modelDisplayLabel();
            const dryCost = MODEL_COST_USD[CONFIG.MODEL] ? `~$${MODEL_COST_USD[CONFIG.MODEL]}/장` : '가격정보 없음';
            console.log(`\n🔧 Model: ${CONFIG.MODEL}  (${dryModel}, ${dryCost})`);
            if (isOpenAIModel()) {
                console.log(`🖼️  OpenAI 해상도: ${resolveOpenAISize(opts.ratio)} (--size ${opts.size} 무시), quality: ${OPENAI_CONFIG.QUALITY}`);
            }
            console.log('\n📝 Generated Prompt:');
            console.log('─'.repeat(60));
            console.log(prompt);
            if (hasRefImages) {
                console.log(`\n📸 참조 이미지 ${refImages.length}개 첨부됨:`);
                refImages.forEach((img, i) => {
                    const sizeMB = (img.size / 1024 / 1024).toFixed(2);
                    console.log(`  ref${i + 1}: ${img.mimeType} (${sizeMB}MB) - ${img.url?.substring(0, 60)}...`);
                });
            }
            console.log('─'.repeat(60));
            return { slide: slide.number, title: slide.title, status: 'dry-run', refCount: refImages.length };
        }

        try {
            const modeLabel = hasRefImages ? '멀티모달 (참조 이미지 포함)' : '텍스트 기반';
            const costHint = MODEL_COST_USD[CONFIG.MODEL] ? ` · ~$${MODEL_COST_USD[CONFIG.MODEL]}/장` : '';

            // Step 3: 이미지 API 호출 (provider 분기, 재시도 포함)
            let imageBuffer, textResponse;
            if (isOpenAIModel()) {
                const oaSize = resolveOpenAISize(opts.ratio);
                console.log(`  ⏳ ${modelDisplayLabel()} 호출 중... (${oaSize}, quality=${OPENAI_CONFIG.QUALITY}, ${opts.ratio}${costHint})`);
                ({ imageBuffer, textResponse } = await withRetry(
                    () => callOpenAIImage(prompt, oaSize, OPENAI_CONFIG.QUALITY),
                    3,  // 최대 3회 재시도
                    CONFIG.REQUEST_DELAY_MS
                ));
            } else {
                console.log(`  ⏳ Gemini ${modelDisplayLabel()} 호출 중... (${opts.size}, ${opts.ratio}, ${modeLabel}${costHint})`);
                ({ imageBuffer, textResponse } = await withRetry(
                    () => callGeminiImage(prompt, opts.size, opts.ratio, refImages),
                    3,  // 최대 3회 재시도
                    CONFIG.REQUEST_DELAY_MS
                ));
            }

            fs.writeFileSync(outputPath, imageBuffer);

            const sizeMB = (imageBuffer.length / 1024 / 1024).toFixed(2);
            console.log(`  ✅ 저장 완료: ${filename} (${sizeMB} MB)`);

            if (textResponse) {
                console.log(`  💬 모델 응답: ${textResponse.substring(0, 100)}...`);
            }

            return {
                slide: slide.number,
                title: slide.title,
                status: 'success',
                file: filename,
                size: sizeMB,
                refCount: refImages.length,
            };

        } catch (error) {
            console.error(`  ❌ 실패: ${error.message}`);
            return {
                slide: slide.number,
                title: slide.title,
                status: 'failed',
                error: error.message,
                refCount: refImages.length,
            };
        }
    }

    // 슬라이드 생성 (병렬 또는 순차)
    let results;

    if (opts.parallel && !opts.dryRun) {
        console.log(`\n  🚀 병렬 모드: ${targetSlides.length}장 동시 생성 중...`);
        results = await Promise.all(targetSlides.map(slide => generateSlide(slide)));
    } else {
        results = [];
        for (const slide of targetSlides) {
            const result = await generateSlide(slide);
            results.push(result);

            // Rate limit 방지 (순차 모드에서만)
            if (!opts.dryRun && targetSlides.indexOf(slide) < targetSlides.length - 1) {
                const delay = opts.ref ? CONFIG.REQUEST_DELAY_MS + 2000 : CONFIG.REQUEST_DELAY_MS;
                console.log(`  ⏳ ${delay / 1000}초 대기...`);
                await sleep(delay);
            }
        }
    }

    // 결과 요약
    console.log(`
╔══════════════════════════════════════════════════╗
║  📊 결과 요약                                    ║
╚══════════════════════════════════════════════════╝
`);

    const success = results.filter(r => r.status === 'success');
    const failed = results.filter(r => r.status === 'failed');

    for (const r of results) {
        const icon = r.status === 'success' ? '✅' : r.status === 'failed' ? '❌' : '📝';
        const refInfo = r.refCount > 0 ? ` (ref: ${r.refCount})` : '';
        console.log(`  ${icon} Slide ${r.slide}: ${r.title} → ${r.file || r.status}${refInfo}`);
    }

    console.log(`
  총 ${results.length}장 | 성공 ${success.length} | 실패 ${failed.length}
  ${opts.ref ? `참조 이미지 모드: 활성 (Tavily)` : '참조 이미지: 비활성'}
  출력 경로: ${outputDir}
`);

    // 결과 JSON 저장
    const resultPath = path.join(outputDir, 'slide_generation_log.json');
    fs.writeFileSync(resultPath, JSON.stringify({
        timestamp: new Date().toISOString(),
        source: path.basename(filePath),
        version: 'v2',
        options: {
            model: CONFIG.MODEL,
            mode: opts.mode,
            size: opts.size,
            ratio: opts.ratio,
            style: opts.style,
            lang: opts.lang,
            ref: opts.ref,
            refCount: opts.refCount,
        },
        results: results
    }, null, 2));
    console.log(`  📋 로그 저장: ${path.basename(resultPath)}`);
}

main().catch(err => {
    console.error('❌ 치명적 오류:', err.message);
    process.exit(1);
});
