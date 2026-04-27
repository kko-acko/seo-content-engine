/**
 * Acko Content Studio — Product Note Generator
 * Produces: Acko_Content_Studio_Product_Note.docx
 */

const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  ExternalHyperlink,
} = require("docx");

// ─── Colour palette ──────────────────────────────────────────────────────────
const C = {
  purple:    "522ED3",
  blue:      "2563EB",
  navy:      "0F172A",
  slate:     "334155",
  muted:     "64748B",
  white:     "FFFFFF",
  light:     "F1F5F9",
  border:    "CBD5E1",
  green:     "059669",
  amber:     "D97706",
  red:       "DC2626",
  lightPurple: "EDE9FE",
  lightBlue:   "DBEAFE",
  lightGreen:  "D1FAE5",
  lightAmber:  "FEF3C7",
};

// ─── Page geometry (A4, 1" margins) ──────────────────────────────────────────
const PAGE_W   = 11906;  // A4 width in DXA
const MARGIN   = 1440;   // 1 inch
const CONTENT_W = PAGE_W - 2 * MARGIN; // 9026 DXA

// ─── Helpers ─────────────────────────────────────────────────────────────────
const sp = (before = 0, after = 0, line) => {
  const s = { before: before * 20, after: after * 20 };
  if (line) s.line = line;
  return s;
};

const border1 = (color = C.border) => ({
  style: BorderStyle.SINGLE, size: 1, color,
});

const cellBorders = (color = C.border) => {
  const b = border1(color);
  return { top: b, bottom: b, left: b, right: b };
};

const noBorders = () => {
  const nb = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  return { top: nb, bottom: nb, left: nb, right: nb };
};

function heading1(text, color = C.navy) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: sp(16, 6),
    children: [
      new TextRun({ text, bold: true, size: 36, color, font: "Arial" }),
    ],
  });
}

function heading2(text, color = C.purple) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: sp(14, 4),
    children: [
      new TextRun({ text, bold: true, size: 28, color, font: "Arial" }),
    ],
  });
}

function heading3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: sp(10, 3),
    children: [
      new TextRun({ text, bold: true, size: 24, color: C.slate, font: "Arial" }),
    ],
  });
}

function body(text, options = {}) {
  return new Paragraph({
    spacing: sp(0, 6),
    children: [new TextRun({ text, size: 22, color: C.slate, font: "Arial", ...options })],
  });
}

function lead(boldPart, restPart, color = C.slate) {
  return new Paragraph({
    spacing: sp(0, 6),
    children: [
      new TextRun({ text: boldPart, bold: true, size: 22, color: C.navy, font: "Arial" }),
      new TextRun({ text: restPart, size: 22, color, font: "Arial" }),
    ],
  });
}

function bullet(text, numbering) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: sp(0, 4),
    children: [new TextRun({ text, size: 22, color: C.slate, font: "Arial" })],
  });
}

function bullet2(boldPart, rest) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: sp(0, 4),
    children: [
      new TextRun({ text: boldPart, bold: true, size: 22, color: C.navy, font: "Arial" }),
      new TextRun({ text: rest, size: 22, color: C.slate, font: "Arial" }),
    ],
  });
}

function gap(pts = 12) {
  return new Paragraph({ spacing: sp(0, pts), children: [] });
}

