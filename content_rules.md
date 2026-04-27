# Acko Content Rules — the canon

This file governs how every Acko article is written. It applies to both Crawl-based and Brief-based articles. It is the source of truth; if anything in `northstar.md` or a prompt string contradicts this file, this file wins.

The whole document is built around one idea — the **Reader Contract**. Read it first; everything else is an application of it.

---

## 1. The Reader Contract

> **Every component of an article exists because the reader needs it here. Nothing exists because a checklist demanded it.**

A reader landed on this page with a real question. They are deciding whether to spend two minutes of their life on what we wrote. Each decision we make — to add a callout, to use a table instead of bullets, to break the page with an FAQ — must answer one question:

*Does this make the next 30 seconds of reading more useful, or am I just filling space?*

If you can't say what a section earns the reader, cut it. If a callout would interrupt a thought instead of punctuate it, leave it inline. If a comparison has only two dimensions, write it as a sentence; don't dress it as a table. **Composition over completeness.**

Three judgment calls that come up constantly:

- **Callout vs. inline emphasis.** A callout is for a fact the reader will hurt themselves by missing. *"IRDAI's claim deadline is 30 days from incident — miss it and your claim is forfeit."* That earns a callout. *"Most policies cover theft."* That's inline.
- **Table vs. bullets.** A table earns its space when there are ≥3 options or ≥4 dimensions, and the reader will scan across rows to compare. Two options with one difference each? A sentence with a semicolon does it.
- **FAQ block vs. body absorption.** An FAQ exists when 4+ residual questions remain after the body has done its job. If only two questions remain, fold them into the closing — don't pretend you have a bigger FAQ than you do.

If you find yourself adding something to satisfy a rule, stop and ask whether the rule serves the reader here. The rule is a default; the reader is the constraint.

---

## 2. Voice charter

We write as a **knowledgeable friend** — someone who knows insurance because they've worked with it for years, who answers your question as if you'd asked them at dinner. Not a brochure. Not a regulator. A friend.

Concretely:

- **No em dashes (—) or en dashes (–).** They are an LLM tic and a brand-voice failure. Use commas, colons, or full stops instead. Hyphens (-) inside compound words are fine.
- **Plain English first.** No jargon without a translation. *"Premium"* on first use becomes *"premium (the amount you pay each year to keep your policy active)."*
- **Second person.** "You" and "your", not "the customer" or "the policyholder."
- **Active verbs.** "File the claim within 30 days" beats "Claims should be filed within a 30-day period."
- **Contractions are fine.** *Don't*, *won't*, *here's*. Articles read warmer for it.
- **Sentences are short.** If a sentence has two ideas, make it two sentences.
- **Confidence without salesmanship.** Tell the reader what to do; don't tell them why Acko is great. If Acko is the right answer, the article will make that obvious.

### Worked example (use this tone)

> **What IDV actually means.** IDV is the maximum amount your insurer will pay if your car is stolen or written off. It's not what you paid for the car — it's what your car is worth today, after depreciation. For a three-year-old hatchback that cost ₹8 lakh new, the IDV is typically around ₹5 lakh. You'll see this number on every quote you compare. Pick a higher IDV and your premium goes up; pick a lower one and you're under-insured. The IRDAI sets standard depreciation rates for cars under five years old, so most insurers will quote the same IDV — give or take a percent.

### Anti-example (do not write like this)

> *"In today's fast-paced world, understanding the nuances of Insured Declared Value (IDV) is paramount for every car owner. It is important to note that IDV represents a critical component of your motor insurance policy. In this comprehensive guide, we shall delve into the intricacies of IDV calculation."*

What's wrong: filler opener ("in today's fast-paced world"), AI-tells ("it is important to note", "in this comprehensive guide", "delve into"), passive voice, abstract framing instead of a concrete answer, the reader is 50 words in and hasn't learned anything.

---

## 3. The narrative spine

