#!/usr/bin/env node
/**
 * camp-talk — deterministic deck builder
 *
 *   node build_deck.js <spec.json> <out.pptx> [--strict]
 *
 * Reads a deck_spec.json (see references/spec-schema.md) and emits an editable
 * 16:9 pptx on the fixed grid defined in references/layout-grid.md.
 *
 * Exit codes
 *   0  built (warnings allowed)
 *   2  schema error or forbidden string found — nothing written
 *   3  --strict and at least one warning
 */

'use strict';

const fs = require('fs');
const path = require('path');
const PptxGenJS = require('pptxgenjs');

let sharp = null;
try { sharp = require('sharp'); } catch (e) { sharp = null; }
let imageSize = null;
try { imageSize = require('image-size'); } catch (e) { imageSize = null; }

// ---------------------------------------------------------------------------
// 1. Grid constants — layout-grid.md §1, §2, §5
// ---------------------------------------------------------------------------

const SLIDE_W = 13.333;
const SLIDE_H = 7.5;

const ZONE = {
  band:    { x: 0,    y: 0,    w: SLIDE_W, h: 0.42 },
  title:   { x: 0.50, y: 0.62, w: 12.33,   h: 0.70 },
  content: { x: 0.50, y: 1.50, w: 12.33,   h: 4.95 },
  bottom:  { x: 0.50, y: 6.65, w: 12.33,   h: 0.50 },
};
const CONTENT_BOTTOM = ZONE.content.y + ZONE.content.h; // 6.45

const COLOR = {
  band:   '1F3A5F',
  ink:    '1B2430',
  ink2:   '4B5563',
  accent: '0E7C7B',
  warn:   'B45309',
  bottom: 'EEF2F7',
  paper:  'FFFFFF',
};

// Tints of paper over band, for text that sits on the navy full-bleed slides.
// Solid values on purpose: LibreOffice/PowerPoint render the `transparency`
// text option inconsistently (last glyph of a run gets clipped on export).
const ON_BAND = {
  strong: 'D2D7DF', // subtitle / secondary lines  (80 % paper)
  dim:    '9AA6B7', // inactive TOC rows           (55 % paper)
  faint:  'B1BAC7', // footer                      (65 % paper)
};

const CY = ZONE.content.y;

const LAYOUTS = {
  'figure-left': {
    figs: [{ x: 0.50, y: CY, w: 7.40, h: 4.95 }],
    text: { x: 8.20, y: CY, w: 4.63, h: 4.95 },
  },
  'figure-right': {
    figs: [{ x: 5.43, y: CY, w: 7.40, h: 4.95 }],
    text: { x: 0.50, y: CY, w: 4.63, h: 4.95 },
  },
  'figure-top': {
    figs: [{ x: 0.50, y: CY, w: 12.33, h: 3.10 }],
    text: { x: 0.50, y: 4.80, w: 12.33, h: 1.65 },
  },
  'figure-full': {
    figs: [{ x: 0.50, y: CY, w: 12.33, h: 4.95 }],
    text: null,
    centerX: true,
  },
  'two-up': {
    figs: [
      { x: 0.50, y: CY, w: 6.00, h: 4.40 },
      { x: 6.83, y: CY, w: 6.00, h: 4.40 },
    ],
    text: null,
  },
  'three-up': {
    figs: [
      { x: 0.50, y: CY, w: 3.95, h: 4.40 },
      { x: 4.69, y: CY, w: 3.95, h: 4.40 },
      { x: 8.88, y: CY, w: 3.95, h: 4.40 },
    ],
    text: null,
  },
  'figure-table': {
    figs: [{ x: 0.50, y: CY, w: 6.40, h: 4.95 }],
    table: { x: 7.20, y: CY, w: 5.63, h: 4.95 },
    text: null,
  },
  'figure-stack': {
    figs: [
      { x: 0.50, y: CY,   w: 7.40, h: 2.40 },
      { x: 0.50, y: 4.05, w: 7.40, h: 2.40 },
    ],
    text: { x: 8.20, y: CY, w: 4.63, h: 4.95 },
  },
  'text-only': {
    figs: [],
    text: { x: 0.50, y: CY, w: 12.33, h: 4.95 },
  },
};

const LAYOUT_NAMES = Object.keys(LAYOUTS);
const SLIDE_TYPES = ['title', 'toc', 'intro', 'section', 'content', 'conclusion', 'thanks', 'appendix'];
const CALLOUT_KINDS = ['warn', 'note', 'key'];
const DIAGRAM_KINDS = ['flow', 'axis', 'cards', 'compare'];

// gates
const FILL_MIN = 0.55;
const PPI_MIN = 110;
const TEXT_MIN_IN = 0.12;
const BULLET_MAX = 5;
const TITLE_MAX_IN = 12.0;   // usable width of the title zone on one line
const CAPTION_H = 0.30;
const CAPTION_PT = 10.5;
const CAPTION_GAP = 0.04;
const CALLOUT_GAP = 0.15;

// ---------------------------------------------------------------------------
// 2. Small helpers
// ---------------------------------------------------------------------------

function fontFor(lang) {
  return lang === 'en' ? 'Arial' : 'Malgun Gothic';
}

function isWide(ch) {
  const c = ch.codePointAt(0);
  return (
    (c >= 0x1100 && c <= 0x115f) ||
    (c >= 0x2e80 && c <= 0xa4cf) ||
    (c >= 0xac00 && c <= 0xd7a3) ||
    (c >= 0xf900 && c <= 0xfaff) ||
    (c >= 0xfe30 && c <= 0xfe6f) ||
    (c >= 0xff00 && c <= 0xff60) ||
    (c >= 0xffe0 && c <= 0xffe6)
  );
}

/** Approximate rendered width in inches. en ≈ 0.55 em, ko/CJK ≈ 1.0 em. */
function textWidthIn(str, fontSizePt, bold) {
  let em = 0;
  for (const ch of String(str)) em += isWide(ch) ? 1.0 : 0.55;
  return (em * fontSizePt * (bold ? 1.05 : 1)) / 72;
}

function round(n, d) {
  const f = Math.pow(10, d === undefined ? 3 : d);
  return Math.round(n * f) / f;
}

function shorten(s, n) {
  s = String(s).replace(/\s+/g, ' ');
  return s.length > n ? s.slice(0, n) + '…' : s;
}

// ---------------------------------------------------------------------------
// 3. Schema validation + forbidden scan
// ---------------------------------------------------------------------------