function rule(color = C.border) {
  return new Paragraph({
    spacing: sp(4, 4),
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color } },
    children: [],
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// Shade cell helper
function shadeCell(fill, children, options = {}) {
  return new TableCell({
    shading: { fill, type: ShadingType.CLEAR },
    borders: noBorders(),
    margins: { top: 100, bottom: 100, left: 160, right: 160 },
    ...options,
    children,
  });
}

// Bordered cell helper
function bCell(fill, children, width, opts = {}) {
  return new TableCell({
    shading: { fill, type: ShadingType.CLEAR },
    borders: cellBorders(C.border),
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    width: { size: width, type: WidthType.DXA },
    ...opts,
    children,
  });
}

// Caption / label
function label(text, color = C.purple) {
  return new Paragraph({
    spacing: sp(0, 3),
    children: [new TextRun({ text: text.toUpperCase(), size: 16, color, bold: true, font: "Arial" })],
  });
}

// ─── KPI card row ─────────────────────────────────────────────────────────────
function kpiTable(items) {
  // items: [{value, label, color}]
  const colW = Math.floor(CONTENT_W / items.length);
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: items.map(() => colW),
    rows: [
      new TableRow({
        children: items.map(({ value, label: lbl, color }) =>
          new TableCell({
            shading: { fill: C.light, type: ShadingType.CLEAR },
            borders: cellBorders(C.border),
            margins: { top: 120, bottom: 120, left: 160, right: 160 },
            width: { size: colW, type: WidthType.DXA },
            verticalAlign: VerticalAlign.CENTER,
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                spacing: sp(0, 4),
                children: [new TextRun({ text: value, bold: true, size: 52, color: color || C.purple, font: "Arial" })],
              }),
              new Paragraph({
                alignment: AlignmentType.CENTER,
                spacing: sp(0, 0),
                children: [new TextRun({ text: lbl, size: 18, color: C.muted, font: "Arial" })],
              }),
            ],
          })
        ),
      }),
    ],
  });
}

// ─── Capability table ────────────────────────────────────────────────────────
function capTable(rows) {
  const col1 = 3200, col2 = 5826;
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [col1, col2],
    rows: [
      new TableRow({
        children: [
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Capability", bold: true, size: 20, color: C.white, font: "Arial" })] })], col1),
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "What it does", bold: true, size: 20, color: C.white, font: "Arial" })] })], col2),
        ],
      }),
      ...rows.map(([cap, what], i) =>
        new TableRow({
          children: [
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: cap, bold: true, size: 20, color: C.navy, font: "Arial" })] })], col1),
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: what, size: 20, color: C.slate, font: "Arial" })] })], col2),
          ],
        })
      ),
    ],
  });
}

// ─── Callout box ─────────────────────────────────────────────────────────────
function callout(labelText, bodyText, fill = C.lightPurple, borderColor = C.purple) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            shading: { fill, type: ShadingType.CLEAR },
            borders: {
              top: border1(borderColor), bottom: border1(borderColor),
              left: { style: BorderStyle.SINGLE, size: 18, color: borderColor },
              right: border1(borderColor),
            },
            margins: { top: 100, bottom: 100, left: 200, right: 160 },
            width: { size: CONTENT_W, type: WidthType.DXA },
            children: [
              new Paragraph({
                spacing: sp(0, 4),
                children: [new TextRun({ text: labelText.toUpperCase(), bold: true, size: 16, color: borderColor, font: "Arial" })],
              }),
              new Paragraph({
                spacing: sp(0, 0),
                children: [new TextRun({ text: bodyText, size: 22, color: C.slate, font: "Arial" })],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}

// ─── Pipeline arrow row ───────────────────────────────────────────────────────
function pipelineRow(steps) {
  // steps: [{emoji, label, color}]
  const n = steps.length;
  const arrowW = 320;
  const stepW = Math.floor((CONTENT_W - arrowW * (n - 1)) / n);
  const colWidths = [];
  for (let i = 0; i < n; i++) {
    colWidths.push(stepW);
    if (i < n - 1) colWidths.push(arrowW);
  }
  const cells = [];
  for (let i = 0; i < n; i++) {
    cells.push(
      new TableCell({
        shading: { fill: steps[i].color || C.light, type: ShadingType.CLEAR },
        borders: cellBorders(C.border),
        margins: { top: 80, bottom: 80, left: 80, right: 80 },
        width: { size: stepW, type: WidthType.DXA },
        verticalAlign: VerticalAlign.CENTER,
        children: [
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: sp(0, 3),
            children: [new TextRun({ text: steps[i].emoji, size: 36, font: "Arial" })],
          }),
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: sp(0, 0),
            children: [new TextRun({ text: steps[i].label, bold: true, size: 18, color: C.navy, font: "Arial" })],
          }),
        ],
      })
    );
    if (i < n - 1) {
      cells.push(
        new TableCell({
          shading: { fill: C.white, type: ShadingType.CLEAR },
          borders: noBorders(),
          margins: { top: 0, bottom: 0, left: 0, right: 0 },
          width: { size: arrowW, type: WidthType.DXA },
          verticalAlign: VerticalAlign.CENTER,
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "→", size: 28, color: C.muted, font: "Arial" })],
          })],
        })
      );
    }
  }
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [new TableRow({ children: cells })],
  });
}

