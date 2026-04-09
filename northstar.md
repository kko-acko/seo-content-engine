# Acko Content Northstar

> The shared definition of "what good looks like" for AI-generated content.
> Used by the system prompt, the evaluation tab, and human reviewers.
> Nothing gets published unless it meets this bar.

---

## The 6 Quality Dimensions

### 1. Consumer Question Clarity (weight: 20%)

Does this article answer a real question a real person would search for?

| Score | Definition |
|-------|-----------|
| **5 — Great** | The H1 IS the question. First 2 paragraphs answer it directly. Reader knows within 5 seconds what this page is about and whether it's for them. |
| **4 — Good** | Question is clear. Answer appears early. Minor room to sharpen the H1 or opening. |
| **3 — Good enough** | Question is present but buried. Takes 1-2 scrolls to find the actual answer. Publishable with edits. |
| **2 — Below bar** | Question is vague. Page could be about 2-3 different things. Needs significant revision. |
| **1 — Fails** | No clear question. Reads like a keyword-stuffed SEO page or a generic overview. Regenerate. |

**Evaluator asks:** What is the one question this page answers? Can I state it in under 15 words? If not, the page fails.

---

### 2. Content Depth & Usefulness (weight: 20%)

Would someone actually find this useful, or is it padded?

| Score | Definition |
|-------|-----------|
| **5 — Great** | Every section adds new information. Reader learns something they didn't know. Covers the main question AND 2-3 adjacent questions they'd ask next. Specific numbers, examples, actionable advice. |
| **4 — Good** | Main question answered thoroughly. Most sections add value. One section could go deeper. |
| **3 — Good enough** | Covers the main question adequately. Some sections feel thin but nothing is wrong. Missing depth on adjacent topics. |
| **2 — Below bar** | Thin in places. Repeats itself. Missing key sub-topics. Needs content added. |
| **1 — Fails** | Repeats the same point in different words across sections. Generic statements ("car insurance is important"). No specific data. Written to fill space. |

**Evaluator asks:** After reading this, would I still need to Google the same question? If yes, the page fails.

---

### 3. Structure & Scannability (weight: 15%)

Can someone get the gist in 15 seconds of scrolling?

| Score | Definition |
|-------|-----------|
| **5 — Great** | Every H2 is a question I'd actually search. Bold lead-ins on bullets tell the story alone. Comparison tables where relevant. Clear visual rhythm — text, bullets, callout, table, repeat. |
| **4 — Good** | Sections are logical and well-ordered. Most H2s are question-format. Good use of bullets and tables. |
| **3 — Good enough** | Sections are reasonable but not all H2s are questions. Some long paragraphs. Could use more tables or bullets. |
| **2 — Below bar** | H2s are generic ("Overview", "Details"). Multiple long paragraphs. Hard to scan. |
| **1 — Fails** | Walls of text. No bullets. No tables. No visual breaks. Looks like a Word document pasted into a webpage. |

**Evaluator asks:** Can I understand the article's key points by reading only the H2s and bold text? If not, the structure fails.

---

### 4. Brand Voice & Publishability (weight: 15%)

Could this go live on Acko's blog with light editing?

| Score | Definition |
|-------|-----------|
| **5 — Great** | Reads like a knowledgeable friend explaining insurance. Second person throughout. Confident, not salesy. No jargon without explanation. Publishable as-is or with 1-2 minor edits. |
| **4 — Good** | Tone is mostly right. 1-2 sentences feel slightly generic. 5-10 minutes of editing. |
| **3 — Good enough** | Tone works overall. A few robotic or overly formal passages. 15-20 minutes of editing. |
| **2 — Below bar** | Mixed tone — parts sound human, parts sound like a textbook. Needs substantial voice editing. |
| **1 — Fails** | Sounds like ChatGPT wrote it. "In today's world...", "It is important to note...", "As we delve into...". Or sounds like a legal document. Full rewrite needed. |

**Forbidden phrases** (automatic score reduction):
- "In conclusion"
- "It is important to note"
- "In today's fast-paced world"
- "Needless to say"
- "As an AI language model"
- "Let us delve into"
- "In this comprehensive guide"

**Evaluator asks:** If I removed the Acko branding, would this sound like a generic insurance article or like Acko specifically? If generic, the voice fails.

---

### 5. Replaceability (weight: 15%)

Can this credibly replace the old page(s) it was built from?