function validateSpec(spec) {
  const errors = [];
  const E = (loc, msg) => errors.push({ loc, msg });

  if (!spec || typeof spec !== 'object') {
    E('$', 'spec root must be an object');
    return errors;
  }
  const meta = spec.meta;
  if (!meta || typeof meta !== 'object') {
    E('meta', 'required object is missing');
  } else {
    if (!meta.title) E('meta.title', 'required non-empty string');
    if (meta.lang && !['ko', 'en'].includes(meta.lang)) {
      E('meta.lang', `must be "ko" or "en" (got ${JSON.stringify(meta.lang)})`);
    }
  }

  const sections = spec.sections || [];
  if (!Array.isArray(sections)) E('sections', 'must be an array');
  const sectionIds = new Set();
  (Array.isArray(sections) ? sections : []).forEach((s, i) => {
    if (!s || typeof s !== 'object') { E(`sections[${i}]`, 'must be an object'); return; }
    if (!s.id) E(`sections[${i}].id`, 'required');
    if (!s.label) E(`sections[${i}].label`, 'required');
    if (s.id) {
      if (sectionIds.has(s.id)) E(`sections[${i}].id`, `duplicate section id ${JSON.stringify(s.id)}`);
      sectionIds.add(s.id);
    }
  });

  if (spec.forbidden !== undefined && !Array.isArray(spec.forbidden)) {
    E('forbidden', 'must be an array of strings');
  }

  if (!Array.isArray(spec.slides) || spec.slides.length === 0) {
    E('slides', 'required non-empty array');
    return errors;
  }

  spec.slides.forEach((sl, i) => {
    const L = `slides[${i}]`;
    if (!sl || typeof sl !== 'object') { E(L, 'must be an object'); return; }
    if (!sl.type) { E(`${L}.type`, 'required'); return; }
    if (!SLIDE_TYPES.includes(sl.type)) {
      E(`${L}.type`, `unknown type ${JSON.stringify(sl.type)} (allowed: ${SLIDE_TYPES.join(', ')})`);
      return;
    }
    if (['intro', 'content', 'appendix', 'conclusion'].includes(sl.type) && !sl.title) {
      E(`${L}.title`, `required for type "${sl.type}"`);
    }
    if (sl.type === 'section') {
      if (!sl.section) E(`${L}.section`, 'required for type "section"');
      else if (!sectionIds.has(sl.section)) E(`${L}.section`, `no section with id ${JSON.stringify(sl.section)}`);
    }
    if (sl.type === 'content') {
      if (!sl.section) E(`${L}.section`, 'required for type "content"');
      else if (!sectionIds.has(sl.section)) E(`${L}.section`, `no section with id ${JSON.stringify(sl.section)}`);
    }
    if (sl.section && sl.type !== 'appendix' && !sectionIds.has(sl.section)) {
      E(`${L}.section`, `no section with id ${JSON.stringify(sl.section)}`);
    }
    if (sl.layout !== undefined) {
      if (sl.layout !== 'auto' && !LAYOUT_NAMES.includes(sl.layout)) {
        E(`${L}.layout`, `unknown layout ${JSON.stringify(sl.layout)} (allowed: auto, ${LAYOUT_NAMES.join(', ')})`);
      }
    }
    if (sl.assets !== undefined) {
      if (!Array.isArray(sl.assets)) E(`${L}.assets`, 'must be an array');
      else sl.assets.forEach((a, j) => {
        if (!a || typeof a !== 'object') { E(`${L}.assets[${j}]`, 'must be an object'); return; }
        if (!a.path) E(`${L}.assets[${j}].path`, 'required');
        if (a.crop !== undefined) {
          if (!Array.isArray(a.crop) || a.crop.length !== 4 || a.crop.some((v) => typeof v !== 'number')) {
            E(`${L}.assets[${j}].crop`, 'must be [x0, y0, x1, y1] numbers in source px');
          } else if (!(a.crop[2] > a.crop[0] && a.crop[3] > a.crop[1])) {
            E(`${L}.assets[${j}].crop`, 'x1 must be > x0 and y1 > y0');
          }
        }
      });
    }
    if (sl.bullets !== undefined && !Array.isArray(sl.bullets)) E(`${L}.bullets`, 'must be an array of strings');
    if (sl.diagram !== undefined) {
      const d = sl.diagram;
      if (typeof d !== 'object' || d === null) E(`${L}.diagram`, 'must be an object');
      else if (!DIAGRAM_KINDS.includes(d.kind)) {
        E(`${L}.diagram.kind`, `must be one of ${DIAGRAM_KINDS.join(' | ')} (got ${JSON.stringify(d.kind)})`);
      } else if (d.kind === 'flow') {
        if (!Array.isArray(d.steps) || d.steps.length < 2 || d.steps.length > 5) {
          E(`${L}.diagram.steps`, 'flow needs 2–5 steps');
        } else d.steps.forEach((s, j) => {
          if (!s || typeof s !== 'object' || !s.label) E(`${L}.diagram.steps[${j}].label`, 'required');
        });
      } else if (d.kind === 'axis') {
        if (!Array.isArray(d.zones) || d.zones.length === 0) E(`${L}.diagram.zones`, 'axis needs a non-empty zones array');
        else d.zones.forEach((z, j) => {
          if (!z || typeof z !== 'object') { E(`${L}.diagram.zones[${j}]`, 'must be an object'); return; }
          if (typeof z.from !== 'number' || typeof z.to !== 'number') E(`${L}.diagram.zones[${j}]`, 'from/to must be numbers (0–1 fraction of the axis)');
          else if (!(z.to > z.from)) E(`${L}.diagram.zones[${j}]`, 'to must be > from');
        });
        if (d.ticks !== undefined && !Array.isArray(d.ticks)) E(`${L}.diagram.ticks`, 'must be an array of strings');
      } else if (d.kind === 'cards') {
        if (!Array.isArray(d.items) || d.items.length < 2 || d.items.length > 4) {
          E(`${L}.diagram.items`, 'cards needs 2–4 items');
        } else d.items.forEach((c, j) => {
          if (!c || typeof c !== 'object' || !c.title) E(`${L}.diagram.items[${j}].title`, 'required');
        });
      } else if (d.kind === 'compare') {
        for (const side of ['left', 'right']) {
          const p = d[side];
          if (!p || typeof p !== 'object') { E(`${L}.diagram.${side}`, 'required object'); continue; }
          if (!p.title) E(`${L}.diagram.${side}.title`, 'required');
          if (p.lines !== undefined && !Array.isArray(p.lines)) E(`${L}.diagram.${side}.lines`, 'must be an array of strings');
        }
      }
      if (!['content', 'appendix', 'intro'].includes(sl.type)) {
        E(`${L}.diagram`, `only content/appendix/intro slides can carry a diagram (type is "${sl.type}")`);
      }
    }
    if (sl.callout !== undefined) {
      if (typeof sl.callout !== 'object' || sl.callout === null) E(`${L}.callout`, 'must be an object');
      else {
        if (!sl.callout.text) E(`${L}.callout.text`, 'required');
        if (sl.callout.kind && !CALLOUT_KINDS.includes(sl.callout.kind)) {
          E(`${L}.callout.kind`, `must be one of ${CALLOUT_KINDS.join(' | ')}`);
        }
      }
    }
    if (sl.table !== undefined) {
      const t = sl.table;
      if (typeof t !== 'object' || t === null) E(`${L}.table`, 'must be an object');
      else {
        if (!Array.isArray(t.header) || t.header.length === 0) E(`${L}.table.header`, 'required non-empty array');
        if (!Array.isArray(t.rows) || t.rows.length === 0) E(`${L}.table.rows`, 'required non-empty array');
        else t.rows.forEach((r, j) => {
          if (!Array.isArray(r)) E(`${L}.table.rows[${j}]`, 'must be an array of strings');
          else if (Array.isArray(t.header) && r.length !== t.header.length) {
            E(`${L}.table.rows[${j}]`, `has ${r.length} cells but header has ${t.header.length}`);
          }
        });
        if (t.highlight_row !== undefined) {
          if (typeof t.highlight_row !== 'number' || t.highlight_row < 0 ||
              (Array.isArray(t.rows) && t.highlight_row >= t.rows.length)) {
            E(`${L}.table.highlight_row`, 'must be a valid index into rows');
          }
        }
      }
    }
    if (sl.type === 'conclusion' && sl.items !== undefined && !Array.isArray(sl.items)) {
      E(`${L}.items`, 'must be an array of strings');
    }
    if (sl.type === 'thanks' && sl.lines !== undefined && !Array.isArray(sl.lines)) {
      E(`${L}.lines`, 'must be an array of strings');
    }
  });

  return errors;
}

/** Walk every human-readable string of the spec and report forbidden hits. */
const SKIP_KEYS = new Set(['path', 'ledger_id', 'layout', 'type', 'section', 'theme', 'lang', 'crop', 'forbidden']);

