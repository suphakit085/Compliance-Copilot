# UI quality: accessibility and design review

The web app is checked against WCAG 2.1 AA with an automated scan plus a manual design review
(first impression, usability, hierarchy, consistency). The scan is a script anyone can re-run;
the review is a checklist for a person.

## Re-running the check

```bash
npm i --no-save --prefix .ui-audit puppeteer-core     # once; kept out of web/ (see below)
NODE_PATH=.ui-audit/node_modules node scripts/ui-audit.mjs
```

With the API and web app running, the script logs in with the demo compliance account and:

- runs axe-core (WCAG 2.0/2.1 A and AA, plus best-practice rules) on every page in both themes;
- tabs through the document library and chat, failing any control without a visible focus indicator;
- lists touch targets under 24×24 px on a 390 px phone;
- saves screenshots and `report.json` to `.ui-audit/report/` for the visual review.

It exits 1 on any serious or critical violation or a missing focus indicator. `UI_AUDIT_ASK=1`
also asks one question so the answer view is scanned (one LLM call).
`puppeteer-core` is installed outside `web/` because adding it there brings 9 high-severity
advisories into the web project's dependency scan (all in its download/proxy code, unused here).

## Review of 15 Nov 2026

| | Before | After |
|---|---|---|
| axe violations (20 page × theme scans) | 101 elements in 6 rules, 91 of them serious/critical | 0 |
| Controls without a visible focus indicator | all links and most buttons (1 px outline at 27% opacity) | 0 |
| Touch targets under 24 px (phone) | citation chips 20×21, summary chips 20 px tall | inline text links only (exempt under 2.5.8) |

What was wrong and what changed:

1. **Contrast (1.4.3).** White text on the brand blue was 3.0:1. Filled buttons now use `--primary`
   `#0073cf` (4.8:1). Brand-coloured *text* uses a new `--brand-strong` token (`#4db8ff` dark,
   `#0062b8` light) instead of a hard-coded light blue that was 1.9:1 on the light theme. Faded
   muted text (`/60`), amber warnings, the light-theme green and the unverified-citation red were
   darkened; uncited sources are no longer dimmed with opacity.
2. **Focus (2.4.7).** One unlayered `:focus-visible` rule gives every link, button, select and
   scroll region a 2 px outline in `--brand-strong`; component utilities cannot fade it.
3. **Names and structure (4.1.2, 1.3.1).** The policy picker on Gap Analysis had no accessible name;
   the two `<aside>` landmarks had none; the chat had no `<h1>`; evaluation headings skipped a level.
4. **Keyboard (2.1.1).** Scrollable panels (sources, audit detail, tables, JSON) can be focused and
   scrolled with the keyboard.
5. **Target size (2.5.8).** Citation and unit chips are at least 24×24 px.

Design review findings, beyond WCAG:

- **The evaluation page led with the tuned set's 100%.** It now opens with every question set side
  by side and highlights the first blind runs (held-out 94% / 86%, extended 92% / 95% / 91%) as the
  numbers to quote; the golden-set details follow, labelled as the tuning set.
- **Repeated warnings.** One "synthetic document" notice per policy took half a phone screen; they
  are merged into one notice listing the documents.
- **Follow-up questions** were centred pills that wrapped badly on a phone; they are left-aligned.
- **Deep links** (`/documents?doc=…`) now scroll the selected document into view in the list.

Not covered by the script: screen-reader testing (NVDA/VoiceOver), 200% zoom, and content written
by the model. Those need a person.