| Score | Definition |
|-------|-----------|
| **5 — Great** | Covers everything the source pages covered AND more. Stronger structure. Better answers. Could consolidate 3-5 old pages into one. All internal links preserved. |
| **4 — Good** | Covers most source content plus some new depth. 1-2 minor details from source not carried over but not critical. |
| **3 — Good enough** | Roughly equivalent coverage to source pages. Better structure. A few minor gaps. |
| **2 — Below bar** | Missing key information from source pages. Important processes or facts dropped. |
| **1 — Fails** | Would lose significant SEO value if it replaced the old pages. Key content missing. Internal links dropped. |

**Evaluator asks:** If we 301-redirect all source URLs to this page tomorrow, would any user be worse off? If yes, the page fails.

---

### 6. Design & Visual Execution (weight: 15%)

Does this page look and feel like a professionally designed Acko page?

| Score | Definition |
|-------|-----------|
| **5 — Great** | Follows the Acko design system exactly. Visual rhythm alternates between white and alt (#F9FAFB) sections. Charts render in brand colours where data exists. Mobile sticky CTA visible. FAQ accordion smooth. Comparison tables styled with dark headers. Feels like a real product page, not a template. |
| **4 — Good** | Design system followed. One section could use a visual element (chart, table, callout) it's missing. Mobile works well. |
| **3 — Good enough** | Colours and typography correct. Layout works. 1-2 sections feel visually flat. Mobile is functional but not polished. |
| **2 — Below bar** | Inconsistent styling. Some cards missing borders/shadows. Sections run together. Mobile has issues. |
| **1 — Fails** | Looks like a blog from 2018. No visual hierarchy. Mobile breaks. No charts despite numeric data. No CTA without scrolling. |

**Design checklist:**

- [ ] Section rhythm: white → alt → white → purple CTA. Never two identical backgrounds in a row.
- [ ] Card styling: 1px border (#E5E7EB), 12-16px radius, shadow on hover, 1.5rem padding.
- [ ] Typography hierarchy: H1 (2.4-2.8rem/900) > H2 (1.5-1.6rem/800) > H3 (1.1-1.25rem/700) > body (1rem/400). All clearly distinct.
- [ ] Data visualisation: Chart present if source had numeric data. Brand purple. Title + source attribution. Empty array if no data.
- [ ] Trust signals: Author bar with name + credential. Breadcrumb. IRDAI number in footer.
- [ ] Mobile: Single column. Sticky CTA bottom. Horizontal scroll on tables. FAQ full-width. No horizontal overflow.
- [ ] CTA placement: Hero, mid-article (after 3rd section), bottom banner, mobile sticky. Never >2 scroll-lengths between CTAs.
- [ ] Layout variant: Listicle → numbered H2s. How-to → step cards. Essay → no sidebar. Explainer → sidebar TOC. Wrong variant = wrong feel.
- [ ] Whitespace: 72px section padding desktop, 48px mobile. Nothing cramped, nothing empty.
- [ ] Interactive: FAQ accordion toggles. TOC highlights active section. Progress bar fills on scroll. Hover states on cards/buttons.

---

## Scoring & Publishing Threshold

### Per-article score
Each dimension scored 1-5. Weighted average calculated.

| Dimension | Weight |
|-----------|--------|
| Consumer question clarity | 20% |
| Content depth & usefulness | 20% |
| Structure & scannability | 15% |
| Brand voice & publishability | 15% |
| Replaceability | 15% |
| Design & visual execution | 15% |

### Publishing rules

| Threshold | Action |
|-----------|--------|
| **Weighted avg ≥ 4.0, no dim < 3** | Auto-approve. Ready to publish. |
| **Weighted avg ≥ 3.5, no dim < 2** | Conditionally approve. Publish with minor edits flagged. |
| **Weighted avg < 3.5 OR any dim < 2** | Reject. Flag for regeneration or manual rewrite. |

### Scaling rules

| Phase | Batch size | Required consistency |
|-------|-----------|---------------------|
| Pilot | 1-5 articles | Every article manually reviewed against this framework. |
| Early scale | 6-20 articles | AI evaluation + human spot-check on 50%. Avg ≥ 4.0 across batch. |
| Growth | 20-100 articles | AI evaluation on all. Human spot-check on 20%. No batch avg below 3.8. |
| Steady state | 100+ articles | AI evaluation on all. Human review only for scores < 3.5 or flagged items. |

---

## How this is used

### By the system prompt
The prompt encodes these standards directly — question-led H1s, scannable structure, Acko voice, depth requirements, forbidden phrases.

### By the Evaluate tab (AI critic)
A second AI pass scores each generated article on all 6 dimensions with written reasoning. Scores below threshold are flagged.

### By human reviewers
The northstar is the rubric. Reviewers don't need to invent what "good" means — they score against this framework and add notes.

### By the team for prompt tuning
When output consistently fails on a specific dimension (e.g., voice always scores 3), the team knows exactly which part of the prompt to improve.