function scanForbidden(spec) {
  const needles = (spec.forbidden || []).filter((s) => typeof s === 'string' && s.length > 0);
  const hits = [];
  if (needles.length === 0) return hits;

  const walk = (node, loc) => {
    if (typeof node === 'string') {
      for (const n of needles) {
        if (node.includes(n)) hits.push({ loc, needle: n, text: shorten(node, 90) });
      }
      return;
    }
    if (Array.isArray(node)) { node.forEach((v, i) => walk(v, `${loc}[${i}]`)); return; }
    if (node && typeof node === 'object') {
      for (const [k, v] of Object.entries(node)) {
        if (SKIP_KEYS.has(k)) continue;
        walk(v, loc ? `${loc}.${k}` : k);
      }
    }
  };
  walk({ meta: spec.meta, sections: spec.sections, slides: spec.slides }, '');
  return hits;
}

// ---------------------------------------------------------------------------
// 4. Image measurement / cropping / fitting
// ---------------------------------------------------------------------------

function measurePx(file) {
  if (imageSize) {
    const fn = imageSize.imageSize || imageSize.default || imageSize;
    const d = fn(fs.readFileSync(file));
    if (d && d.width && d.height) return { width: d.width, height: d.height };
  }
  throw new Error(`cannot measure image size: ${file}`);
}

async function prepareAsset(asset, specDir, cropDir, idx, slideIdx) {
  const src = path.isAbsolute(asset.path) ? asset.path : path.resolve(specDir, asset.path);
  if (!fs.existsSync(src)) throw new Error(`asset not found: ${src}`);

  let file = src;
  let px = measurePx(src);
  let cropped = false;

  if (Array.isArray(asset.crop)) {
    const [x0, y0, x1, y1] = asset.crop.map((v) => Math.round(v));
    const left = Math.max(0, Math.min(x0, px.width - 1));
    const top = Math.max(0, Math.min(y0, px.height - 1));
    const width = Math.max(1, Math.min(x1 - x0, px.width - left));
    const height = Math.max(1, Math.min(y1 - y0, px.height - top));
    if (!sharp) throw new Error('crop requested but sharp is not installed (run npm install in scripts/)');
    fs.mkdirSync(cropDir, { recursive: true });
    const base = path.basename(src, path.extname(src));
    file = path.join(cropDir, `s${String(slideIdx + 1).padStart(2, '0')}_a${idx + 1}_${base}.png`);
    await sharp(src).extract({ left, top, width, height }).png().toFile(file);
    px = { width, height };
    cropped = true;
  }

  return { file, srcPath: src, px, cropped, caption: asset.caption || '', minTextPx: asset.min_text_px, ledgerId: asset.ledger_id };
}

/** contain-fit, top(-left) aligned. Returns {x,y,w,h,fill_ratio}. */
function fitContain(px, box, centerX) {
  const ar = px.width / px.height;
  let w = box.w;
  let h = w / ar;
  if (h > box.h) { h = box.h; w = h * ar; }
  const x = centerX ? box.x + (box.w - w) / 2 : box.x;
  const y = box.y; // top aligned, always
  return { x, y, w, h, fill_ratio: (w * h) / (box.w * box.h) };
}

// ---------------------------------------------------------------------------
// 5. Layout selection — layout-grid.md §2
// ---------------------------------------------------------------------------

function chooseLayout(declared, prepared, hasTable, hasDiagram, hasBullets) {
  if (declared && declared !== 'auto') return { name: declared, auto: false };
  const n = prepared.length;
  // A diagram occupies a figure box, so an asset-less diagram slide still needs
  // one — unless the diagram is alone on the slide, which gets the full width.
  if (n === 0 && hasDiagram) {
    if (hasTable) return { name: 'figure-table', auto: true };
    return { name: hasBullets ? 'figure-left' : 'text-only', auto: true };
  }
  if (n === 0) return { name: 'text-only', auto: true };
  if (hasTable) return { name: 'figure-table', auto: true };
  const ar = prepared[0].px.width / prepared[0].px.height;
  if (n === 1) {
    if (ar >= 2.4) return { name: 'figure-top', auto: true };
    if (ar >= 1.2) return { name: 'figure-left', auto: true };
    return { name: 'figure-right', auto: true };
  }
  if (n === 2) return { name: ar >= 1.5 ? 'figure-stack' : 'two-up', auto: true };
  return { name: 'three-up', auto: true };
}

// ---------------------------------------------------------------------------
// 6. Render primitives
// ---------------------------------------------------------------------------

function addBand(slide, ctx, leftText, rightText) {
  slide.addShape(ctx.pres.shapes.RECTANGLE, {
    x: ZONE.band.x, y: ZONE.band.y, w: ZONE.band.w, h: ZONE.band.h,
    fill: { color: COLOR.band }, line: { color: COLOR.band, width: 0 },
  });
  if (leftText) {
    slide.addText(String(leftText), {
      x: 0.50, y: 0.02, w: 10.0, h: 0.38, margin: 0,
      fontFace: ctx.font, fontSize: 12, bold: true, color: COLOR.paper, valign: 'middle', align: 'left',
    });
  }
  if (rightText) {
    slide.addText(String(rightText), {
      x: 10.6, y: 0.02, w: 2.23, h: 0.38, margin: 0,
      fontFace: ctx.font, fontSize: 11, color: COLOR.paper, valign: 'middle', align: 'right',
    });
  }
}

function addTitle(slide, ctx, title, warnings) {
  // titles are one line — measure, do not count characters
  const w26 = textWidthIn(title, 26, true);
  const long = w26 > TITLE_MAX_IN;
  if (long) {
    warnings.push({ code: 'TITLE_LONG', detail: `title needs ${round(w26, 2)} in at 26 pt (> ${TITLE_MAX_IN}) — rendered at 22 pt` });
    const w22 = textWidthIn(title, 22, true);
    if (w22 > TITLE_MAX_IN) {
      warnings.push({ code: 'TITLE_OVERFLOW', detail: `title still needs ${round(w22, 2)} in at 22 pt (> ${TITLE_MAX_IN}) — shorten it, titles may not wrap` });
    }
  }
  slide.addText(String(title), {
    x: ZONE.title.x, y: ZONE.title.y, w: ZONE.title.w, h: ZONE.title.h, margin: 0,
    fontFace: ctx.font, fontSize: long ? 22 : 26, bold: true, color: COLOR.ink,
    valign: 'middle', align: 'left',
  });
  slide.addShape(ctx.pres.shapes.RECTANGLE, {
    x: ZONE.title.x, y: ZONE.title.y + ZONE.title.h + 0.02, w: 1.30, h: 0.045,
    fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
  });
}

function addBottomLine(slide, ctx, text) {
  slide.addShape(ctx.pres.shapes.RECTANGLE, {
    x: ZONE.bottom.x, y: ZONE.bottom.y, w: ZONE.bottom.w, h: ZONE.bottom.h,
    fill: { color: COLOR.bottom }, line: { color: COLOR.bottom, width: 0 },
  });
  slide.addText(String(text), {
    x: ZONE.bottom.x + 0.18, y: ZONE.bottom.y, w: ZONE.bottom.w - 0.36, h: ZONE.bottom.h, margin: 0,
    fontFace: ctx.font, fontSize: 14, bold: true, color: COLOR.ink, valign: 'middle', align: 'left',
  });
}

function addFooter(slide, ctx) {
  if (!ctx.meta.footer) return;
  slide.addText(String(ctx.meta.footer), {
    x: 8.33, y: 7.18, w: 4.50, h: 0.26, margin: 0,
    fontFace: ctx.font, fontSize: 9, color: COLOR.ink2, align: 'right', valign: 'middle',
  });
}