Every article is a journey through four reader-questions, in order:

1. **Orient** — *What is this, and does it apply to me?*
2. **Understand** — *How does it work?*
3. **Decide** — *What should I do about it?*
4. **Close** — *What's the next step, and what else might I wonder?*

The job of each section is to move the reader one step further along this spine. Two structural rules make this work:

### 3a. The lede + stage-setter

The first two paragraphs answer the consumer's question in 60 seconds. A skimmer who reads only this should leave informed. **Then, before the first H2, write a stage-setter** — 80–150 words that frame *who this is for, what's at stake, and why this matters now*. The stage-setter is what's missing in current Acko output and what makes Plum and Lemonade articles feel composed instead of assembled.

Example stage-setter:

> *If you're buying car insurance for the first time — or renewing after a few years — IDV is the number that quietly shapes everything. It decides what you'll get if your car is stolen tomorrow. It decides what you'll pay every year. And because most online comparison tools display IDV as a single editable field, it's the easiest place to over-insure or under-insure yourself without realising. The next few sections walk through what IDV is, how it's calculated, and how to pick the right number for your car.*

### 3b. Bridge sentences

**Every section ends with a sentence that sets up the next section's question.** This is the cohesion lever. Without it, the article reads as stapled-together blocks. With it, the article reads as one piece.

Example bridge: a section on *"How IDV is calculated"* ends with — *"Now that you know how the number is built, the next question is whether you can change it."* The next section is *"Can you adjust your IDV?"*

If you can't write a bridge from one section to the next, the sections are in the wrong order — or one of them shouldn't exist.

---

## 4. Section choices

Section types are tools. Use the right one for the moment in the spine, not the one that was next on a list.

| Tool | Earns its place when… |
|---|---|
| **content_block** (paragraph) | The reader needs explanation, story, or nuance. The default. |
| **bullet_list** | 3–6 parallel items the reader will scan, not read in order. ≤3 → write as prose; ≥7 → reorganise. |
| **comparison_table** | ≥3 options OR ≥4 dimensions, and the reader will compare across rows. Otherwise prose or bullets. |
| **callout** (info / tip / warning) | A single fact the reader will damage themselves by missing. Punctuation, not paragraphs. **Max 1 per ~400 words; never adjacent to another callout.** |
| **steps** | A literal sequence the reader will execute (claim filing, document submission, online flow). Not a synonym for "list of things." |
| **faq** | 4+ residual questions remain after the body has done its job. Each answer 40–80 words. If fewer than 4, fold them into the closing. |
| **expert_tip** | A non-obvious shortcut or insider insight. One per article, max. Otherwise it's not insider — it's filler. |
| **cta** | At the end of the decide-phase: a soft, in-context link to the relevant Acko product or comparison page. Anchor text says what's there, not "click here." |

### Other composition rules

- **Bold lead-ins** on any paragraph >100 words. First 4–6 words bolded, working as a mini-headline. Carries the article on a skim.
- **Internal links**: 2–4 per article. Anchor text is the linked page's question or specific subject — never *"click here"*, *"learn more"*, or *"this article"*.
- **Density alternation**: avoid two consecutive sections of the same type. Paragraph → list → comparison → callout → paragraph reads as varied; four paragraphs in a row reads as a wall.

---

## 5. Hard rules (enforced post-generation)

These are the non-negotiables. Hard checks run on every article before save. A violation either auto-fixes or surfaces as a high-severity issue in the eval drawer.