// ─── Layer architecture table ─────────────────────────────────────────────────
function layerTable(layers) {
  // layers: [{num, title, items, color, built}]
  const col1 = 1400, col2 = 4000, col3 = 3626;
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [col1, col2, col3],
    rows: [
      new TableRow({
        children: [
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Layer", bold: true, size: 18, color: C.white, font: "Arial" })] })], col1),
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "What it does", bold: true, size: 18, color: C.white, font: "Arial" })] })], col2),
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Components", bold: true, size: 18, color: C.white, font: "Arial" })] })], col3),
        ],
      }),
      ...layers.map((l, i) =>
        new TableRow({
          children: [
            bCell(l.color, [
              new Paragraph({ children: [new TextRun({ text: `Layer ${l.num}`, bold: true, size: 16, color: l.textColor || C.navy, font: "Arial" })] }),
              new Paragraph({ children: [new TextRun({ text: l.title, bold: true, size: 20, color: l.textColor || C.navy, font: "Arial" })] }),
              ...(l.built ? [new Paragraph({ children: [new TextRun({ text: l.built, size: 14, color: l.builtColor || C.green, bold: true, font: "Arial" })] })] : []),
            ], col1),
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: l.desc, size: 20, color: C.slate, font: "Arial" })] })], col2),
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: l.items, size: 18, color: C.slate, font: "Arial" })] })], col3),
          ],
        })
      ),
    ],
  });
}

// ─── Scoring table ────────────────────────────────────────────────────────────
function scoringTable(rows, cols) {
  const colW = Math.floor(CONTENT_W / cols.length);
  const colWidths = cols.map(() => colW);
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({
        children: cols.map(c => bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: c, bold: true, size: 18, color: C.white, font: "Arial" })] })], colW)),
      }),
      ...rows.map((r, i) =>
        new TableRow({
          children: r.map((cell, j) =>
            bCell(i % 2 === 0 ? C.light : C.white,
              [new Paragraph({ children: [new TextRun({ text: cell, size: 20, color: j === 0 ? C.navy : C.slate, bold: j === 0, font: "Arial" })] })],
              colW
            )
          ),
        })
      ),
    ],
  });
}

// ─── Roadmap table ────────────────────────────────────────────────────────────
function roadmapTable(items) {
  const col1 = 1200, col2 = 2000, col3 = 4626, col4 = 1200;
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [col1, col2, col3, col4],
    rows: [
      new TableRow({
        children: [
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Day", bold: true, size: 18, color: C.white, font: "Arial" })] })], col1),
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Workstream", bold: true, size: 18, color: C.white, font: "Arial" })] })], col2),
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Deliverable", bold: true, size: 18, color: C.white, font: "Arial" })] })], col3),
          bCell(C.navy, [new Paragraph({ children: [new TextRun({ text: "Status", bold: true, size: 18, color: C.white, font: "Arial" })] })], col4),
        ],
      }),
      ...items.map(([day, ws, del_, status], i) => {
        const statusColor = status === "Done" ? C.green : status === "In Progress" ? C.amber : C.muted;
        return new TableRow({
          children: [
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: day, bold: true, size: 18, color: C.purple, font: "Arial" })] })], col1),
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: ws, size: 18, color: C.navy, bold: true, font: "Arial" })] })], col2),
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: del_, size: 18, color: C.slate, font: "Arial" })] })], col3),
            bCell(i % 2 === 0 ? C.light : C.white, [new Paragraph({ children: [new TextRun({ text: status, bold: true, size: 18, color: statusColor, font: "Arial" })] })], col4),
          ],
        });
      }),
    ],
  });
}

// ─── Document assembly ───────────────────────────────────────────────────────