function addCaption(slide, ctx, caption, placed, box, limit) {
  if (!caption) return placed.y + placed.h;
  const stop = limit === undefined ? CONTENT_BOTTOM : limit;
  let y = placed.y + placed.h + CAPTION_GAP;
  let h = CAPTION_H;
  if (y + h > stop) { h = Math.max(0.20, stop - y); y = stop - h; }
  slide.addText(String(caption), {
    x: box.x, y, w: box.w, h, margin: 0,
    fontFace: ctx.font, fontSize: CAPTION_PT, color: COLOR.ink2, valign: 'top', align: 'left',
  });
  return y + h;
}

/**
 * Bullets, top aligned, with a 2 pt downshift on overflow.
 * `opts.base` is 16 pt beside a figure and 20 pt in the full-width text-only
 * box, where 16 pt on a 12.33 in line reads sparse.
 */
function addBullets(slide, ctx, bullets, box, warnings, opts) {
  const base = (opts && opts.base) || 16;
  const lineMult = (opts && opts.lineMult) || 0;      // 0 = pptx default spacing
  const paraAfter = (opts && opts.paraAfter) || 5;
  const items = bullets.filter((b) => b !== undefined && b !== null && String(b).length > 0).map(String);
  if (items.length === 0) return { usedH: 0, fontSize: base };
  if (items.length > BULLET_MAX) {
    warnings.push({ code: 'BULLET_OVERFLOW', detail: `${items.length} bullets > max ${BULLET_MAX}` });
  }

  const usable = box.w - 0.30; // bullet glyph + indent
  const measure = (fs_) => {
    let lines = 0;
    for (const it of items) lines += Math.max(1, Math.ceil(textWidthIn(it, fs_) / usable));
    const lineH = (fs_ * (lineMult ? lineMult * 1.2 : 1.45)) / 72;
    return { lines, h: lines * lineH + (items.length - 1) * (paraAfter / 72) };
  };

  let fontSize = base;
  let m = measure(fontSize);
  if (m.h > box.h) {
    fontSize = base - 2;
    const mSmall = measure(fontSize);
    warnings.push({
      code: 'BULLET_OVERFLOW',
      detail: `bullets need ${round(m.h, 2)} in at ${base} pt but box is ${round(box.h, 2)} in — dropped to ${fontSize} pt (${round(mSmall.h, 2)} in)`,
    });
    m = mSmall;
    if (m.h > box.h) {
      warnings.push({ code: 'BULLET_OVERFLOW', detail: `still overflowing at ${fontSize} pt (${round(m.h, 2)} in > ${round(box.h, 2)} in) — split the slide` });
    }
  }

  const runs = items.map((t, i) => ({
    text: t,
    options: { bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: paraAfter },
  }));
  const textOpts = {
    x: box.x, y: box.y, w: box.w, h: Math.min(box.h, Math.max(m.h, 0.4)), margin: 0,
    fontFace: ctx.font, fontSize, color: COLOR.ink, valign: 'top', align: 'left',
  };
  if (lineMult) textOpts.lineSpacingMultiple = lineMult;
  slide.addText(runs, textOpts);
  return { usedH: Math.min(m.h, box.h), fontSize };
}

function addCallout(slide, ctx, callout, box, afterH, warnings) {
  const kind = callout.kind || 'note';
  const palette = {
    warn: { line: COLOR.warn, fill: 'FDF1E3', text: COLOR.ink },
    note: { line: COLOR.ink2, fill: 'F3F4F6', text: COLOR.ink2 },
    key:  { line: COLOR.accent, fill: 'E4F1F1', text: COLOR.ink },
  }[kind];

  const text = String(callout.text);
  const inner = box.w - 0.30;
  const lines = Math.max(1, Math.ceil(textWidthIn(text, 12) / inner));
  const h = Math.max(0.48, lines * 0.24 + 0.20);
  let y = box.y + afterH + (afterH > 0 ? CALLOUT_GAP : 0);
  if (y + h > CONTENT_BOTTOM) {
    if (warnings) {
      warnings.push({
        code: 'BULLET_OVERFLOW',
        detail: `callout would end at ${round(y + h, 2)} in, past the content floor ${CONTENT_BOTTOM} — bullets and callout do not both fit`,
      });
    }
    y = Math.max(box.y, CONTENT_BOTTOM - h);
  }

  slide.addShape(ctx.pres.shapes.RECTANGLE, {
    x: box.x, y, w: box.w, h,
    fill: { color: palette.fill }, line: { color: palette.line, width: 1.25 },
  });
  slide.addText(text, {
    x: box.x + 0.14, y: y + 0.05, w: box.w - 0.28, h: h - 0.10, margin: 0,
    fontFace: ctx.font, fontSize: 12, color: palette.text, valign: 'middle', align: 'left',
  });
  return y + h - box.y;
}

function addTable(slide, ctx, table, box, wide) {
  const nCols = table.header.length;
  const colW = new Array(nCols).fill(round(box.w / nCols, 3));
  const head = table.header.map((c) => ({
    text: String(c),
    options: { fill: { color: COLOR.band }, color: COLOR.paper, bold: true, align: 'center' },
  }));
  const body = table.rows.map((r, i) => {
    const hi = table.highlight_row === i;
    return r.map((c) => ({
      text: String(c),
      options: {
        color: hi ? COLOR.accent : COLOR.ink,
        bold: !!hi,
        align: 'center',
        fill: { color: hi ? 'F2F8F8' : COLOR.paper },
      },
    }));
  });
  const rowH = wide ? 0.45 : Math.min(0.42, (box.h - 0.2) / (body.length + 1));
  // Declare the frame height as the sum of the rows: PowerPoint sizes the frame
  // from it, and deck_qa's FILL_RATIO reads the declared height (pptxgenjs
  // would otherwise write its 1.0 in default and the table looks 20 % tall).
  slide.addTable([head, ...body], {
    x: box.x, y: box.y, w: box.w, h: round(rowH * (body.length + 1), 3), colW,
    fontFace: ctx.font, fontSize: wide ? 16 : 12, color: COLOR.ink,
    border: { pt: 0.75, color: 'C9D2DC' },
    rowH,
    valign: 'middle',
  });
}

// --- native diagrams -------------------------------------------------------
// Drawn with pptxgenjs shapes so every element stays editable in PowerPoint.
// Each diagram FILLS the box it was assigned (content zone when it is alone on
// the slide, the layout's figure box when bullets or a table share the slide) —
// a diagram that only occupies the top inch is exactly the "slide that empties
// downward" the fixed grid exists to prevent. Container shapes carry their own
// text so they read as one editable object. No text below DIAGRAM_PT_MIN.

const DIAGRAM_PT_MIN = 12;

