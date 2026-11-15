// UI quality check: WCAG 2.1 AA scan (axe-core) of every page in both themes, focus-indicator check,
// touch-target sizes on a phone, and screenshots for a visual review.
//
//   npm i --no-save --prefix .ui-audit puppeteer-core     (once; kept out of web/ on purpose:
//                                                            it would add dev-only advisories there)
//   NODE_PATH=.ui-audit/node_modules node scripts/ui-audit.mjs [outDir]
//
// Needs the API and web app running (http://localhost:3000) and a local Chrome. Uses the demo
// compliance account from config/users.yaml (override with UI_AUDIT_USER / UI_AUDIT_PASSWORD).
// Exits 1 if axe reports any serious or critical violation, or a focused control has no visible
// focus indicator. Does not ask a question (no LLM quota); set UI_AUDIT_ASK=1 to include an answer.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(path.resolve(process.env.NODE_PATH || ".ui-audit/node_modules", "x.js"));
const puppeteer = require("puppeteer-core");
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const AXE = fs.readFileSync(path.join(ROOT, "web/node_modules/axe-core/axe.min.js"), "utf8");
const BASE = process.env.UI_AUDIT_BASE || "http://localhost:3000";
const OUT = process.argv[2] || path.join(ROOT, ".ui-audit/report");
const CHROME = process.env.CHROME_PATH || (process.platform === "win32"
  ? "C:/Program Files/Google/Chrome/Application/chrome.exe"
  : process.platform === "darwin" ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : "/usr/bin/google-chrome");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--force-color-profile=srgb"] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
const report = { violations: {}, focus: [], touch: [] };

async function scan(name) {
  await page.screenshot({ path: `${OUT}/${name}.png` });
  await page.evaluate(AXE);
  report.violations[name] = await page.evaluate(async () => {
    const r = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
    return r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target.join(" "), summary: n.failureSummary })) }));
  });
}

await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
for (const theme of ["dark", "light"]) {
  await page.evaluate((t) => localStorage.setItem("theme", t), theme);
  await page.reload({ waitUntil: "networkidle0" });
  await sleep(800);
  await scan(`login-${theme}`);
}
await page.type('input[autocomplete="username"]', process.env.UI_AUDIT_USER || "nida");
await page.type('input[autocomplete="current-password"]', process.env.UI_AUDIT_PASSWORD || "demo-compliance");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.keyboard.press("Enter")]);
await sleep(800);
if (await page.$("[role=dialog] input[type=checkbox]")) await scan("terms");

const pages = [["chat", "/"], ["documents", "/documents"], ["summary", "/documents?doc=pdpa-2562&view=summary"],
  ["gap", "/gap"], ["audit", "/audit"], ["reports", "/reports"], ["eval", "/eval"], ["help", "/help"]];
let conversation = null;
if (process.env.UI_AUDIT_ASK && !(await page.$("[role=dialog]"))) {
  await page.type("textarea", "ลูกค้ามอบกระเช้ามูลค่า 4,000 บาท ระหว่างพิจารณาสินเชื่อ รับได้ไหม");
  await page.keyboard.press("Enter");
  await page.waitForSelector("button[title='ดูข้อความต้นฉบับที่อ้างอิง']", { timeout: 180000 }).catch(() => {});
  await sleep(1500);
  conversation = page.url().replace(BASE, "");
  pages.splice(1, 0, ["answer", conversation]);
}
for (const theme of ["dark", "light"]) {
  await page.evaluate((t) => localStorage.setItem("theme", t), theme);
  for (const [name, p] of pages) {
    await page.goto(`${BASE}${p}`, { waitUntil: "networkidle0" });
    await sleep(1200);
    await scan(`${name}-${theme}`);
  }
}

// Focus: every control reached by Tab must show an indicator (outline or ring) once transitions settle.
for (const p of ["/documents", conversation || "/"]) {
  await page.goto(`${BASE}${p}`, { waitUntil: "networkidle0" });
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press("Tab");
    await sleep(250);
    report.focus.push(await page.evaluate(() => {
      const el = document.activeElement, s = getComputedStyle(el);
      const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2;
      const ring = s.boxShadow !== "none";
      const glow = !!el.closest(".glow-shell"); // the question box shows focus on its container
      return { page: location.pathname, tag: el.tagName, label: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40), visible: outline || ring || glow || el === document.body };
    }));
  }
}

// Touch targets on a phone (WCAG 2.5.8: at least 24x24 CSS px)
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
for (const p of [conversation || "/", "/documents?doc=pdpa-2562&view=summary"]) {
  await page.goto(`${BASE}${p}`, { waitUntil: "networkidle0" });
  await sleep(1200);
  await page.screenshot({ path: `${OUT}/phone-${p === "/" ? "chat" : p.includes("summary") ? "summary" : "answer"}.png` });
  report.touch.push(...await page.evaluate(() => [...document.querySelectorAll("button, a, select, [role=button]")]
    .map((el) => { const r = el.getBoundingClientRect(); return { page: location.pathname, label: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40), w: Math.round(r.width), h: Math.round(r.height) }; })
    .filter((x) => x.w > 0 && x.h > 0 && (x.w < 24 || x.h < 24))));
}

if (conversation?.startsWith("/c/")) {
  await page.evaluate((id) => fetch(`/api/backend/conversations/${id}/delete`, { method: "POST" }), conversation.slice(3));
}
await browser.close();

fs.writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 1));
const serious = Object.entries(report.violations).flatMap(([p, vs]) => vs.filter((v) => ["serious", "critical"].includes(v.impact)).map((v) => `${p}: ${v.id} (${v.nodes.length}) ${v.help}`));
const minor = Object.entries(report.violations).flatMap(([p, vs]) => vs.filter((v) => !["serious", "critical"].includes(v.impact)).map((v) => `${p}: ${v.id} (${v.nodes.length})`));
const noFocus = report.focus.filter((f) => !f.visible);
console.log(`pages scanned: ${Object.keys(report.violations).length}`);
console.log(`serious/critical: ${serious.length}`); serious.forEach((s) => console.log("  ✗", s));
console.log(`moderate/minor: ${minor.length}`); minor.forEach((s) => console.log("  ·", s));
console.log(`controls without a visible focus indicator: ${noFocus.length}`); noFocus.forEach((f) => console.log("  ✗", f.page, f.tag, f.label));
console.log(`touch targets under 24px on a phone: ${report.touch.length}`); report.touch.forEach((t) => console.log("  ·", t.page, t.label, `${t.w}x${t.h}`));
console.log(`screenshots and report.json: ${OUT}`);
process.exit(serious.length || noFocus.length ? 1 : 0);