const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 480, hanging: 240 } } },
        }],
      },
    ],
  },
  styles: {
    default: {
      document: { run: { font: "Arial", size: 22 } },
    },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: C.navy },
        paragraph: { spacing: { before: 320, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: C.purple },
        paragraph: { spacing: { before: 280, after: 80 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: C.slate },
        paragraph: { spacing: { before: 200, after: 60 }, outlineLevel: 2 } },
    ],
  },

  sections: [
    // ═══════════════════════════════════════════════════════════════
    // SECTION 0 — COVER PAGE
    // ═══════════════════════════════════════════════════════════════
    {
      properties: {
        page: {
          size: { width: PAGE_W, height: 16838 },
          margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
        },
      },
      children: [
        gap(60),

        // Acko logo text
        new Paragraph({
          spacing: sp(0, 0),
          children: [
            new TextRun({ text: "ACKO", bold: true, size: 40, color: C.purple, font: "Arial" }),
            new TextRun({ text: ".", bold: true, size: 40, color: C.blue, font: "Arial" }),
          ],
        }),

        gap(48),

        // Category tag
        new Paragraph({
          spacing: sp(0, 6),
          children: [new TextRun({ text: "INTERNAL PRODUCT NOTE  ·  APRIL 2026  ·  CONFIDENTIAL", size: 16, color: C.muted, font: "Arial", bold: true })],
        }),

        gap(8),

        // Main title
        new Paragraph({
          spacing: sp(0, 8),
          children: [new TextRun({ text: "Acko Content Studio", bold: true, size: 72, color: C.navy, font: "Arial" })],
        }),

        new Paragraph({
          spacing: sp(0, 24),
          children: [new TextRun({ text: "AI-Powered Publishing at Scale", bold: false, size: 40, color: C.purple, font: "Arial" })],
        }),

        // Divider
        new Paragraph({
          spacing: sp(0, 24),
          border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: C.purple } },
          children: [],
        }),

        gap(24),

        // Subtitle blurb
        new Paragraph({
          spacing: sp(0, 8),
          children: [new TextRun({ text: "A full-stack AI content engine that transforms raw research, legacy pages, and briefs into publishing-ready blog articles for Acko\u2019s Enterprise, Retail, and Long-tail content lines.", size: 26, color: C.slate, font: "Arial" })],
        }),

        gap(40),

        // KPI strip
        kpiTable([
          { value: "128",  label: "Pages crawled",       color: C.purple },
          { value: "154",  label: "Clusters created",    color: C.blue },
          { value: "56",   label: "Articles generated",  color: C.green },
          { value: "3",    label: "Business lines",      color: C.amber },
        ]),

        gap(40),

        // Pipeline row
        pipelineRow([
          { emoji: "📝", label: "Brief / Crawl", color: "EDE9FE" },
          { emoji: "🧩", label: "Cluster",       color: "DBEAFE" },
          { emoji: "✍️", label: "Generate",      color: "D1FAE5" },
          { emoji: "📊", label: "Evaluate",      color: "FEF3C7" },
          { emoji: "📚", label: "Library",       color: "F1F5F9" },
        ]),

        gap(64),

        // Footer note
        new Paragraph({
          spacing: sp(0, 0),
          children: [new TextRun({ text: "Prepared by: Acko Technology & Services · All rights reserved · Not for external distribution", size: 16, color: C.muted, font: "Arial" })],
        }),

        pageBreak(),
      ],
    },

    // ═══════════════════════════════════════════════════════════════
    // SECTION 1 — BODY (all remaining pages)
    // ═══════════════════════════════════════════════════════════════
    {
      properties: {
        page: {
          size: { width: PAGE_W, height: 16838 },
          margin: { top: MARGIN, right: MARGIN, bottom: MARGIN + 360, left: MARGIN },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.border } },
              spacing: sp(0, 8),
              children: [
                new TextRun({ text: "Acko Content Studio  ·  Product Note  ·  April 2026", size: 16, color: C.muted, font: "Arial" }),
              ],
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.border } },
              spacing: sp(8, 0),
              alignment: AlignmentType.RIGHT,
              children: [
                new TextRun({ text: "Page ", size: 16, color: C.muted, font: "Arial" }),
                new TextRun({ children: [PageNumber.CURRENT], size: 16, color: C.muted, font: "Arial" }),
                new TextRun({ text: " of ", size: 16, color: C.muted, font: "Arial" }),
                new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: C.muted, font: "Arial" }),
              ],
            }),
          ],
        }),
      },
      children: [

        // ── 1. EXECUTIVE SUMMARY ─────────────────────────────────────
        heading1("1. Executive Summary"),
        rule(C.purple),
        gap(6),

        callout(
          "What is Acko Content Studio?",
          "An in-house AI content engine that converts legacy pages, topic briefs, PDFs, and reference URLs into fully designed, SEO-optimised blog articles. It covers all three of Acko\u2019s content lines \u2014 Enterprise (B2B group insurance), Retail (individual/family), and Long-tail (specific niche queries) \u2014 and produces output that is ready for editorial review and publishing."
        ),

        gap(10),
        body("The studio is built as a 5-step pipeline running entirely in-house:"),
        gap(6),

        pipelineRow([
          { emoji: "📝", label: "Brief / Crawl",  color: "EDE9FE" },
          { emoji: "🧩", label: "Cluster",        color: "DBEAFE" },
          { emoji: "✍️", label: "Generate",       color: "D1FAE5" },
          { emoji: "📊", label: "Evaluate",       color: "FEF3C7" },
          { emoji: "📚", label: "Publish-ready",  color: "F1F5F9" },
        ]),

        gap(12),
        bullet2("Two entry points: ", "Start from a 30-second brief (Enterprise + targeted content) or from 3,500+ crawled legacy pages (Retail SEO overhaul)."),
        bullet2("Three business lines: ", "Enterprise (🏢 B2B), Retail (👤 B2C), Long-tail (🔍 niche) \u2014 each with its own tone, template, and quality rules."),
        bullet2("Publishing-quality output: ", "Every article goes through a 3-pass quality pipeline (extraction \u2192 editor \u2192 Northstar evaluation) before appearing in the Library."),
        bullet2("Fully editable: ", "Generated articles can be edited section-by-section, reordered, and re-rendered with one click \u2014 no raw HTML needed."),

        gap(16),

        // ── 2. THE PROBLEM ────────────────────────────────────────────
        heading1("2. The Problem"),
        rule(C.purple),
        gap(6),

        body("Acko\u2019s content operation faces four compounding challenges:"),
        gap(8),

        scoringTable([
          ["Volume vs. quality",   "3,500+ legacy pages exist on acko.com \u2014 many are thin, duplicate, or outdated. Manual rewrites at this scale are impractical."],
          ["Enterprise gap",       "No evergreen content exists for Corporate Health, Fleet Insurance, Group Policies, or Workmen\u2019s Comp \u2014 the fastest-growing revenue lines."],
          ["Production speed",     "A single well-researched article takes 3-5 hours to brief, write, and SEO-optimise. The backlog grows faster than the team can clear it."],
          ["Consistency",          "Tone, structure, and quality vary widely across writers and editors. No standard template for B2B vs. B2C vs. long-tail articles."],
        ], ["Challenge", "Impact"]),

        gap(16),

        // ── 3. THE SOLUTION ───────────────────────────────────────────
        heading1("3. The Solution"),
        rule(C.purple),
        gap(6),
        body("Acko Content Studio introduces two parallel content creation paths:"),
        gap(10),

        heading3("Path A \u2014 Crawl-Based (Retail SEO overhaul)"),
        body("The crawler extracts content from acko.com/car-insurance/ and related pages, groups them by consumer question (cluster), and generates one authoritative new article per cluster. Legacy pages that map to the same question get consolidated into a single, stronger piece. The old pages can then be 301-redirected."),
        gap(6),
        heading3("Path B \u2014 Brief-Based (Enterprise + targeted content)"),
        body("A content editor fills in a 3-screen brief: business line, topic/question, audience, key angles, and research material (typed text, uploaded PDF/DOCX, or reference URLs). The brief is processed as a cluster and the same generation pipeline runs. No crawling required \u2014 ideal for Enterprise topics where no legacy pages exist."),
        gap(6),

        callout("Key insight", "This is not a page rewriter. Every article is written from scratch using source material as research only. The AI is instructed to generate new structure, narrative, and examples \u2014 not to copy or paraphrase existing content.", C.lightBlue, C.blue),

        gap(16),

        // ── 4. CURRENT CAPABILITIES ───────────────────────────────────
        heading1("4. Current Capabilities"),
        rule(C.purple),
        gap(6),

        capTable([
          ["Crawling",          "Headless Playwright browser extracts title, H1, meta, headings, body text, and internal links from up to 3,500 pages. Checkpoint/resume, 4 retries, robots.txt compliant."],
          ["Clustering",        "AI groups pages by the real consumer question they answer. One cluster = one article topic. Supports Phase 2 deep enrichment (content gaps, journey stage, quality scores per page)."],
          ["Brief intake",      "3-screen wizard for any business line. Accepts typed text, PDF upload, DOCX upload, and reference URLs. All sources are assembled into a structured brief block."],
          ["Generation",        "3-pass pipeline: (1) smart source extraction, (2) article writing, (3) self-editing. Output is a structured JSON article with 12+ section types. Renders to 4 Jinja2 HTML templates."],
          ["Quality evaluation","Northstar 6-dimension framework scores every article (0\u20135). Automatically regenerates if score < 3.5. Dimensions: question clarity, content depth, structure, brand voice, replaceability, visual execution."],
          ["Templates",         "4 Jinja2 HTML templates: informational (Retail default), transactional (buying guide), longtail (niche/specific), enterprise (B2B corporate). All are fully responsive with JSON-LD structured data."],
          ["Library + editing", "Card-based article gallery filtered by business line, status, and score. Inline editor: edit metadata, reorder/delete/add sections, save and re-render HTML. No raw HTML required."],
          ["AI model options",  "Supports gpt-4.1 (default), gpt-4.1-mini, gpt-5, o4-mini, o3, and legacy gpt-4o. Automatic API parameter switching between legacy and new model endpoints."],
        ]),

        gap(16),
        pageBreak(),

        // ── 5. CONTENT QUALITY FRAMEWORK ─────────────────────────────
        heading1("5. Content Quality Framework"),
        rule(C.purple),
        gap(6),
        body("Every generated article is scored across six dimensions using the Northstar evaluation framework. Scores are 1\u20135 per dimension with weighted aggregation."),
        gap(10),

        scoringTable([
          ["Consumer question clarity",  "20%", "Does the H1 directly state the question? Do the first two paragraphs fully answer it?"],
          ["Content depth & usefulness", "20%", "Specific numbers, examples, adjacent questions covered. No generic statements."],
          ["Structure & scannability",   "15%", "H2s are questions, bold text carries 80% of value, bullet lists and tables present."],
          ["Brand voice & publishability","15%", "Knowledgeable-friend tone, active voice, no banned phrases, no filler."],
          ["Replaceability",             "15%", "Covers everything the source pages covered. Internal links preserved. 301-redirect ready."],
          ["Design & visual execution",  "15%", "Section variety (tables, callouts, expert tips, FAQ accordions), not just text blocks."],
        ], ["Dimension", "Weight", "What is checked"]),

        gap(10),

        scoringTable([
          ["Approve",      "\u2265 4.0 overall AND all dimensions \u2265 3.0", "Ready for editorial review and publishing"],
          ["Conditional",  "\u2265 3.5 overall AND all dimensions \u2265 2.0", "Minor fixes needed \u2014 goes back to editor"],
          ["Reject",       "< 3.5 overall OR any dimension < 2.0",          "Auto-regenerated (max 2 attempts)"],
        ], ["Verdict", "Threshold", "Action"]),

        gap(16),

        // ── 6. THIS WEEK\u2019S ROADMAP ──────────────────────────────────────
        heading1("6. This Week\u2019s Build Roadmap"),
        rule(C.purple),
        gap(6),
        body("Three parallel workstreams are in progress this week to move from a functional prototype to a polished internal product:"),
        gap(10),

        roadmapTable([
          ["Day 1", "Product Note",    "This document. Full product brief for Product, Marketing, and CXOs.",           "Done"],
          ["Day 1", "Design System",   "Shared CSS tokens applied across all pages (colour, type, spacing).",            "In Progress"],
          ["Day 2", "UI \u2014 Dashboard",  "Home page with live KPI strip, activity feed, and pipeline health card.",       "Planned"],
          ["Day 2", "UI \u2014 Library",    "Masonry article grid, fullscreen preview mode, business line filters.",         "Planned"],
          ["Day 3", "UI \u2014 Brief",      "3-step wizard with live preview panel and AI-assisted key angle suggestions.", "Planned"],
          ["Day 3", "UI \u2014 Generate",   "Split view, real-time quality stepper (extraction \u2192 edit \u2192 eval).",   "Planned"],
          ["Day 4", "Quality \u2014 Pipeline","Mandatory 3-pass pipeline (no skip toggles), publishing thresholds enforced.", "Planned"],
          ["Day 4", "Quality \u2014 Eval",  "Expanded evaluation prompt. Structured per-dimension feedback on regen.",      "Planned"],
          ["Day 5", "Quality \u2014 Fidelity","Brief fidelity check: verifies article covers all key angles from the brief.","Planned"],
          ["Day 5", "QA + Clusters",   "End-to-end test all business lines. Kanban cluster status board.",                "Planned"],
        ]),

        gap(16),
        pageBreak(),

        // ── 7. CONTENT STUDIO VISION ──────────────────────────────────
        heading1("7. Content Studio Vision"),
        rule(C.purple),
        gap(6),
        body("The studio is designed as a 6-layer stack. Layers 1\u20134 are built and operational. Layers 5\u20136 are the next horizon."),
        gap(10),

        layerTable([
          {
            num: 1, title: "Ingestion",
            color: "EDE9FE", textColor: C.purple,
            built: "BUILT", builtColor: C.green,
            desc: "Accept content from multiple sources: Playwright crawler, typed brief, PDF/DOCX upload, reference URLs.",
            items: "Playwright crawler · Brief intake (3-screen wizard) · PDF / DOCX extraction · Reference URL fetch",
          },
          {
            num: 2, title: "Intelligence",
            color: "DBEAFE", textColor: C.blue,
            built: "BUILT", builtColor: C.green,
            desc: "Group inputs by consumer question. Deep analysis: content gaps, journey stage, priority scoring, deduplication.",
            items: "AI clustering · Phase 2 enrichment · Cross-cluster gap analysis · Content priority scoring",
          },
          {
            num: 3, title: "Generation",
            color: "D1FAE5", textColor: "15803D",
            built: "BUILT", builtColor: C.green,
            desc: "3-pass AI writing pipeline. Business-line tone adaptation. 4 HTML templates.",
            items: "Smart extraction · Article writing · Self-editing · 4 Jinja2 templates · 8 AI model options",
          },
          {
            num: 4, title: "Review",
            color: "FEF3C7", textColor: C.amber,
            built: "BUILT", builtColor: C.green,
            desc: "Northstar quality scoring. Inline section editor. Approval workflow (draft \u2192 reviewed \u2192 approved).",
            items: "6-dimension Northstar eval · Inline section editor · Reorder / delete / add sections · Status workflow",
          },
          {
            num: 5, title: "Publishing",
            color: "FEE2E2", textColor: C.red,
            built: "ROADMAP", builtColor: C.red,
            desc: "Push approved articles to CMS, validate SEO metadata, map 301 redirects from legacy pages.",
            items: "CMS API export (WordPress / Contentful) · Canonical + redirect mapping · SEO validation",
          },
          {
            num: 6, title: "Memory",
            color: "F1F5F9", textColor: C.slate,
            built: "ROADMAP", builtColor: C.muted,
            desc: "Track published performance, identify content gaps automatically, schedule refreshes.",
            items: "GA4 performance import · Topic inventory (covered vs. missing) · Refresh scheduler · Content calendar",
          },
        ]),

        gap(16),

        // ── 8. BUSINESS IMPACT ────────────────────────────────────────
        heading1("8. Business Impact"),
        rule(C.purple),
        gap(6),

        heading3("Publishing velocity"),
        body("Manual production of one quality article: 3-5 hours (research + write + SEO-optimise). With Content Studio: 8-12 minutes end-to-end, including quality evaluation. Editorial review time is the primary remaining variable."),
        gap(6),

        kpiTable([
          { value: "25\u00D7", label: "Speed increase (vs. manual)",      color: C.purple },
          { value: "154",     label: "Topics ready to generate",          color: C.blue },
          { value: "3,500+",  label: "Legacy pages to consolidate",       color: C.green },
          { value: "0",       label: "Enterprise articles today (gap)",   color: C.red },
        ]),

        gap(12),
        heading3("Content gap coverage"),
        bullet("3,500+ legacy pages across car, health, bike, travel, and home insurance \u2014 identified and clustered into 154 unique consumer questions."),
        bullet("Zero evergreen Enterprise content exists today \u2014 Content Studio can generate the full library from briefs alone, no crawling needed."),
        bullet("Long-tail cluster identification surfaces questions that existing pages answer poorly or not at all."),
        gap(10),

        callout(
          "Bottom line",
          "Content Studio turns a multi-week content production backlog into a 2-day sprint. The editorial team\u2019s role shifts from writing to reviewing, editing, and approving \u2014 which is where their judgment adds the most value.",
          C.lightGreen, C.green
        ),

        gap(16),
        pageBreak(),

        // ── 9. APPENDIX ───────────────────────────────────────────────
        heading1("Appendix"),
        rule(C.purple),
        gap(6),

        heading2("A. Article JSON Schema (section types)"),
        gap(4),

        scoringTable([
          ["content_block",    "Rich HTML paragraph. Every paragraph opens with a <strong>bold lead-in</strong> (2\u20136 words)."],
          ["bullet_list",      "Scannable list. Each item is <strong>Lead:</strong> Explanation format."],
          ["comparison / table","Feature or plan tier comparison. Renders as a styled HTML table with header row."],
          ["faq",              "Accordion FAQ. Each item has a question (H3) and HTML answer. Adds FAQPage JSON-LD."],
          ["steps",            "Numbered implementation steps. Each step has a title and description paragraph."],
          ["expert_tip",       "Pull-quote callout. Includes author name and title."],
          ["callout_info / warning / tip", "Highlighted callout box. Info = blue, warning = amber, tip = green."],
          ["cta",              "Call-to-action block. Heading, description, button text and URL (template-specific)."],
        ], ["Section type", "Description"]),

        gap(12),
        heading2("B. Template Guide"),
        gap(4),

        scoringTable([
          ["informational.html", "Retail",     "Default B2C template. Friendly hero, quick answer box, sticky sidebar TOC, purple CTA."],
          ["transactional.html", "Retail",     "Buying guide template. CTA-heavy, comparison tables prominent, \u201CGet a Quote\u201D intent."],
          ["longtail.html",      "Long-tail",  "Compact template (800\u20131,200 words). No sidebar, tight layout, laser-focused on one question."],
          ["enterprise.html",    "Enterprise", "B2B corporate template. Dark navy header, Executive Summary box, IRDAI compliance badge, \u201CRequest a Group Quote\u201D CTA."],
        ], ["Template", "Business line", "Purpose"]),

        gap(12),
        heading2("C. AI Model Options"),
        gap(4),

        scoringTable([
          ["gpt-4.1 (default)", "Best balance of speed and quality. Recommended for all standard generation runs."],
          ["gpt-4.1-mini",      "2\u00D7 faster, ~70% quality. Good for fast drafts or bulk longtail generation."],
          ["gpt-5",             "Highest quality. Use for flagship Enterprise articles or complex multi-source briefs."],
          ["o4-mini / o3",      "Reasoning models. Ideal for evaluation and brief-fidelity checks."],
          ["gpt-4o / gpt-4o-mini", "Legacy models. Supported but not recommended for new generation runs."],
        ], ["Model", "Use case"]),

        gap(16),

        new Paragraph({
          spacing: sp(0, 0),
          children: [
            new TextRun({ text: "Acko Technology & Services Pvt. Ltd.  \u00B7  Confidential  \u00B7  April 2026", size: 16, color: C.muted, font: "Arial" }),
          ],
        }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then(buf => {
  const out = "/Users/kanika.oberoi/Desktop/seo crawler/Acko_Content_Studio_Product_Note.docx";
  fs.writeFileSync(out, buf);
  console.log("Written:", out);
});