1. **H1 is the consumer question, near-verbatim.** If the consumer searched *"does car insurance cover theft"*, that's the H1 — not *"Understanding Theft Coverage in Motor Insurance"*.
2. **Every H2 works as a standalone TOC entry, ≤10 words.** No *"Now let's look at…"*, *"Another factor"*, *"Here's the thing"*. Each H2 must be a complete, self-explanatory phrase or question when read in isolation in the table of contents — and short enough to scan in one glance. If you need more than 10 words, the H2 is doing two jobs; split the section.
3. **Mobile paragraph length: max 3 sentences.** Walls of text are a brand failure.
4. **Numeric claims trace or hedge.** Every ₹ amount, percentage, deadline, or day count either cites a source URL or hedges (*"typically"*, *"in most policies"*). Unsourced specifics are the #1 hallucination risk.
5. **Regulatory claims cite IRDAI by name.** Generic *"regulators require…"* is banned. Use *"IRDAI mandates…"* with the specific clause when known.
6. **IRDAI registration footer** on every published article. Standard line.
7. **"As of [month, year]" footnote** on any product comparison or pricing claim.
8. **No forbidden phrases** (canonical list lives in `content_rules.py:FORBIDDEN_PHRASES`; ~10 items, single source of truth).
9. **Stage-setter present** between the lede and the first H2.
10. **No adjacent callouts or boxes.** Any box-style section (callout, key-takeaway, IRDAI update, expert tip, info/warning/tip box) must be separated from the next one by ≥1 substantive content_block. Two boxes in a row is a structural failure.
11. **Box budget.** Maximum 3 box-style sections in any article, and at most 1 per ~400 words. If you cannot say "the reader will damage themselves by missing this fact," fold it into prose. Boxes are punctuation, not paragraphs.
12. **No em dashes or en dashes.** Replace every `—` and `–` with a comma, colon, or full stop.

---

## 6. Calibration excerpts — what good looks like

The two articles below are the bar. The point is not to copy text; it is to **imitate the pattern** — coverage breadth, the way they answer the next-question-the-reader-was-about-to-ask, the rhythm of explanation and example.

### Excerpt A — from *Plum: Difference between OPD and IPD*

> *OPD (Out-Patient Department) covers the medical expenses you incur without being hospitalised — a doctor consultation, a diagnostic test, a pharmacy bill for a prescription. You walk in, you walk out, and the bill stays under a few thousand rupees. IPD (In-Patient Department) kicks in when you're admitted to a hospital for at least 24 hours — a surgery, a serious infection, an accident. The bills here run into lakhs, and that's what most health insurance is designed for.*
>
> *The reason this distinction matters: most standard health insurance plans cover IPD generously and OPD barely or not at all. So if you're someone who sees a doctor four times a year for routine issues, a plan with strong OPD cover is worth paying extra for. If your medical history is mostly uneventful, an IPD-focused plan with a low premium is the better buy.*

**What to imitate:** Both terms defined with concrete examples (*"a pharmacy bill for a prescription"*, *"a surgery, a serious infection"*) before any abstract comparison. Then immediately the *decide-phase* sentence: *"the reason this distinction matters"* — telling the reader what to do with what they just learned. No padding between the definition and the decision.

### Excerpt B — from *Plum: Employer-employee insurance explained*

> *Employer-employee insurance is, on paper, a life insurance policy that the company buys for its employee. The company pays the premium, the employee is the insured, and the employee's family is the nominee. If something happens to the employee, the family receives the sum assured directly — without waiting for any internal company process.*
>
> *Two things are easy to misunderstand here. First, this isn't the same as group health insurance — that's a separate product, also employer-paid, but for hospital bills, not death benefits. Second, the tax treatment is unusual: the premium the company pays is a deductible business expense, but the payout to the employee's family is tax-free under section 10(10D). Most companies don't explain either of these clearly, which is why employees often think their group health insurance includes life cover. It doesn't.*

**What to imitate:** The article anticipates the two confusions a real reader will have — *"is this group health insurance?"* and *"how is this taxed?"* — and answers them inside the explanation, not in a separate FAQ at the end. That's coverage breadth. The article doesn't wait for the reader to ask; it surfaces the question itself, then resolves it.

---

*End of canon. Anything not covered here defaults to the Reader Contract: serve the reader, cut the rest.*
