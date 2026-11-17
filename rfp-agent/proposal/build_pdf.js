// Proposal PDF build: HTML (with @@FACE:<key>@@ tokens) -> print PDF via Chromium.
//
//   node proposal/build_pdf.js proposal.html out.pdf --faces faces.json [--title "Short title"]
//
// faces.json is private (headshots as base64, names, roles) and never committed:
//   { "<key>": { "name": "...", "role": "...", "photo": "data:image/jpeg;base64,..." } }
//
// The page design (cover, bands, cards, type) comes from the brand proposal template the
// agent loads from the thriving-culture-proposal-pdf skill; this script only resolves face
// tokens, enforces the print rules that are mechanical, and prints:
//   - display_header_footer on with non-empty templates (coloured margins)
//   - no table split across a page (break-inside: avoid on tables, rows and .person)
//   - every @@FACE@@ token resolved, or the build fails
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i > -1 ? process.argv[i + 1] : def;
}

function personHtml(key, f) {
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  return `<div class="person" data-face="${esc(key)}">` +
    `<span class="person__ring"><img class="person__photo" alt="${esc(f.name)}" src="${f.photo}"></span>` +
    `<span class="person__text"><span class="person__name">${esc(f.name)}</span>` +
    `<span class="person__role">${esc(f.role)}</span></span></div>`;
}

const PRINT_CSS = `
<style id="build-print-rules">
  table, tr, .person, .card, figure { break-inside: avoid; page-break-inside: avoid; }
  thead { display: table-header-group; }
  .person { display: flex; align-items: center; gap: 10pt; }
  .person__ring { width: 54pt; height: 54pt; border-radius: 50%; padding: 2pt;
    background: linear-gradient(135deg, var(--tc-green, #3a9a4a), var(--tc-teal, #1f8f8f), var(--tc-blue, #2a5fa8));
    display: inline-flex; align-items: center; justify-content: center; flex: none; }
  .person__photo { width: 50pt; height: 50pt; border-radius: 50%; object-fit: cover; background: #fff; }
  .person__name { display: block; font-family: Lora, Georgia, serif; font-size: 12pt; }
  .person__role { display: block; text-transform: uppercase; letter-spacing: .06em; font-size: 8pt;
    color: var(--tc-teal, #1f8f8f); }
</style>`;

(async () => {
  const [src, out] = process.argv.slice(2, 4);
  if (!src || !out) { console.error('usage: build_pdf.js in.html out.pdf --faces faces.json'); process.exit(2); }
  let html = fs.readFileSync(src, 'utf8');
  const facesPath = arg('--faces');
  const faces = facesPath ? JSON.parse(fs.readFileSync(facesPath, 'utf8')) : {};
  const missing = [];
  html = html.replace(/@@FACE:([a-z0-9_-]+)@@/gi, (m, key) => {
    const f = faces[key.toLowerCase()];
    if (!f || !f.photo) { missing.push(key); return m; }
    return personHtml(key, f);
  });
  if (missing.length) { console.error('unresolved face tokens: ' + [...new Set(missing)].join(', ')); process.exit(4); }
  for (const bad of ['—', '–', '“', '”', '‘', '’']) {
    if (html.includes(bad)) { console.error(`forbidden character U+${bad.charCodeAt(0).toString(16)} in source`); process.exit(5); }
  }
  html = html.replace('</head>', PRINT_CSS + '</head>');
  const title = arg('--title', path.basename(src, '.html'));
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: 'networkidle' });
  await page.pdf({
    path: out, format: 'Letter', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: `<div style="width:100%;height:6px;background:linear-gradient(90deg,#3a9a4a,#1f8f8f,#2a5fa8);-webkit-print-color-adjust:exact"></div>`,
    footerTemplate: `<div style="width:100%;font-size:7pt;font-family:Carlito,Calibri,sans-serif;color:#555;padding:0 36pt;display:flex;justify-content:space-between"><span>${title.replace(/</g, '&lt;')}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
    margin: { top: '0.75in', bottom: '0.75in', left: '0.75in', right: '0.75in' },
  });
  await browser.close();
  console.log(out);
})().catch((e) => { console.error(e); process.exit(1); });