function diagFlow(slide, ctx, d, box) {
  const steps = d.steps;
  const n = steps.length;
  const gap = Math.max(0.30, Math.min(0.44, box.w * 0.035));
  // A box taller than it is wide cannot hold a readable left-to-right row, so
  // the flow runs top-to-bottom instead. Otherwise: one row, or two if that
  // would squeeze the cards below a readable width (Z order: right, then down).
  const vertical = box.w / box.h < 1.3;
  const gapY = vertical ? 0.25 : 0.28;
  const perRow = vertical ? 1 : ((box.w - (n - 1) * gap) / n >= 2.0 ? n : Math.ceil(n / 2));
  const rows = Math.ceil(n / perRow);
  const cardW = (box.w - (perRow - 1) * gap) / perRow;
  const cardH = vertical
    ? (box.h - (n - 1) * gapY) / n
    : Math.max(1.8, (box.h - (rows - 1) * gapY) / rows);

  if (vertical) {
    for (let i = 0; i < n - 1; i++) {
      slide.addShape(ctx.pres.shapes.DOWN_ARROW, {
        x: box.x + box.w / 2 - 0.17, y: box.y + (i + 1) * cardH + i * gapY + 0.01,
        w: 0.34, h: gapY - 0.02,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
    }
  } else if (rows === 2) {
    slide.addShape(ctx.pres.shapes.DOWN_ARROW, {
      x: box.x + box.w / 2 - 0.17, y: box.y + cardH + 0.01, w: 0.34, h: gapY - 0.02,
      fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
    });
  }

  for (let i = 0; i < n; i++) {
    const col = i % perRow;
    const x = box.x + col * (cardW + gap);
    const y = box.y + Math.floor(i / perRow) * (cardH + gapY);
    const runs = [{
      text: String(steps[i].label),
      options: { fontSize: 18, bold: true, color: COLOR.ink, breakLine: !!steps[i].sub },
    }];
    if (steps[i].sub) {
      runs.push({ text: String(steps[i].sub), options: { fontSize: 14, color: COLOR.ink2 } });
    }
    slide.addText(runs, {
      shape: ctx.pres.shapes.ROUNDED_RECTANGLE,
      x, y, w: cardW, h: cardH, rectRadius: 0.08,
      fill: { color: COLOR.paper }, line: { color: COLOR.band, width: 1.75 },
      fontFace: ctx.font, valign: 'middle', align: 'center', margin: 10,
    });
    slide.addShape(ctx.pres.shapes.RECTANGLE, {
      x: x + (cardW - 0.44) / 2, y: y + 0.22, w: 0.44, h: 0.07,
      fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
    });
    if (!vertical && col < perRow - 1 && i < n - 1) {
      slide.addShape(ctx.pres.shapes.RIGHT_ARROW, {
        x: x + cardW + 0.04, y: y + cardH / 2 - 0.17, w: gap - 0.08, h: 0.34,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
    }
  }
  return rows * cardH + (rows - 1) * gapY;
}

function diagAxis(slide, ctx, d, box) {
  // "수직선" here is a number line: a horizontal axis with shaded zones above it
  // and tick labels below (see references/spec-schema.md example, D_agg/D_L).
  const x0 = box.x;
  const w = box.w;
  const footer = d.caption ? 1.00 : 0.70; // line + tick labels (+ caption)
  const zoneH = Math.max(0.9, box.h - footer);
  const zoneY = box.y;

  (d.zones || []).forEach((z) => {
    const zx = x0 + Math.max(0, Math.min(1, z.from)) * w;
    const zw = Math.max(0.05, (Math.min(1, z.to) - Math.max(0, z.from)) * w);
    slide.addText(z.label ? String(z.label) : '', {
      shape: ctx.pres.shapes.RECTANGLE,
      x: zx, y: zoneY, w: zw, h: zoneH,
      fill: { color: z.accent ? COLOR.accent : 'DDE4EC' },
      line: { color: z.accent ? COLOR.accent : 'C9D2DC', width: 1 },
      fontFace: ctx.font, fontSize: 14, bold: !!z.accent,
      color: z.accent ? COLOR.paper : COLOR.ink2,
      valign: 'middle', align: 'center', margin: 6,
    });
  });

  const lineY = zoneY + zoneH + 0.20;
  slide.addShape(ctx.pres.shapes.LINE, {
    x: x0, y: lineY, w, h: 0,
    line: { color: COLOR.ink, width: 4 },
  });

  const ticks = Array.isArray(d.ticks) && d.ticks.length ? d.ticks
    : [d.min, d.max].filter((v) => v !== undefined && v !== null).map(String);
  const denom = Math.max(1, ticks.length - 1);
  ticks.forEach((t, i) => {
    const tx = x0 + (ticks.length === 1 ? 0 : (i / denom) * w);
    slide.addShape(ctx.pres.shapes.LINE, {
      x: tx, y: lineY, w: 0, h: 0.14,
      line: { color: COLOR.ink, width: 2.5 },
    });
    slide.addText(String(t), {
      x: tx - 0.70, y: lineY + 0.16, w: 1.40, h: 0.28, margin: 0,
      fontFace: ctx.font, fontSize: 14, color: COLOR.ink, valign: 'top', align: 'center',
    });
  });

  if (d.caption) {
    slide.addText(String(d.caption), {
      x: box.x, y: lineY + 0.48, w: box.w, h: 0.32, margin: 0,
      fontFace: ctx.font, fontSize: 14, color: COLOR.ink2, valign: 'top', align: 'center',
    });
  }
  return Math.max(0.9, box.h);
}

function diagCards(slide, ctx, d, box, sharesFigures) {
  const items = d.items;
  const n = items.length;
  const cols = n === 4 ? 2 : n;          // 2 → 2열, 3 → 3열, 4 → 2 × 2
  const rows = Math.ceil(n / cols);
  const gapX = 0.33;
  const gapY = 0.25;
  const w = (box.w - (cols - 1) * gapX) / cols;
  const cellH = (box.h - (rows - 1) * gapY) / rows;

  let bodyLines = 0;
  let titleLines = 1;
  for (const c of items) {
    titleLines = Math.max(titleLines, Math.ceil(textWidthIn(String(c.title), 20, true) / (w - 0.44)));
    if (c.body) bodyLines = Math.max(bodyLines, Math.ceil(textWidthIn(String(c.body), 16) / (w - 0.44)));
  }
  const contentH = 0.22 + titleLines * 0.36 + (bodyLines ? 0.08 + bodyLines * 0.30 : 0) + 0.18;

  // Two rules, because the failure they prevent is different in each case.
  //  - sharing the figure area with a real figure: a card stretched to the grid
  //    cell with two lines in it is a half-empty box, so size to content;
  //  - owning the figure area: the cards ARE the exhibit, so they take the cell,
  //    with 1.3 line spacing filling them, and only genuinely short cards shrink
  //    — never past 60 % of the box.
  const h = sharesFigures
    ? (bodyLines <= 2 ? Math.min(cellH, Math.max(1.6, contentH)) : cellH)
    : (titleLines + bodyLines <= 2 ? Math.min(cellH, Math.max(0.6 * box.h, contentH)) : cellH);

  items.forEach((c, i) => {
    const x = box.x + (i % cols) * (w + gapX);
    const y = box.y + Math.floor(i / cols) * (h + gapY);
    const runs = [{
      text: String(c.title),
      options: { fontSize: 20, bold: true, color: COLOR.band, breakLine: !!c.body },
    }];
    if (c.body) {
      runs.push({ text: String(c.body), options: { fontSize: 16, color: COLOR.ink2, paraSpaceBefore: 6 } });
    }
    const cardOpts = {
      shape: ctx.pres.shapes.ROUNDED_RECTANGLE,
      x, y, w, h, rectRadius: 0.07,
      fill: { color: 'F7F9FB' }, line: { color: 'C9D2DC', width: 1.25 },
      fontFace: ctx.font, valign: 'top', align: 'left', margin: 16,
    };
    if (!sharesFigures) cardOpts.lineSpacingMultiple = 1.3;
    slide.addText(runs, cardOpts);
    slide.addShape(ctx.pres.shapes.RECTANGLE, {
      x, y, w: 0.09, h,
      fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
    });
  });
  return rows * h + (rows - 1) * gapY;
}

function diagCompare(slide, ctx, d, box) {
  const gap = 0.33;
  const w = (box.w - gap) / 2;
  const headH = 0.60;
  const sides = [
    { p: d.left, x: box.x, color: COLOR.ink2 },
    { p: d.right, x: box.x + w + gap, color: COLOR.accent },
  ];
  for (const s of sides) {
    const lines = (s.p.lines || []).map(String);
    slide.addText(lines.length ? lines.map((t, i) => ({
      text: t,
      options: { bullet: true, breakLine: i < lines.length - 1, paraSpaceAfter: 8 },
    })) : '', {
      shape: ctx.pres.shapes.RECTANGLE,
      x: s.x, y: box.y + headH, w, h: box.h - headH,
      fill: { color: COLOR.paper }, line: { color: s.color, width: 1.5 },
      fontFace: ctx.font, fontSize: 16, color: COLOR.ink,
      valign: 'top', align: 'left', margin: 14,
    });
    slide.addText(String(s.p.title), {
      shape: ctx.pres.shapes.RECTANGLE,
      x: s.x, y: box.y, w, h: headH,
      fill: { color: s.color }, line: { color: s.color, width: 1.5 },
      fontFace: ctx.font, fontSize: 20, bold: true, color: COLOR.paper,
      valign: 'middle', align: 'left', margin: 14,
    });
  }
  return box.h;
}

function renderDiagram(slide, ctx, d, box, sharesFigures) {
  const fn = { flow: diagFlow, axis: diagAxis, cards: diagCards, compare: diagCompare }[d.kind];
  fn(slide, ctx, d, box, sharesFigures);
  return d.kind;
}

/** Table of contents body — used by both toc and section slides. */
function addTocList(slide, ctx, sections, activeId, onDark) {
  const top = ZONE.content.y + 0.25;
  const rowH = Math.min(0.72, (ZONE.content.h - 0.5) / Math.max(sections.length, 1));
  sections.forEach((s, i) => {
    const active = activeId && s.id === activeId;
    const y = top + i * rowH;
    if (active) {
      slide.addShape(ctx.pres.shapes.RECTANGLE, {
        x: 0.50, y: y + 0.06, w: 0.09, h: rowH - 0.18,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
    }
    const opts = {
      x: 0.78, y, w: 11.9, h: rowH, margin: 0,
      fontFace: ctx.font, fontSize: 20, valign: 'middle', align: 'left',
      bold: !!active,
    };
    if (onDark) {
      opts.color = active ? COLOR.paper : ON_BAND.dim;
    } else {
      opts.color = active ? COLOR.accent : COLOR.ink2;
    }
    slide.addText(`${s.id}. ${s.label}`, opts);
  });
}

// ---------------------------------------------------------------------------
// 7. Slide renderers
// ---------------------------------------------------------------------------

/**
 * Lowest y a figure box's caption may reach: the top of whatever box sits under
 * it (the next figure box, the text box, the table box), else the content floor.
 */
function captionLimit(L, box) {
  const under = [...L.figs, L.text, L.table]
    .filter((b) => b && b.y > box.y + 0.01)
    .map((b) => b.y);
  return under.length ? Math.min(...under) : CONTENT_BOTTOM;
}

async function renderFigures(slide, ctx, prepared, layoutName, warnings, report) {
  const L = LAYOUTS[layoutName];
  const boxes = L.figs;
  const placements = [];
  if (boxes.length === 0) return placements;

  const n = Math.min(prepared.length, boxes.length);
  if (prepared.length > boxes.length) {
    warnings.push({
      code: 'ASSET_EXTRA',
      detail: `${prepared.length} assets but layout "${layoutName}" has ${boxes.length} figure box(es) — extras dropped`,
    });
  }

  for (let i = 0; i < n; i++) {
    const a = prepared[i];
    const box = boxes[i];
    const limit = captionLimit(L, box);
    // the caption may never be covered by the box below: if it does not fit,
    // give the caption its band back by shrinking the figure, not the caption
    let fitBox = box;
    if (a.caption) {
      const trial = fitContain(a.px, box, !!L.centerX);
      if (trial.y + trial.h + CAPTION_GAP + CAPTION_H > limit) {
        fitBox = { ...box, h: Math.max(0.5, box.h - (CAPTION_H + CAPTION_GAP)) };
      }
    }
    const placed = fitContain(a.px, fitBox, !!L.centerX);
    slide.addImage({ path: a.file, x: round(placed.x), y: round(placed.y), w: round(placed.w), h: round(placed.h) });
    const contentBottom = addCaption(slide, ctx, a.caption, placed, box, limit);
    placements.push({ boxIndex: i, box, placed, contentBottom });

    const ppi = a.px.width / placed.w;
    const rec = {
      path: path.relative(ctx.specDir, a.srcPath).replace(/\\/g, '/'),
      native_px: [a.px.width, a.px.height],
      native_ar: round(a.px.width / a.px.height, 4),
      cropped: a.cropped,
      placed_in: { x: round(placed.x), y: round(placed.y), w: round(placed.w), h: round(placed.h) },
      placed_ar: round(placed.w / placed.h, 4),
      scale_ppi: round(ppi, 1),
      fill_ratio: round((placed.w * placed.h) / (fitBox.w * fitBox.h), 3),
    };
    const fillRatio = (placed.w * placed.h) / (fitBox.w * fitBox.h);
    if (fillRatio < FILL_MIN) {
      warnings.push({ code: 'FILL_LOW', detail: `${path.basename(a.srcPath)} fills ${(fillRatio * 100).toFixed(1)}% of its box (< ${round(FILL_MIN * 100, 0)}%) in "${layoutName}"` });
    }
    if (ppi < PPI_MIN) {
      warnings.push({ code: 'PPI_LOW', detail: `${path.basename(a.srcPath)} placed at ${ppi.toFixed(0)} ppi (< ${PPI_MIN})` });
    }
    const rawMinText = a.minTextPx !== undefined ? a.minTextPx : ctx.ledger[a.ledgerId] && ctx.ledger[a.ledgerId].min_text_px;
    // 0 or "none" means the figure carries no text at all — nothing to shrink
    const noText = rawMinText === 0 || rawMinText === '0' ||
      (typeof rawMinText === 'string' && rawMinText.trim().toLowerCase() === 'none');
    const minTextPx = noText ? null : rawMinText;
    if (typeof minTextPx === 'number' && minTextPx > 0) {
      const onSlide = minTextPx * (placed.h / a.px.height);
      rec.min_text_in = round(onSlide, 4);
      if (onSlide < TEXT_MIN_IN) {
        warnings.push({ code: 'TEXT_TINY', detail: `${path.basename(a.srcPath)} smallest glyph renders at ${onSlide.toFixed(3)} in (< ${TEXT_MIN_IN})` });
      }
    }
    report.assets.push(rec);
  }
  return placements;
}

function bandLeftFor(ctx, sl) {
  if (sl.type === 'appendix') return 'Appendix';
  if (sl.section) {
    const s = ctx.sectionById[sl.section];
    if (s) return `${s.id}. ${s.label}`;
    return String(sl.section);
  }
  if (sl.type === 'intro') return ctx.ko ? '소개' : 'Intro';
  if (sl.type === 'conclusion') return ctx.ko ? '결론' : 'Conclusion';
  if (sl.type === 'toc') return ctx.ko ? '목차' : 'Contents';
  return '';
}

async function renderSlide(ctx, sl, report) {
  const warnings = report.warnings;
  const slide = ctx.pres.addSlide();
  const font = ctx.font;

  switch (sl.type) {
    // ------------------------------------------------------------- title
    case 'title': {
      slide.background = { color: COLOR.band };
      slide.addShape(ctx.pres.shapes.RECTANGLE, {
        x: 0, y: 0, w: SLIDE_W, h: 0.52,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
      if (ctx.meta.event) {
        slide.addText(String(ctx.meta.event), {
          x: 0.60, y: 0, w: 12.13, h: 0.52, margin: 0,
          fontFace: font, fontSize: 13, bold: true, color: COLOR.paper, valign: 'middle', align: 'left',
        });
      }
      slide.addText(String(ctx.meta.title), {
        x: 0.90, y: 2.05, w: 11.5, h: 1.70, margin: 0,
        fontFace: font, fontSize: 36, bold: true, color: COLOR.paper, valign: 'bottom', align: 'left',
      });
      slide.addShape(ctx.pres.shapes.RECTANGLE, {
        x: 0.92, y: 3.90, w: 2.20, h: 0.06,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
      if (ctx.meta.subtitle) {
        slide.addText(String(ctx.meta.subtitle), {
          x: 0.90, y: 4.10, w: 11.5, h: 0.60, margin: 0,
          fontFace: font, fontSize: 18, color: ON_BAND.strong, valign: 'top', align: 'left',
        });
      }
      const who = [ctx.meta.presenter, ctx.meta.affiliation].filter(Boolean);
      if (who.length) {
        slide.addText(who.map((t, i) => ({ text: t, options: { breakLine: i < who.length - 1, bold: i === 0 } })), {
          x: 0.90, y: 5.40, w: 11.5, h: 1.00, margin: 0,
          fontFace: font, fontSize: 15, color: COLOR.paper, valign: 'top', align: 'left',
        });
      }
      if (ctx.meta.footer) {
        slide.addText(String(ctx.meta.footer), {
          x: 8.33, y: 6.90, w: 4.40, h: 0.30, margin: 0,
          fontFace: font, fontSize: 11, color: ON_BAND.faint, align: 'right', valign: 'middle',
        });
      }
      break;
    }

    // --------------------------------------------------------------- toc
    case 'toc': {
      addBand(slide, ctx, bandLeftFor(ctx, sl), report.number_label);
      addTitle(slide, ctx, sl.title || (ctx.ko ? '목차' : 'Contents'), warnings);
      addTocList(slide, ctx, ctx.sections, null, false);
      if (sl.bottom_line) addBottomLine(slide, ctx, sl.bottom_line);
      addFooter(slide, ctx);
      break;
    }

    // ----------------------------------------------------------- section
    case 'section': {
      const s = ctx.sectionById[sl.section];
      slide.background = { color: COLOR.band };
      slide.addText(`${s.id}. ${s.label}`, {
        x: 0.50, y: 0.62, w: 12.33, h: 0.70, margin: 0,
        fontFace: font, fontSize: 26, bold: true, color: COLOR.paper, valign: 'middle', align: 'left',
      });
      slide.addShape(ctx.pres.shapes.RECTANGLE, {
        x: 0.50, y: 1.36, w: 1.30, h: 0.045,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
      addTocList(slide, ctx, ctx.sections, sl.section, true);
      break;
    }

    // -------------------------------------------- intro / content / appendix
    case 'intro':
    case 'content':
    case 'appendix': {
      addBand(slide, ctx, bandLeftFor(ctx, sl), report.number_label);
      addTitle(slide, ctx, sl.title, warnings);

      const prepared = [];
      const cropDir = path.join(ctx.buildDir, 'crops');
      for (let i = 0; i < (sl.assets || []).length; i++) {
        prepared.push(await prepareAsset(sl.assets[i], ctx.specDir, cropDir, i, report.index - 1));
      }
      const hasBullets = Array.isArray(sl.bullets) && sl.bullets.length > 0;
      const chosen = chooseLayout(sl.layout, prepared, !!sl.table, !!sl.diagram, hasBullets);
      report.layout_chosen = chosen.name;
      report.layout_auto = chosen.auto;
      const L = LAYOUTS[chosen.name];

      const placements = await renderFigures(slide, ctx, prepared, chosen.name, warnings, report);

      if (sl.diagram) {
        // A diagram takes the figure box of the chosen layout; layouts with no
        // figure box fall back to the figure-left box (coordinator spec).
        const free = L.figs.slice(prepared.length);
        const soleOccupant = !hasBullets && !sl.table && prepared.length === 0;
        const dbox = free.length
          ? free[0]
          : (L.figs.length ? null
            : (soleOccupant ? { ...ZONE.content } : LAYOUTS['figure-left'].figs[0]));
        if (dbox) {
          // "shares" = a real figure or table sits in the same figure area;
          // bullets live in their own text box and do not crowd the diagram
          const sharesFigures = prepared.length > 0 || !!sl.table;
          report.diagram = renderDiagram(slide, ctx, sl.diagram, dbox, sharesFigures);
        } else {
          warnings.push({ code: 'DIAGRAM_NO_BOX', detail: `layout "${chosen.name}" figure box already used by ${prepared.length} asset(s) — diagram dropped` });
        }
      }

      // A table with no figure owns the whole content zone; with bullets it
      // splits the zone instead of colliding with the full-width text box.
      const noFigure = prepared.length === 0 && !sl.diagram;
      const tableAlone = !!sl.table && noFigure && !hasBullets;
      let textBox = L.text;

      // figure-top: a flat figure fits well above the box floor, and a text box
      // pinned to y 4.80 would leave a dead band under it. Follow the figure.
      if (chosen.name === 'figure-top' && placements.length) {
        const top = Math.min(placements[0].contentBottom + 0.20, CONTENT_BOTTOM - 0.60);
        textBox = { x: L.text.x, y: top, w: L.text.w, h: CONTENT_BOTTOM - top };
      }
      let tableBox = null;
      if (sl.table) {
        if (tableAlone) tableBox = { ...ZONE.content };
        else if (noFigure && hasBullets) {
          tableBox = { x: 7.20, y: CY, w: 5.63, h: 4.95 };
          textBox = { x: 0.50, y: CY, w: 6.40, h: 4.95 };
        } else tableBox = L.table || { x: 7.20, y: CY, w: 5.63, h: 4.95 };
      }

      // 16 pt on a 12.33 in line reads sparse — the full-width bullet slide
      // gets 20 pt on an 11.0 in measure instead.
      const wideText = chosen.name === 'text-only' && !sl.table && textBox && textBox.w > 10;
      if (wideText) textBox = { x: 0.50, y: CY, w: 11.0, h: 4.95 };
      const bulletOpts = wideText ? { base: 20, lineMult: 1.25, paraAfter: 8 } : undefined;

      let used = 0;
      if (textBox && Array.isArray(sl.bullets) && sl.bullets.length) {
        used = addBullets(slide, ctx, sl.bullets, textBox, warnings, bulletOpts).usedH;
      } else if (!textBox && Array.isArray(sl.bullets) && sl.bullets.length) {
        warnings.push({ code: 'BULLET_OVERFLOW', detail: `layout "${chosen.name}" has no text box — ${sl.bullets.length} bullet(s) dropped` });
      }

      if (sl.table) addTable(slide, ctx, sl.table, tableBox, tableAlone);

      if (sl.callout) {
        const cbox = textBox || { x: 0.50, y: CY, w: 12.33, h: 4.95 };
        addCallout(slide, ctx, sl.callout, cbox, textBox ? used : 4.95 - 0.60, warnings);
      }

      if (sl.bottom_line) addBottomLine(slide, ctx, sl.bottom_line);
      addFooter(slide, ctx);
      if (!sl.notes) warnings.push({ code: 'NOTES_MISSING', detail: `type "${sl.type}" slide has no speaker notes` });
      break;
    }

    // -------------------------------------------------------- conclusion
    case 'conclusion': {
      addBand(slide, ctx, bandLeftFor(ctx, sl), report.number_label);
      addTitle(slide, ctx, sl.title, warnings);
      report.layout_chosen = 'text-only';
      report.layout_auto = !sl.layout || sl.layout === 'auto';

      const items = (sl.items || []).map(String);
      const box = LAYOUTS['text-only'].text;
      let cursor = box.y;
      items.forEach((it) => {
        const lines = Math.max(1, Math.ceil(textWidthIn(it, 18) / (box.w - 0.2)));
        const h = lines * 0.375 + 0.12;
        slide.addText(it, {
          x: box.x, y: cursor, w: box.w, h, margin: 0,
          fontFace: font, fontSize: 18, lineSpacingMultiple: 1.25,
          color: COLOR.ink, valign: 'top', align: 'left',
        });
        cursor += h + 10 / 72;
      });
      if (sl.future) {
        const fy = Math.min(cursor + 0.14, CONTENT_BOTTOM - 0.70);
        slide.addShape(ctx.pres.shapes.RECTANGLE, {
          x: box.x, y: fy, w: box.w, h: 0.66,
          fill: { color: 'E4F1F1' }, line: { color: COLOR.accent, width: 1.25 },
        });
        slide.addText([
          { text: (ctx.ko ? 'Future work — ' : 'Future work — '), options: { bold: true, color: COLOR.accent } },
          { text: String(sl.future), options: { color: COLOR.ink } },
        ], {
          x: box.x + 0.14, y: fy, w: box.w - 0.28, h: 0.66, margin: 0,
          fontFace: font, fontSize: 14, valign: 'middle', align: 'left',
        });
      }
      if (sl.bottom_line) addBottomLine(slide, ctx, sl.bottom_line);
      addFooter(slide, ctx);
      if (!sl.notes) warnings.push({ code: 'NOTES_MISSING', detail: 'conclusion slide has no speaker notes' });
      break;
    }

    // ------------------------------------------------------------ thanks
    case 'thanks': {
      slide.background = { color: COLOR.band };
      const lines = (sl.lines && sl.lines.length ? sl.lines : [ctx.ko ? '감사합니다 · Q&A' : 'Thank you · Q&A']).map(String);
      slide.addText(lines[0], {
        x: 0.90, y: 2.70, w: 11.5, h: 1.10, margin: 0,
        fontFace: font, fontSize: 34, bold: true, color: COLOR.paper, valign: 'middle', align: 'left',
      });
      slide.addShape(ctx.pres.shapes.RECTANGLE, {
        x: 0.92, y: 3.90, w: 2.20, h: 0.06,
        fill: { color: COLOR.accent }, line: { color: COLOR.accent, width: 0 },
      });
      if (lines.length > 1) {
        slide.addText(lines.slice(1).map((t, i) => ({ text: t, options: { breakLine: i < lines.length - 2 } })), {
          x: 0.90, y: 4.20, w: 11.5, h: 1.60, margin: 0,
          fontFace: font, fontSize: 15, color: ON_BAND.strong, valign: 'top', align: 'left',
        });
      }
      break;
    }
  }

  if (sl.notes) slide.addNotes(String(sl.notes));
  return slide;
}

// ---------------------------------------------------------------------------
// 8. Main
// ---------------------------------------------------------------------------

async function build(specPath, outPath, strict) {
  const specDir = path.dirname(path.resolve(specPath));
  let spec;
  try {
    spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  } catch (e) {
    console.error(`[SCHEMA] cannot parse ${specPath}: ${e.message}`);
    return 2;
  }

  const errors = validateSpec(spec);
  if (errors.length) {
    console.error(`[SCHEMA] ${errors.length} error(s) in ${path.basename(specPath)}:`);
    for (const e of errors) console.error(`  ${e.loc}: ${e.msg}`);
    return 2;
  }

  const hits = scanForbidden(spec);
  if (hits.length) {
    console.error(`[FORBIDDEN] ${hits.length} forbidden string(s) found — build refused:`);
    for (const h of hits) console.error(`  ${h.loc}: "${h.needle}"  in  ${h.text}`);
    return 2;
  }

  const meta = spec.meta;
  const sections = spec.sections || [];
  const sectionById = {};
  for (const s of sections) sectionById[s.id] = s;

  // optional asset ledger next to the spec
  const ledger = {};
  const ledgerPath = path.join(specDir, 'asset_ledger.json');
  if (fs.existsSync(ledgerPath)) {
    try {
      const raw = JSON.parse(fs.readFileSync(ledgerPath, 'utf8'));
      const list = Array.isArray(raw) ? raw : (raw.assets || Object.values(raw));
      for (const a of list) if (a && a.id) ledger[a.id] = a;
    } catch (e) {
      console.warn(`[warn] asset_ledger.json present but unreadable: ${e.message}`);
    }
  }

  const pres = new PptxGenJS();
  pres.defineLayout({ name: 'CONF_16x9', width: SLIDE_W, height: SLIDE_H });
  pres.layout = 'CONF_16x9';
  pres.author = meta.presenter || '';
  pres.title = meta.title;
  pres.subject = meta.subtitle || '';

  const outAbs = path.resolve(outPath);
  const outDir = path.dirname(outAbs);
  fs.mkdirSync(outDir, { recursive: true });

  const ctx = {
    pres, meta, sections, sectionById, ledger, specDir,
    ko: (meta.lang || 'ko') !== 'en',
    font: fontFor(meta.lang || 'ko'),
    buildDir: path.join(outDir, '_build'),
  };

  const mainCount = spec.slides.filter((s) => s.type !== 'appendix').length;
  const reports = [];
  let mainN = 0;
  let appendixN = 0;

  for (let i = 0; i < spec.slides.length; i++) {
    const sl = spec.slides[i];
    let numberLabel = '';
    if (sl.type === 'appendix') {
      appendixN += 1;
      numberLabel = `A-${appendixN}`;
    } else {
      mainN += 1;
      numberLabel = `${mainN} / ${mainCount}`;
    }
    const report = {
      index: i + 1,
      type: sl.type,
      number_label: numberLabel,
      layout_chosen: null,
      layout_auto: false,
      diagram: null,
      assets: [],
      warnings: [],
    };
    try {
      await renderSlide(ctx, sl, report);
    } catch (e) {
      console.error(`[SCHEMA] slides[${i}] (${sl.type}): ${e.message}`);
      return 2;
    }
    reports.push(report);
  }

  await pres.writeFile({ fileName: outAbs });

  const allWarnings = [];
  for (const r of reports) {
    for (const w of r.warnings) allWarnings.push({ slide: r.index, code: w.code, detail: w.detail });
  }

  const buildJsonPath = outAbs.replace(/\.pptx$/i, '') + '.build.json';
  const buildDoc = {
    generated_at: new Date().toISOString(),
    spec: path.relative(outDir, path.resolve(specPath)).replace(/\\/g, '/'),
    pptx: path.basename(outAbs),
    slide_count: reports.length,
    main_count: mainCount,
    appendix_count: appendixN,
    strict,
    warning_count: allWarnings.length,
    warnings: allWarnings,
    slides: reports,
  };
  fs.writeFileSync(buildJsonPath, JSON.stringify(buildDoc, null, 2), 'utf8');

  console.log(`built ${path.basename(outAbs)} — ${reports.length} slides (${mainCount} main + ${appendixN} appendix)`);
  console.log(`report ${path.basename(buildJsonPath)} — ${allWarnings.length} warning(s)`);
  for (const w of allWarnings) console.log(`  [${w.code}] slide ${w.slide}: ${w.detail}`);

  if (strict && allWarnings.length) {
    console.error(`--strict: ${allWarnings.length} warning(s) — failing.`);
    return 3;
  }
  return 0;
}

function main() {
  const argv = process.argv.slice(2);
  const strict = argv.includes('--strict');
  const pos = argv.filter((a) => !a.startsWith('--'));
  if (pos.length < 2) {
    console.error('usage: node build_deck.js <spec.json> <out.pptx> [--strict]');
    process.exit(2);
  }
  build(pos[0], pos[1], strict).then(
    (code) => process.exit(code),
    (err) => { console.error(err && err.stack ? err.stack : String(err)); process.exit(1); }
  );
}

// CJS entrypoint guard (no import.meta / file:// comparison — broken on Windows)
if (require.main === module) main();

module.exports = { build, validateSpec, scanForbidden, fitContain, chooseLayout, textWidthIn, LAYOUTS, ZONE, COLOR };
