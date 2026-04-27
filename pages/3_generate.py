"""
Step 3 — Cluster-Based Article Generator
==========================================
Takes a cluster (multiple source pages answering the same consumer question),
feeds ALL of them to OpenAI, and generates ONE new article that answers the
question better than any individual source page.

This is NOT a rewriter. It's a blog-writing agent.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import sys
import jinja2
import openai
import pandas as pd

# Add project root to path for ai_helpers import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_helpers import MODELS, build_messages, build_api_kwargs, extract_json
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "crawl_state.db"
CLUSTER_DB_PATH = PROJECT_ROOT / "clusters.db"
ARTICLES_DB_PATH = PROJECT_ROOT / "articles.db"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
ARTICLES_DIR = PROJECT_ROOT / "generated_articles"

TEMPLATE_MAP = {
    "transactional": "transactional.html",
    "informational": "informational.html",
    "longtail": "longtail.html",
    "enterprise": "enterprise.html",
}
FALLBACK_TEMPLATE = "informational.html"


def get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# JSON Schema for article output
# ---------------------------------------------------------------------------

ARTICLE_JSON_SCHEMA = r"""{
    "page_classification": "informational | longtail",
    "content_format": "guide | explained | how-to | compared | checklist | deep-dive | myth-buster",
    "layout_type": "explainer | listicle | how-to | essay",
    "quick_answer": "str - 2-3 sentence direct answer with at least one specific number. Renders as a highlighted box at the top.",
    "page_title": "str - 50-60 char SEO title tag",
    "meta_description": "str - 150-155 char meta description with CTA",
    "suggested_slug": "str - URL slug e.g. what-affects-car-insurance-premium",
    "canonical_url": "str - suggested canonical URL",
    "breadcrumb": [{"text": "str", "url": "str"}],
    "product_label": "str - e.g. CAR INSURANCE",
    "h1": "str - the consumer question as an H1",
    "subtitle": "str - 1-2 sentence answer preview",
    "author": {"name": "str", "title": "str"},
    "reviewer": {"name": "str", "title": "str"},
    "sections": [
        {
            "type": "content_block | bullet_list | comparison | expert_tip | faq | steps | cta | related_articles | table | callout_info | callout_tip | callout_warning",
            "heading": "str or null",
            "content": "varies by type — see SECTION CONTENT FORMAT below",
            "key_takeaway": "str or null — a 1-2 sentence callout box shown after this section (optional, use for 2-3 most important sections)"
        }
    ],
    "graph_data": [
        {
            "title": "str",
            "type": "bar | line | pie",
            "labels": ["str"],
            "values": [0],
            "unit": "str or null",
            "source": "str or null"
        }
    ],
    "internal_links_footer": [{"href": "str", "text": "str"}],
    "source_urls": ["str - list of source URLs this article was built from"]
}

SECTION CONTENT FORMAT:

content_block:
  {"html": "<p>Paragraph with <strong>bold lead-in</strong> and <a href='...'>links</a>.</p><p>Second paragraph.</p><p>Third paragraph with a relatable example or scenario.</p>"}

bullet_list:
  {"items": ["<strong>Bold lead:</strong> Explanation sentence.", ...]}

comparison / table:
  {"rows": [{"feature": "...", "option_a": "...", "option_b": "..."}, ...]}

expert_tip:
  {"quote": "The tip text", "name": "Expert Name", "title": "Designation"}

faq:
  {"items": [{"question": "Full question?", "answer": "<p>Answer with HTML.</p>"}, ...]}

steps:
  [{"step": 1, "title": "Step title", "description": "What to do"}, ...]

cta:
  {"heading": "...", "description": "...", "button_text": "...", "button_url": "..."}

related_articles:
  {"articles": [{"title": "...", "description": "...", "url": "..."}, ...]}

callout_info:
  {"text": "Regulatory note or important factual context.", "label": "IRDAI Update | Important | Note"}

callout_tip:
  {"text": "Practical pro tip or money-saving advice.", "label": "Pro Tip | Expert Tip"}

callout_warning:
  {"text": "Caveat, common mistake, or thing to watch out for.", "label": "Watch Out | Warning | Caveat"}
"""


# ---------------------------------------------------------------------------
# System prompt — blog-writing agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = r"""You are the blog editor for Acko's insurance content. You write original blog articles that answer real customer questions.

━━━ BUSINESS LINE AWARENESS ━━━

The prompt will specify BUSINESS LINE: ENTERPRISE | RETAIL | LONGTAIL. Adapt tone, IA, and page_classification accordingly.

ENTERPRISE (B2B — Group/Corporate Insurance)
  page_classification: "enterprise"
  AUDIENCE: HR heads, CFOs, fleet managers, procurement teams, operations leads
  TONE: Consultative, data-driven, ROI-focused. Like a McKinsey brief — precise, respects the reader's time, avoids fluff.
  CONTENT ANGLES TO EMPHASIZE:
    - Cost/ROI framing: ₹ per employee, total premium for group size, savings vs. self-insured
    - IRDAI compliance requirements and corporate mandates
    - Implementation logistics (enrollment workflows, HR admin portal, dependent additions)
    - Group policy structure vs. retail (floater vs. individual SI, sub-limits, restoration)
    - Claims process for HR-administered policies (TPA coordination, cashless network)
    - Premium factors for corporate groups: headcount, age mix, industry risk, prior claims ratio
    - Procurement and vendor evaluation (what to ask insurers, SLA expectations)
  SECTION TYPES TO PREFER: ROI/cost tables, compliance callout_info boxes, step-by-step implementation, plan tier comparisons
  AVOID: Consumer retail framing, "you" as an individual buyer, personal finance tone, casual language

RETAIL (B2C — Individual/Family Insurance)
  page_classification: "informational" | "longtail" | "transactional"
  Default tone — friendly, clear, helpful. Use all existing article rules.

LONGTAIL (narrow specific question — either audience)
  page_classification: "longtail"
  4-6 sections, 800-1,200 words. Determine B2B vs B2C from context.
  Every sentence must directly answer the ONE specific question being asked.

━━━ END BUSINESS LINE AWARENESS ━━━

You receive:
- A CONSUMER QUESTION that real customers are searching for
- RESEARCH MATERIAL from Acko's existing pages (treat as background research, not a template)
- EXTRACTED FACTS: key numbers, policy details, and examples pulled from source pages
- CLUSTER ANALYSIS (if available): consolidation strategy, user journey stage, content depth needed, subtopics
- CONTENT QUALITY ratings for each source page: THIN (<300 useful words), ADEQUATE (covers topic, lacks depth), COMPREHENSIVE (deep with specific facts)
- SUBTOPICS that must each get at least one section or substantial paragraph

Your job: Write one blog article that answers this question so completely that the reader never needs to Google it again.

━━━ USING CLUSTER ANALYSIS ━━━

When CLUSTER ANALYSIS is provided, use it to guide your approach:

CONSOLIDATION STRATEGY:
  - CREATE_COMPREHENSIVE_GUIDE → Write an authoritative long-form guide covering ALL subtopics. Go deep on every angle.
  - MERGE_DUPLICATES → Source pages overlap heavily. De-duplicate, create one clear narrative that's better than any individual page.
  - FILL_CONTENT_GAP → Source pages are missing key angles. Pay special attention to subtopics NOT covered by existing pages — fill those gaps.
  - KEEP_AND_LINK → Write a hub page that covers the main question and links to supporting content for sub-topics.

USER JOURNEY STAGE — match tone and depth:
  - awareness → Explain concepts from scratch. Don't assume knowledge. Use analogies.
  - consideration → Compare options, present trade-offs, help narrow choices.
  - decision → Enable action. Specific steps, exact costs, "if you X, then do Y" recommendations.
  - post_purchase → Practical how-to for existing policyholders. Claims, renewals, changes.

CONTENT QUALITY per source page:
  - Prioritize extracting facts and data from COMPREHENSIVE source pages over THIN ones.
  - THIN pages may still have 1-2 useful facts — grab those but don't rely on them for structure.
  - If most sources are THIN, you'll need to be extra thorough in structuring the article logically.

SUBTOPICS: Every listed subtopic must appear in your article — either as its own section heading or covered substantially within a section. Missing a subtopic = quality fail.

The article is for HUMAN REVIEW before publication. Write it like a Stripe or Toptal blog post — precise, expert-depth, clean formatting, every sentence earns its place.

━━━ CONTENT DEPTH (most important rule) ━━━

DEPTH COMES FIRST, STRUCTURE SECOND. The skeleton below is a guide, but the priority is:
1. FULLY COVER the topic — every angle, every edge case, every real-world scenario
2. USE SPECIFIC DATA from the source material — real ₹ amounts, real percentages, real examples
3. THEN fit into the skeleton structure

Every paragraph must contain SUBSTANTIVE INFORMATION — a fact, a number, an example,
a comparison, or a decision rule. If a paragraph could be deleted without the reader
losing any information, delete it yourself before outputting.

ZERO TOLERANCE for these filler patterns:
  ✗ "You'll learn about X, Y, and Z" — just TEACH X, Y, and Z directly
  ✗ "This is more than just numbers" — meaningless filler
  ✗ "We'll cover car specifics, claims history, and more" — don't preview, just write
  ✗ "Understanding X is crucial/important/essential" — explain X instead
  ✗ "Let's explore/examine/look at" — just present the content
  ✗ "Grasp these elements to strategically manage" — vague, says nothing
  ✗ Any sentence that talks ABOUT the article instead of teaching the reader something

TEST: For every sentence, ask "Does this teach the reader a NEW FACT they didn't know?"
If the answer is no, rewrite it with a specific fact or delete it.

━━━ IA RULES (article skeleton) ━━━

Your job is to write DECISION-ENABLING content, not just informational content.
Every section must move the reader closer to making a confident decision — not just
understanding a concept. Think: "After reading this section, can the reader DO something
they couldn't before?"

ARTICLE SKELETON (follow this order — adapt depth per topic):

PHASE 1: ORIENT THE READER (first 2 sections, always present)

  Section 1 — THE STAKES (content_block)
    Heading: Topic-specific, not "Introduction". Frame why this matters NOW.
    Content: 2-3 paragraphs with REAL INFORMATION, not meta-commentary:
      (a) A concrete fact or number that frames the topic (e.g., "The average comprehensive premium in India is ₹8,000-15,000/year")
      (b) A specific reason this matters NOW (a regulation, a market trend, a common costly mistake)
      (c) The core trade-off or decision the reader faces
    Follow with a callout_info if there's a regulatory update, IRDAI rule, or
    recent policy change that affects this topic.

    NEVER write "You'll learn about..." or "We'll cover..." — just START teaching.

    GOOD: "A 2024 Maruti Swift in Mumbai costs ₹8,200/year to insure. But pick the wrong policy and a single claim could cost you ₹50,000 out of pocket."
    BAD: "Premiums vary widely. You'll learn key influencing factors."

  Section 2 — OVERVIEW (content_block)
    Heading: Restate the question as a confident statement.
    Content: Give the ACTUAL ANSWER in 2-3 substantive paragraphs:
    - Start with the direct answer — what are the key factors/options/outcomes?
    - Include at least one specific number, comparison, or example
    - Name the 3-4 main factors/concepts concretely (not "we'll cover X, Y, Z" — actually EXPLAIN them briefly)
    This should be useful ON ITS OWN — a reader who only reads this section should walk away informed.
    Add key_takeaway summarizing the core insight.

    GOOD: "Your premium depends on four things: your car's IDV (₹4-12 lakh for most cars), your city (metro = 15-20% more), your claim history (NCB saves up to 50%), and your coverage type."
    BAD: "Multiple factors affect premiums. We'll explore car specifics, geography, and more."

PHASE 2: BUILD UNDERSTANDING (2-4 sections, pick what fits)

  Section 3 — TYPES / CATEGORIES (content_block or bullet_list)
    Only include if the topic has distinct types, plans, or categories.
    Name each type with a 1-sentence definition + who it's best for.
    If possible, include cost range or coverage scope for each type.

  Sections 4-6 — DEEP DIVES (content_block, vary with bullet_list)
    Each section covers ONE concept or factor. For EVERY concept, include:
      → WHAT it is (1 sentence, plain English definition)
      → HOW it works (2-3 sentences explaining the mechanism)
      → EXAMPLE with real numbers (₹ amounts, specific cars, real cities)
      → WHEN it applies to the reader (which situation, which car, which driver)
      → WATCH OUT — one specific mistake or misconception people make

    If a concept doesn't need all 5 layers, it's probably not worth a section.
    Add key_takeaway on the 2-3 most important sections.

    After every 2 content_blocks, insert ONE of:
      - callout_tip (practical money-saving or decision-making advice)
      - callout_warning (common mistake or trap to avoid)
      - bullet_list (for lists of items, factors, or steps)

PHASE 3: ENABLE THE DECISION (2-3 sections)

  COMPARISON TABLE (comparison — if applicable, when 2+ options exist)
    Include real trade-offs — not marketing feature lists.
    Every row must have: concrete metrics (₹, %, count), not just "Yes/No".
    Add a note below the table citing the data source or caveats.

  DECISION GUIDE (content_block)
    Structure as persona-driven recommendations:
      "If you [specific situation] → [specific recommendation + why]"
    Cover 3-4 real scenarios (e.g., new buyer, renewal, luxury car, budget-conscious).
    This is the MOST VALUABLE section — the reader came here to decide.
    Add a callout_tip with the single best piece of actionable advice.

PHASE 4: CLOSE STRONG (2 sections)

  FAQ (faq, 6-8 questions)
    Questions someone would ask AFTER reading the article, not repeats of H2s.
    Answers: 2-3 sentences each, practical, specific, with numbers where possible.

  QUICK SUMMARY (bullet_list — mandatory last section)
    5-7 bullets with <strong>bold lead-ins</strong> summarizing key takeaways.
    This is for readers who scrolled to the bottom or want a refresher.
    Each bullet should be self-contained — someone reading ONLY this section
    should get the essential points of the entire article.
    End with a bridge to a related topic or next action.

━━━ SECTION VARIETY RULES ━━━

STRICT — the AI must follow these:
  - NEVER two content_block sections in a row without a visual break between them
    (callout, bullet_list, comparison, or expert_tip)
  - Every article uses at least 4 different section types
  - Every article includes at least 1 callout box (callout_info, callout_tip, or callout_warning)
  - Minimum 8 sections for informational articles, 4 for longtail
  - The DECISION GUIDE section is mandatory for "compared", "guide", and "explained" formats

━━━ TONE GUARDRAIL ━━━

This is EDUCATIONAL content, not sales content. The goal is to help the reader
understand, evaluate, and decide — not to push them toward a purchase.

- Explain concepts clearly with real examples and numbers
- Present multiple options fairly — never position one option as "the best"
- When mentioning specific companies, present them as examples, not recommendations
- Use numbers to educate (₹ amounts, percentages) — not to sell
- Avoid urgency language ("don't miss out", "act now", "limited time")

━━━ LANGUAGE RULES (voice) ━━━

TONE: A sharp, knowledgeable friend who works in insurance. Precise like Stripe's docs. Deep like a Toptal article. Friendly like Lemonade's blog. Never salesy.

PARAGRAPHS:
  - Maximum 3 sentences per paragraph. If you need more, start a new <p>.
  - EVERY paragraph starts with a <strong>bold lead-in</strong> (2-6 words).
    Someone reading ONLY the bold text should get 80% of the value.

  EXAMPLE:
  <p><strong>Comprehensive covers everything.</strong> Your own car damage, third-party liability, theft, fire, and natural disasters.</p>
  <p><strong>Third-party is the legal minimum.</strong> It only covers damage you cause to someone else. Your own car? Not covered.</p>

SPECIFICITY:
  BAD: "Premiums vary based on multiple factors."
  GOOD: "A 25-year-old in Mumbai pays ~₹8,000/year. Same car in a tier-3 city? ₹5,500."

VOICE: Second person ("you/your"), active voice, present tense, short sentences.

BANNED PHRASES (never use these — instant quality fail):
"In conclusion", "It is important to note", "In today's world",
"Needless to say", "Let us delve into", "In this comprehensive guide",
"Without further ado", "It's worth noting", "One should consider",
"As we explore", "As per", "In the realm of",
"You'll learn", "We'll cover", "We'll explore", "Let's look at",
"Let's examine", "Let's dive into", "In this article",
"This article will", "This guide covers", "Read on to discover",
"Understanding X is crucial", "Understanding X is important",
"It goes without saying", "Grasp these elements",
"This is more than just", "multiple factors", "various factors"

ALL content uses HTML. <strong> for bold (NEVER **), <p> tags, <ul><li> for lists.

CONTENT FORMATS: Choose the best fit for the question:
  - "guide" — comprehensive how-to for complex topics
  - "explained" — concept explainer for "what is" questions
  - "how-to" — step-by-step process for "how do I" questions
  - "compared" — side-by-side for "vs" or "which is better" questions
  - "checklist" — actionable list for "what do I need" questions
  - "deep-dive" — in-depth analysis for niche topics
  - "myth-buster" — corrective content for common misconceptions

━━━ VISUAL RULES (formatting) ━━━

HEADINGS:
  - 6-18 words, specific to the topic
  - Mix: ~40% questions, ~30% statements, ~20% insight-driven, ~10% actionable
  - Every heading should make someone want to read that section

VOLUME:
  - Informational: 8-12 sections, 1,800-2,500 words
  - Longtail: 4-6 sections, 800-1,200 words

KEY TAKEAWAY: Add to 2-3 important sections. Renders as a highlighted callout.
Example: "<strong>Bottom line:</strong> Comprehensive covers your car AND others. Third-party only covers damage you cause to someone else."

QUICK ANSWER BOX: Add a "quick_answer" field — a concise overview (2-3 sentences) that frames the topic and sets the stage for the article. Renders as a highlighted box at the top.

━━━ GOLDEN EXAMPLE ━━━

This is what a GREAT section looks like. Match this quality:

{
  "heading": "How much does comprehensive car insurance actually cost?",
  "type": "content_block",
  "content": {"html": "<p><strong>Expect ₹8,000–₹15,000/year for most cars.</strong> A 2023 Maruti Swift in Mumbai with comprehensive cover costs ~₹8,200/year. A Hyundai Creta? Around ₹12,500. These are real premium ranges — your exact price depends on car value, city, and your claim history.</p><p><strong>Your car's age is the biggest factor.</strong> A brand-new car has high IDV (Insured Declared Value), so premiums are higher. After 5 years, the IDV drops ~50%, and so does your premium — but so does your payout if the car is totalled.</p><p><strong>Watch out for the deductible trap.</strong> A ₹1,000 voluntary deductible can cut your premium by ₹800/year. But if you claim, you pay ₹1,000 out of pocket. Worth it if you rarely claim. Not worth it if you drive in Delhi traffic.</p>"},
  "key_takeaway": "<strong>Bottom line:</strong> Budget ₹8K–₹15K/year. Use voluntary deductible only if you claim less than once every 2 years."
}

Notice: bold lead-ins carry the message, real ₹ numbers, specific car models, a watch-out, and a key takeaway with a decision rule. THIS is the bar.

━━━ ACCURACY ━━━

- Numbers, premiums, IRDAI references must come from source data
- Never invent coverage details or policy features
- If data is thin, write around what IS there
- graph_data must come from source content. Empty array if none.

━━━ INTERNAL LINKS ━━━

Weave ALL internal links from source pages naturally into content. Also list in internal_links_footer.

━━━ LAYOUT TYPE ━━━

- explainer: concept explanations with sidebar TOC
- listicle: numbered sections ("top X", "best Y")
- how-to: step-by-step with cards
- essay: deep narrative, single column

━━━ BEFORE YOU OUTPUT ━━━

Re-read your ENTIRE article and check. If ANY check fails, fix it before outputting:

1. FILLER CHECK: Read every paragraph. Does each one teach a NEW FACT? Delete or rewrite any sentence that talks about the article itself ("You'll learn...", "We'll cover...") instead of teaching.
2. DEPTH CHECK: Does every concept get the full depth (what/how/example with ₹ numbers/when/watch-out)? If a section has only 1-2 generic sentences, it's too shallow — expand it.
3. SPECIFICITY CHECK: Are there specific ₹ amounts, percentages, or real examples in at least 5 sections? If you wrote "premiums vary" anywhere, replace it with actual numbers.
4. STRUCTURE CHECK: Does the article follow the 4-phase skeleton? At least 4 different section types? At least 1 callout box?
5. DUPLICATION CHECK: Does the Quick Summary (last section) contain DIFFERENT phrasing from the body? Don't just copy-paste bullet points from earlier sections.
6. SKELETON CHECK: Is the last section a bullet_list QUICK SUMMARY with 5-7 points?
7. BOLD CHECK: Does every paragraph start with a <strong>bold lead-in</strong>? Can someone reading ONLY bold text get 80% of the value?

━━━ OUTPUT ━━━

Return ONLY valid JSON matching the schema. No markdown fences. No explanation.

""" + ARTICLE_JSON_SCHEMA


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_articles_db() -> None:
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            article_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id       INTEGER,
            consumer_question TEXT,
            suggested_slug   TEXT,
            page_classification TEXT,
            layout_type      TEXT,
            structured_json  TEXT,
            html_content     TEXT,
            source_urls_json TEXT,
            eval_score       REAL,
            eval_json        TEXT,
            status           TEXT DEFAULT 'draft',
            generated_at     TEXT DEFAULT (datetime('now')),
            model_used       TEXT
        )
    """)
    # Migrate: add new columns if they don't exist yet
    for col, coltype in [
        ("business_line", "TEXT DEFAULT 'retail'"),
        ("eeat_json", "TEXT"),
        ("seo_geo_json", "TEXT"),
    ]:
        try:
            conn.execute("ALTER TABLE articles ADD COLUMN {} {}".format(col, coltype))
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_article(cluster_id: int, question: str, result: dict,
                 html: str, source_urls: List[str], model: str,
                 business_line: str = "retail") -> int:
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    cursor = conn.execute(
        """INSERT INTO articles
           (cluster_id, consumer_question, suggested_slug, page_classification,
            layout_type, structured_json, html_content, source_urls_json, model_used, business_line)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cluster_id,
            question,
            result.get("suggested_slug", ""),
            result.get("page_classification", "informational"),
            result.get("layout_type", "explainer"),
            json.dumps(result, ensure_ascii=False),
            html,
            json.dumps(source_urls, ensure_ascii=False),
            model,
            business_line,
        ),
    )
    article_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return article_id


def update_article(article_id: int, result: dict, html: str) -> None:
    """Update an existing article's structured_json and html_content."""
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.execute(
        """UPDATE articles SET structured_json = ?, html_content = ?,
           suggested_slug = ?, page_classification = ?, layout_type = ?
           WHERE article_id = ?""",
        (
            json.dumps(result, ensure_ascii=False),
            html,
            result.get("suggested_slug", ""),
            result.get("page_classification", "informational"),
            result.get("layout_type", "explainer"),
            article_id,
        ),
    )
    conn.commit()
    conn.close()


def update_article_eval(article_id: int, eval_result: dict) -> None:
    """Persist EEAT + SEO/GEO eval payload onto an article row."""
    if not eval_result or "error" in eval_result:
        return
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.execute(
        """UPDATE articles SET eval_json = ?, eval_score = ?,
           eeat_json = ?, seo_geo_json = ? WHERE article_id = ?""",
        (
            json.dumps(eval_result, ensure_ascii=False),
            float(eval_result.get("overall_score", 0) or 0),
            json.dumps(eval_result.get("eeat", {}), ensure_ascii=False),
            json.dumps(eval_result.get("seo_geo", {}), ensure_ascii=False),
            article_id,
        ),
    )
    conn.commit()
    conn.close()


def load_articles() -> List[Dict]:
    if not ARTICLES_DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM articles ORDER BY generated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_clusters() -> List[Dict]:
    if not CLUSTER_DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM clusters ORDER BY priority DESC, cluster_id"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = {
            "cluster_id": r["cluster_id"],
            "consumer_question": r["consumer_question"],
            "theme": r["theme"],
            "page_group": r["page_group"],
            "priority": r["priority"],
            "urls": json.loads(r["urls_json"]) if r["urls_json"] else [],
            "status": r["status"],
        }
        try:
            d["audience_persona"] = r["audience_persona"] or ""
        except (IndexError, KeyError):
            d["audience_persona"] = ""
        try:
            d["search_trigger"] = r["search_trigger"] or ""
        except (IndexError, KeyError):
            d["search_trigger"] = ""
        try:
            d["secondary_questions"] = json.loads(r["secondary_questions_json"] or "[]")
        except (IndexError, KeyError, json.JSONDecodeError):
            d["secondary_questions"] = []
        # Enrichment fields (Phase 2)
        try:
            d["enrichment"] = json.loads(r["enrichment_json"] or "{}")
        except (IndexError, KeyError, json.JSONDecodeError):
            d["enrichment"] = {}
        try:
            d["page_details"] = json.loads(r["page_details_json"] or "[]")
        except (IndexError, KeyError, json.JSONDecodeError):
            d["page_details"] = []
        # Content Engine fields
        try:
            d["business_line"] = r["business_line"] or "retail"
        except (IndexError, KeyError):
            d["business_line"] = "retail"
        try:
            d["brief_text"] = r["brief_text"] or ""
        except (IndexError, KeyError):
            d["brief_text"] = ""
        try:
            d["input_type"] = r["input_type"] or "crawled"
        except (IndexError, KeyError):
            d["input_type"] = "crawled"
        result.append(d)
    return result


def get_page_data(url: str) -> Optional[Dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_cluster_page_data(urls: List[str]) -> List[Dict]:
    """Load full crawled data for all URLs in a cluster."""
    pages = []
    for url in urls:
        data = get_page_data(url)
        if data:
            pages.append(data)
    return pages


# ---------------------------------------------------------------------------
# Build user prompt from cluster
# ---------------------------------------------------------------------------

def build_cluster_prompt(cluster: Dict, pages: List[Dict]) -> str:
    """Build a user prompt that contains ALL pages in the cluster."""
    parts = []

    business_line = cluster.get("business_line", "retail")
    input_type = cluster.get("input_type", "crawled")
    brief_text = cluster.get("brief_text", "")

    # ---- BRIEF-BASED PATH (no crawled pages needed) ----
    if brief_text and input_type in ("brief", "ref_url"):
        parts.append("BUSINESS LINE: {}".format(business_line.upper()))
        parts.append("CLUSTER QUESTION: {}".format(cluster["consumer_question"]))
        if cluster.get("theme"):
            parts.append("CLUSTER THEME: {}".format(cluster["theme"]))
        if cluster.get("audience_persona"):
            parts.append("TARGET AUDIENCE: {}".format(cluster["audience_persona"]))
        if cluster.get("secondary_questions"):
            parts.append("SECONDARY QUESTIONS TO ALSO ANSWER:")
            for sq in cluster["secondary_questions"]:
                parts.append("  - {}".format(sq))
        parts.append("")
        parts.append("━━━ CONTENT BRIEF (PRIMARY RESEARCH SOURCE) ━━━")
        parts.append(brief_text[:8000])
        parts.append("")
        parts.append("━━━ YOUR TASK ━━━")
        parts.append('Write ONE new blog article answering: "{}"'.format(
            cluster["consumer_question"]))
        parts.append("")
        parts.append("The BRIEF above is your PRIMARY research source. Use ALL specific data points,")
        parts.append("product details, figures, and angles provided in the brief.")
        parts.append("Do NOT invent facts not present in the brief — if data is thin, write around what IS there.")
        parts.append("")
        if business_line == "enterprise":
            parts.append("Set page_classification to 'enterprise' in your JSON output.")
        parts.append("")
        parts.append("REQUIREMENTS:")
        parts.append("1. Follow the article SKELETON from your system instructions")
        parts.append("2. Include a quick_answer field with at least one specific figure or fact from the brief")
        parts.append("3. Every paragraph gets a <strong>bold lead-in</strong> and contains a specific fact or example")
        parts.append("4. Use at least 4 different section types")
        parts.append("5. Include at least 1 callout box")
        parts.append("6. Use HTML only (never markdown bold). Every section needs a heading (6-18 words)")
        parts.append("7. The LAST section must be a QUICK SUMMARY (bullet_list) with 5-7 key takeaway bullets")
        parts.append("8. Return ONLY valid JSON")
        return "\n".join(parts)

    # ---- CRAWLED PAGES PATH (existing behaviour) ----
    parts.append("BUSINESS LINE: {}".format(business_line.upper()))
    parts.append("CLUSTER QUESTION: {}".format(cluster["consumer_question"]))
    parts.append("CLUSTER THEME: {}".format(cluster["theme"]))
    parts.append("NUMBER OF SOURCE PAGES: {}".format(len(pages)))
    if cluster.get("audience_persona"):
        parts.append("TARGET AUDIENCE: {}".format(cluster["audience_persona"]))
    if cluster.get("search_trigger"):
        parts.append("SEARCH TRIGGER: {}".format(cluster["search_trigger"]))
    if cluster.get("secondary_questions"):
        parts.append("SECONDARY QUESTIONS TO ALSO ANSWER:")
        for sq in cluster["secondary_questions"]:
            parts.append("  - {}".format(sq))
    parts.append("")

    # ---- Enrichment context (Phase 2) ----
    enrichment = cluster.get("enrichment", {})
    if enrichment:
        parts.append("━━━ CLUSTER ANALYSIS (from deep enrichment) ━━━")
        if enrichment.get("consolidation_strategy"):
            parts.append("CONSOLIDATION STRATEGY: {}".format(enrichment["consolidation_strategy"]))
        if enrichment.get("user_journey_stage"):
            parts.append("USER JOURNEY STAGE: {}".format(enrichment["user_journey_stage"]))
        if enrichment.get("question_type"):
            parts.append("QUESTION TYPE: {}".format(enrichment["question_type"]))
        if enrichment.get("content_depth_needed"):
            parts.append("CONTENT DEPTH NEEDED: {}".format(enrichment["content_depth_needed"]))
        if enrichment.get("suggested_pillar_question"):
            parts.append("SUGGESTED PILLAR H1: {}".format(enrichment["suggested_pillar_question"]))
        if enrichment.get("estimated_impact"):
            parts.append("ESTIMATED IMPACT: {}".format(enrichment["estimated_impact"]))
        subtopics = enrichment.get("subtopics", [])
        if subtopics:
            parts.append("SUBTOPICS TO COVER (each must get at least one section or substantial paragraph):")
            for st_item in subtopics:
                parts.append("  - {}".format(st_item))
        parts.append("")

    # Build quality map from page_details for per-page annotations
    page_details = cluster.get("page_details", [])
    quality_map = {}
    for pd_item in page_details:
        if isinstance(pd_item, dict) and pd_item.get("url"):
            quality_map[pd_item["url"]] = {
                "content_quality": pd_item.get("content_quality", ""),
                "consolidation_role": pd_item.get("consolidation_role", ""),
                "quality_rationale": pd_item.get("quality_rationale", ""),
            }

    all_links = set()

    for i, page in enumerate(pages):
        body_text = page.get("body_text", "") or ""
        if len(body_text) > 12000:
            body_text = body_text[:12000] + "\n... [truncated — {} chars total]".format(len(body_text))

        # Collect internal links
        try:
            links = json.loads(page.get("internal_links_json") or "[]")
            for link in links:
                if isinstance(link, dict):
                    all_links.add(link.get("href", ""))
                elif isinstance(link, str):
                    all_links.add(link)
        except (json.JSONDecodeError, TypeError):
            pass

        parts.append("━━━ SOURCE PAGE {} ━━━".format(i + 1))
        page_url = page.get("url", "")
        parts.append("URL: {}".format(page_url))
        # Per-page quality annotation from enrichment
        qinfo = quality_map.get(page_url, {})
        if qinfo.get("content_quality"):
            parts.append("CONTENT QUALITY: {} | ROLE: {} | {}".format(
                qinfo["content_quality"],
                qinfo.get("consolidation_role", ""),
                qinfo.get("quality_rationale", ""),
            ))
        parts.append("TITLE: {}".format(page.get("title", "")))
        parts.append("H1: {}".format(page.get("h1", "")))
        parts.append("META: {}".format(page.get("meta_description", "")))

        headings = ""
        try:
            h_json = json.loads(page.get("headings_json") or "[]")
            for h in h_json:
                if isinstance(h, dict):
                    headings += "  {} {}\n".format(h.get("tag", ""), h.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            pass
        if headings:
            parts.append("HEADINGS:\n{}".format(headings))

        parts.append("BODY CONTENT:\n{}".format(body_text))
        parts.append("")

    parts.append("━━━ ALL INTERNAL LINKS (preserve every one) ━━━")
    for link in sorted(all_links):
        if link:
            parts.append(link)

    # Add extracted facts if available
    extracted_facts = cluster.get("_extracted_facts", "")
    if extracted_facts:
        parts.append("━━━ EXTRACTED FACTS (key data from source pages) ━━━")
        parts.append(extracted_facts[:4000])
        parts.append("")

    # Add feedback from previous evaluation if this is a retry
    feedback = cluster.get("_feedback", "")
    if feedback:
        parts.append("━━━ FEEDBACK FROM PREVIOUS ATTEMPT ━━━")
        parts.append(feedback)
        parts.append("Fix these specific issues in your new article.")
        parts.append("")

    parts.append("━━━ YOUR TASK ━━━")
    parts.append("Write ONE new blog article answering: \"{}\"".format(cluster["consumer_question"]))
    parts.append("")
    parts.append("These source pages are RESEARCH MATERIAL — not a template. Read them all, extract the useful facts, then write something DEEPER and MORE COMPREHENSIVE than any single source page.")
    parts.append("")
    parts.append("PRIORITY ORDER:")
    parts.append("1. DEPTH FIRST: Mine ALL specific data from the source pages — every ₹ amount, percentage, example, comparison, rule, deadline. Use them in the article. If a source page mentions a specific number, your article must include it.")
    parts.append("2. COMPREHENSIVENESS: Cover every sub-topic the source pages cover. If 5 source pages each cover a different aspect, your article covers ALL 5 aspects in depth.")
    parts.append("3. ZERO FILLER: Every sentence must teach a NEW FACT. Never write about the article itself ('You'll learn...', 'We'll cover...', 'This is more than...'). Just teach directly.")
    parts.append("4. THEN STRUCTURE: Fit the depth into the article skeleton.")
    parts.append("")
    parts.append("REQUIREMENTS:")
    parts.append("1. Follow the article SKELETON: Introduction → Overview → Context → Deep Sections → Comparison (if applicable) → Decision Guide → FAQ → Quick Summary")
    parts.append("2. Include a quick_answer field — a concise overview (2-3 sentences) with at least one specific number from source data")
    parts.append("3. Every paragraph gets a <strong>bold lead-in</strong> and contains a specific fact, number, or example")
    parts.append("4. Use at least 4 different section types (content_block, bullet_list, comparison, callout_info/tip/warning, faq)")
    parts.append("5. Include at least 1 callout box (callout_info, callout_tip, or callout_warning)")
    parts.append("6. Use HTML only (never markdown bold). Every section needs a heading (6-18 words)")
    parts.append("7. The LAST section must be a QUICK SUMMARY (bullet_list) with 5-7 key takeaway bullets — use DIFFERENT phrasing from the body, not copy-paste")
    parts.append("8. Return ONLY valid JSON")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Canon-driven system prompt builder
# ---------------------------------------------------------------------------
# When a research dict is available, we replace the legacy 700-line SYSTEM_PROMPT
# with: thin role prefix + content_rules canon + per-article research brief.
# The legacy SYSTEM_PROMPT remains as a fallback when research is unavailable.

_CANON_ROLE_PREFIX = r"""You are the staff writer for Acko's content team. You write original blog articles for Indian readers — answering real questions about insurance with the warmth and clarity of a knowledgeable friend.

Your output is a single JSON object describing the article (no markdown fences, no preamble). Schema:

{
  "h1": "<consumer question, near-verbatim>",
  "suggested_slug": "<kebab-case slug>",
  "page_classification": "informational | transactional | longtail | enterprise",
  "layout_type": "explainer | comparison | how_to | troubleshooting | decision_guide",
  "meta_title": "<55–65 chars>",
  "meta_description": "<140–160 chars>",
  "lede": "<2 short paragraphs answering the question in 60 seconds>",
  "stage_setter": "<80–150 word paragraph after lede, before first H2: who is this for, what's at stake, why now>",
  "sections": [
    {
      "section_id": "<stable-slug-id>",
      "heading": "<H2: self-explanatory in TOC isolation>",
      "type": "content_block | bullet_list | comparison_table | callout | steps | faq | expert_tip | cta",
      "content": <type-appropriate payload>,
      "bridge": "<sentence ending the section that sets up the next section's question>"
    },
    ...
  ],
  "faqs": [{"q": "...", "a": "<40–80 words>"}, ...],
  "cta": {"label": "...", "href": "<acko.com URL>", "context": "<one-sentence why this CTA here>"},
  "schema_blocks": ["Article", "FAQPage", ...],
  "irdai_footer": "<standard IRDAI registration line>"
}

You will be given the canon (rules that govern every Acko article) and a per-article brief (the IA + coverage for THIS article). Write to both.

The canon's reader contract supersedes everything: every component you include must serve the reader at this moment in their journey. If a section, callout, or block is not earning its place, cut it.
"""


def _build_canon_system_prompt(research: Optional[Dict] = None) -> str:
    """Compose the system prompt: role prefix + content_rules canon + research brief.
    Falls back to canon-only when research is missing."""
    try:
        from content_rules import load_rules
    except Exception:
        return SYSTEM_PROMPT  # legacy fallback

    canon = load_rules()
    parts = [_CANON_ROLE_PREFIX, "\n\n# THE CANON\n\n", canon]

    if research and "error" not in research:
        try:
            from research_v2 import render_research_brief
            parts.append("\n\n---\n\n# THIS ARTICLE\n\n")
            parts.append(render_research_brief(research))
        except Exception:
            pass

    return "".join(parts)


def generate_article(api_key: str, cluster: Dict, pages: List[Dict],
                     model: str = "gpt-4o",
                     research: Optional[Dict] = None) -> Dict:
    client = openai.OpenAI(api_key=api_key)
    user_prompt = build_cluster_prompt(cluster, pages)

    # Use canon-driven prompt when research is available; fall back to legacy.
    if research is not None:
        system_prompt = _build_canon_system_prompt(research)
    else:
        system_prompt = SYSTEM_PROMPT

    messages = build_messages(system_prompt, user_prompt, model)
    api_kwargs = build_api_kwargs(model, 16384, messages)
    response = client.chat.completions.create(**api_kwargs)

    text = response.choices[0].message.content.strip()

    try:
        return extract_json(text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse JSON", "raw_response": text}


# ---------------------------------------------------------------------------
# Quality Multiplier 1: Smart Source Extraction
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """Extract the useful facts from this insurance page. Return bullet points:
- Key numbers (₹ amounts, percentages, dates, timelines)
- Policy rules and eligibility criteria
- Specific examples or scenarios mentioned
- Common misconceptions addressed
- Any comparison data (plan vs plan, option vs option)

Be concise. Only include facts, not filler. If the page has little useful content, say "Minimal useful content."
"""


def extract_source_facts(api_key: str, pages: List[Dict],
                         model: str = "gpt-4o-mini") -> str:
    """Run a fast extraction pass on source pages to pull structured facts."""
    client = openai.OpenAI(api_key=api_key)

    all_facts = []
    for page in pages:
        body = (page.get("body_text") or "")[:6000]
        if not body.strip():
            continue

        try:
            extract_user = "URL: {}\nTitle: {}\n\n{}".format(
                        page.get("url", ""), page.get("title", ""), body)
            extract_msgs = build_messages(EXTRACT_PROMPT, extract_user, model)
            extract_kwargs = build_api_kwargs(model, 1024, extract_msgs)
            response = client.chat.completions.create(**extract_kwargs)
            facts = response.choices[0].message.content.strip()
            all_facts.append("From {}:\n{}".format(page.get("url", ""), facts))
        except Exception:
            continue

    return "\n\n".join(all_facts) if all_facts else ""


# ---------------------------------------------------------------------------
# Quality Multiplier 2: Editor Pass (self-edit)
# ---------------------------------------------------------------------------

EDITOR_PROMPT = """You are a senior editor reviewing an AI-generated insurance article for Acko. Your job is to IMPROVE it, not rewrite it.

Fix these specific issues (in priority order):

1. FILLER & META-COMMENTARY (most important): Delete or rewrite any sentence that talks ABOUT the article instead of teaching:
   ✗ "You'll learn about X" → Just explain X
   ✗ "We'll cover car specifics" → Directly discuss car specifics
   ✗ "This is more than just numbers" → Replace with an actual insight
   ✗ "Understanding X is crucial" → Explain WHY with a specific fact
   Every sentence must teach the reader something NEW. If it doesn't, delete it.

2. SHALLOW SECTIONS: Any section with only 1-2 generic sentences needs real depth — add specific ₹ amounts, car models, city names, percentages, or concrete examples.

3. GENERIC LANGUAGE: Replace ALL vague phrases:
   ✗ "Premiums vary based on multiple factors" → "A Maruti Swift in Mumbai costs ₹8,200/year; the same car in Lucknow is ₹5,500"
   ✗ "Various factors affect" → Name the exact factors with numbers

4. DUPLICATE CONTENT: If the Quick Summary repeats content verbatim from earlier sections, rewrite the summary with fresh phrasing.

5. Missing <strong>bold lead-in</strong> on paragraphs — add one (2-6 words).

6. Two paragraph-only sections back to back — convert one to a bullet list, table, or callout.

7. Any heading that's vague or generic — make it specific and compelling.

Return the COMPLETE corrected article JSON. Same schema, improved content. No markdown fences.
"""


def editor_pass(api_key: str, article_json: str, consumer_question: str,
                model: str = "gpt-4o", research: Optional[Dict] = None) -> Dict:
    """Run a second pass on the article to catch and fix quality issues.

    When the canon is available, the editor enforces it (instead of inventing
    its own list). The legacy EDITOR_PROMPT is appended as concrete examples
    so the editor still has actionable patterns to fix."""
    client = openai.OpenAI(api_key=api_key)

    # Build canon-aware editor prompt when content_rules is available
    editor_system = EDITOR_PROMPT
    try:
        from content_rules import load_rules
        canon = load_rules()
        editor_system = (
            "You are the senior editor enforcing the Acko content canon on a freshly drafted article. "
            "Your job is to spot drift from the canon and fix it. Do not invent rules; do not rewrite "
            "the article wholesale. Return the COMPLETE corrected article JSON, same schema, improved content. "
            "No markdown fences.\n\n"
            "# THE CANON (your enforcement reference)\n\n"
            + canon
            + "\n\n---\n\n# Concrete patterns to catch (in priority order)\n\n"
            + EDITOR_PROMPT
        )
        if research and "error" not in research:
            try:
                from research_v2 import render_research_brief
                editor_system += "\n\n---\n\n# This article's brief\n\n" + render_research_brief(research)
            except Exception:
                pass
    except Exception:
        pass

    editor_user = "CONSUMER QUESTION: {}\n\nARTICLE JSON:\n{}".format(
        consumer_question, article_json[:14000])
    editor_msgs = build_messages(editor_system, editor_user, model)
    editor_kwargs = build_api_kwargs(model, 16384, editor_msgs)
    response = client.chat.completions.create(**editor_kwargs)

    text = response.choices[0].message.content.strip()

    try:
        return extract_json(text)
    except json.JSONDecodeError:
        return {"error": "Editor pass failed to parse", "raw": text}


# ---------------------------------------------------------------------------
# Quality Multiplier 3: Auto-Evaluate + Regenerate
# ---------------------------------------------------------------------------

def _quick_evaluate(api_key: str, article_json: str, consumer_question: str,
                    source_urls: List[str], model: str = "gpt-4o") -> Dict:
    """EEAT + SEO/GEO scorecard via evaluation_v2.run_evaluation."""
    try:
        import evaluation_v2 as _ev
    except Exception as e:
        return {"error": "evaluation_v2 import failed: {}".format(e)}
    return _ev.run_evaluation(api_key, article_json, source_urls, consumer_question, model)


def generate_with_quality(api_key: str, cluster: Dict, pages: List[Dict],
                          model: str = "gpt-4o",
                          enable_extraction: bool = True,
                          enable_editor: bool = True,
                          enable_auto_eval: bool = True,
                          status_callback=None) -> Dict:
    """Full quality pipeline: research → extract → generate → edit → hard-checks → evaluate."""

    # Step 0: Research pass — design the IA before writing
    research = None
    try:
        from research_v2 import research_for_article
        if status_callback:
            status_callback("Scoping the article (research pass)...")
        research = research_for_article(
            api_key,
            cluster.get("consumer_question", ""),
            sources=pages or cluster.get("brief") or cluster.get("urls"),
            model=model,
        )
        if research and "error" in research:
            research = None  # fall through silently — generation still works
    except Exception:
        research = None

    # Step 1: Extract facts from source pages
    extracted_facts = ""
    if enable_extraction and pages:
        if status_callback:
            status_callback("Extracting key facts from {} source pages...".format(len(pages)))
        extracted_facts = extract_source_facts(api_key, pages, "gpt-4o-mini")

    # Step 2: Generate article (canon-driven when research is available)
    if status_callback:
        status_callback("Writing article with {}...".format(model))

    cluster_for_gen = dict(cluster)
    if extracted_facts:
        cluster_for_gen["_extracted_facts"] = extracted_facts
    result = generate_article(api_key, cluster_for_gen, pages, model, research=research)

    if not result or "error" in result:
        return result

    # Step 3: Editor pass (canon-aware)
    if enable_editor:
        if status_callback:
            status_callback("Running editor pass...")
        edited = editor_pass(api_key, json.dumps(result, ensure_ascii=False),
                             cluster["consumer_question"], model, research=research)
        if edited and "error" not in edited:
            result = edited

    # Step 3.4: Deterministic normaliser (footer extraction, box demotion, section cap)
    try:
        from content_rules import normalize_article
        if status_callback:
            status_callback("Normalising structure...")
        result = normalize_article(result)
    except Exception:
        pass

    # Step 3.5: Hard structural checks (run regardless of auto-eval)
    hard_issues: List[Dict] = []
    try:
        from content_rules import run_hard_checks
        hard_issues = run_hard_checks(result) or []
    except Exception:
        pass
    if hard_issues:
        if status_callback:
            status_callback("Hard checks: {} structural issue(s) flagged.".format(len(hard_issues)))
        # Auto-fix high-severity structural issues (callout adjacency, missing H1, etc.)
        try:
            import evaluation_v2 as _ev_hard
            high = [i for i in hard_issues if i.get("severity") == "high"][:3]
            for idx, issue in enumerate(high):
                if status_callback:
                    status_callback("Hard-fix {}/{}: {}".format(
                        idx + 1, len(high), issue.get("what", "")[:80]))
                result = _ev_hard.apply_fix(api_key, result, issue, full_article=result, model=model)
            # Re-run hard checks after fixes (informational)
            try:
                from content_rules import run_hard_checks as _rhc
                hard_issues = _rhc(result) or []
            except Exception:
                pass
        except Exception:
            pass

    # Step 4: Auto-evaluate
    if enable_auto_eval:
        if status_callback:
            status_callback("Evaluating article quality...")
        eval_result = _quick_evaluate(
            api_key, json.dumps(result, ensure_ascii=False),
            cluster["consumer_question"], cluster.get("urls", []), model)

        overall = eval_result.get("overall_score", 0) if isinstance(eval_result, dict) else 0
        if overall and overall < 3.5 and "error" not in eval_result:
            # Surgical fix loop — apply per-issue patches for high-severity issues, cap 3
            try:
                import evaluation_v2 as _ev
            except Exception:
                _ev = None

            if _ev is not None:
                top_issues = [i for i in eval_result.get("top_issues", [])
                              if (i.get("severity") == "high")][:3]
                for idx, issue in enumerate(top_issues):
                    if status_callback:
                        status_callback("Fix {}/{}: {}".format(
                            idx + 1, len(top_issues), issue.get("what", "")[:80]))
                    result = _ev.apply_fix(api_key, result, issue, full_article=result, model=model)

                # Re-evaluate after fixes
                if top_issues:
                    if status_callback:
                        status_callback("Re-evaluating after fixes...")
                    eval_result = _ev.run_evaluation(
                        api_key, json.dumps(result, ensure_ascii=False),
                        cluster.get("urls", []), cluster["consumer_question"], model)

        # Merge any remaining hard structural issues into top_issues so the
        # eval drawer surfaces them with Fix-this affordances.
        if hard_issues and isinstance(eval_result, dict) and "error" not in eval_result:
            existing = list(eval_result.get("top_issues", []))
            eval_result["top_issues"] = existing + hard_issues

        # Store eval data in result for display
        if eval_result and "error" not in eval_result:
            result["_eval_preview"] = eval_result

    return result


# ---------------------------------------------------------------------------
# HTML rendering (reuses existing templates)
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("html", "text", "description", "content", "summary"):
            val = content.get(key)
            if val and isinstance(val, str):
                return val
        for key in ("items", "paragraphs", "bullets", "points"):
            val = content.get(key)
            if val and isinstance(val, list):
                parts = []
                for item in val:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        parts.append(_extract_text(item))
                return "\n".join(parts)
        str_vals = [str(v) for v in content.values() if v]
        return " ".join(str_vals) if str_vals else ""
    if isinstance(content, list):
        return "\n".join(_extract_text(i) for i in content if i)
    return str(content)


def _extract_list(content, key: str) -> list:
    if isinstance(content, dict):
        val = content.get(key)
        if isinstance(val, list):
            return val
        # Try alternate keys
        for alt in ("items", "questions", "cards", "steps", "articles", "rows"):
            val = content.get(alt)
            if isinstance(val, list):
                return val
    if isinstance(content, list):
        return content
    return []


import re as _re


def _fix_markdown_bold(text: str) -> str:
    """Convert **markdown bold** to <strong>HTML bold</strong> if the AI ignored instructions."""
    if not text or "**" not in text:
        return text
    # Replace **text** with <strong>text</strong>
    return _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)


def _fix_content(text: str) -> str:
    """Fix common AI output issues: markdown bold, missing <p> tags."""
    if not text:
        return text
    text = _fix_markdown_bold(text)
    # If it's a plain string without any HTML tags, wrap in <p>
    if "<" not in text and len(text) > 50:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        text = "".join("<p>{}</p>".format(p) for p in paragraphs)
    return text


def transform_ai_response(raw: dict) -> dict:
    out = {}  # type: Dict

    classification = (raw.get("page_classification") or "informational").lower()
    out["page_type"] = classification
    out["layout_type"] = (raw.get("layout_type") or "explainer").lower().strip()

    raw_graph = raw.get("graph_data")
    out["graph_data"] = raw_graph if isinstance(raw_graph, list) else []

    for key in (
        "page_title", "meta_description", "canonical_url", "breadcrumb",
        "product_label", "h1", "subtitle", "author", "reviewer",
        "internal_links_footer", "suggested_slug", "source_urls",
        "quick_answer",
    ):
        if key in raw:
            out[key] = raw[key]

    sections = raw.get("sections", [])
    if not isinstance(sections, list):
        sections = []

    body_sections = []  # type: List[Dict]
    faqs = []  # type: List[Dict]
    qa_cards = []  # type: List[Dict]
    articles = []  # type: List[Dict]

    for section in sections:
        sec_type = (section.get("type") or "").lower()
        heading = section.get("heading") or ""
        content = section.get("content")

        if sec_type == "hero":
            if not out.get("h1") and heading:
                out["h1"] = heading
            text = _extract_text(content)
            if not out.get("subtitle") and text:
                out["subtitle"] = text

        elif sec_type == "qa":
            cards = _extract_list(content, "cards")
            for c in cards:
                if isinstance(c, dict):
                    qa_cards.append({
                        "question": c.get("question") or "",
                        "answers": c.get("answers") or [],
                        "cta_text": c.get("cta_text") or "Learn more",
                        "cta_url": c.get("cta_url") or "#",
                    })

        elif sec_type == "faq":
            items = _extract_list(content, "items")
            for item in items:
                if isinstance(item, dict):
                    raw_answer = item.get("answer") or item.get("a") or ""
                    faqs.append({
                        "question": item.get("question") or item.get("q") or "",
                        "answer": _fix_content(raw_answer),
                    })

        elif sec_type == "expert_tip":
            if isinstance(content, dict):
                out["expert_tip"] = {
                    "quote": content.get("quote") or "",
                    "name": content.get("name") or "",
                    "title": content.get("title") or "",
                }

        elif sec_type == "related_articles":
            items = _extract_list(content, "articles")
            for item in items:
                if isinstance(item, dict):
                    articles.append({
                        "title": item.get("title") or "",
                        "description": item.get("description") or "",
                        "url": item.get("url") or "#",
                    })

        elif sec_type == "cta":
            if isinstance(content, dict):
                out.setdefault("cta_heading", content.get("heading") or "")
                out.setdefault("cta_description", content.get("description") or "")
                out.setdefault("cta_button_text", content.get("button_text") or "Check Prices")
                out.setdefault("cta_button_url", content.get("button_url") or "#")

        elif sec_type in ("comparison", "table"):
            if isinstance(content, dict):
                rows = content.get("rows") or []
                if rows:
                    out["comparison"] = rows

        elif sec_type == "steps":
            steps_data = _extract_list(content, "steps")
            if steps_data:
                out["steps_renew"] = steps_data

        elif sec_type in ("callout_info", "callout_tip", "callout_warning"):
            text = ""
            label = "Note"
            callout_type = sec_type.replace("callout_", "")  # info, tip, warning
            if isinstance(content, dict):
                text = content.get("text", "")
                label = content.get("label", callout_type.title())
            elif isinstance(content, str):
                text = content
            if text:
                sec_entry = {"heading": heading}
                sec_entry["callout"] = _fix_content(text)
                sec_entry["callout_type"] = callout_type
                sec_entry["callout_label"] = label
                kt = section.get("key_takeaway")
                if kt and isinstance(kt, str):
                    sec_entry["key_takeaway"] = _fix_markdown_bold(kt.strip())
                body_sections.append(sec_entry)

        elif sec_type == "bullet_list":
            # bullet_list — ONLY extract bullets, never duplicate as content text
            sec_entry = {"heading": heading}  # type: Dict
            items = _extract_list(content, "items")
            if items:
                sec_entry["bullets"] = [_fix_markdown_bold(str(b)) for b in items]
            elif isinstance(content, str):
                # Fallback: if AI passed a string, wrap as content
                sec_entry["content"] = _fix_content(content)
            kt = section.get("key_takeaway")
            if kt and isinstance(kt, str) and kt.strip():
                sec_entry["key_takeaway"] = _fix_markdown_bold(kt.strip())
            if sec_entry.get("bullets") or sec_entry.get("content"):
                body_sections.append(sec_entry)

        else:
            # content_block and any other type
            sec_entry = {"heading": heading}  # type: Dict
            items = _extract_list(content, "items")
            if items:
                # Has items — treat as bullet-style, don't also extract text
                sec_entry["bullets"] = [_fix_markdown_bold(str(b)) for b in items]
            else:
                text = _extract_text(content)
                if text:
                    sec_entry["content"] = _fix_content(text)
            # Extract key_takeaway callout if present
            kt = section.get("key_takeaway")
            if kt and isinstance(kt, str) and kt.strip():
                sec_entry["key_takeaway"] = _fix_markdown_bold(kt.strip())
            # Only add if there's actual content
            if sec_entry.get("content") or sec_entry.get("bullets"):
                body_sections.append(sec_entry)

    out["body_sections"] = body_sections
    out["faqs"] = faqs
    out["qa_cards"] = qa_cards
    out["articles"] = articles

    # Generate TOC
    if body_sections:
        toc = []
        for i, sec in enumerate(body_sections):
            h = sec.get("heading", "")
            if h:
                toc.append({"id": "section-{}".format(i + 1), "text": h})
        out["toc"] = toc

    if not out.get("internal_links") and out.get("internal_links_footer"):
        out["internal_links"] = out["internal_links_footer"]

    return out


def render_html(result: dict) -> str:
    transformed = transform_ai_response(result)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
        undefined=jinja2.Undefined,
    )

    page_type = (transformed.get("page_type") or "informational").lower()
    template_name = TEMPLATE_MAP.get(page_type, FALLBACK_TEMPLATE)

    try:
        template = env.get_template(template_name)
    except jinja2.TemplateNotFound:
        template = env.get_template(FALLBACK_TEMPLATE)

    return template.render(**transformed)


# ---------------------------------------------------------------------------
# EEAT + SEO quality metrics (heuristic)
# ---------------------------------------------------------------------------

def compute_eeat_seo_metrics(result: dict) -> dict:
    """Compute heuristic EEAT signals and SEO quality markers from article JSON."""
    metrics = {}
    sections = result.get("sections", [])

    # Gather all content text for analysis
    all_text = ""
    for s in sections:
        all_text += _extract_text(s.get("content")) + " "

    # ---- EEAT Signals ----
    eeat = {}

    # Experience: specific data points (rupee amounts as proxy)
    rupee_count = len(_re.findall(r'₹[\d,]+', all_text))
    eeat["specific_data_points"] = rupee_count
    eeat["has_specific_examples"] = rupee_count >= 3

    # Expertise: expert tip, author, reviewer
    eeat["has_expert_tip"] = any(
        (s.get("type") or "").lower() == "expert_tip" for s in sections)
    author = result.get("author") or {}
    reviewer = result.get("reviewer") or {}
    eeat["has_author"] = bool(author.get("name"))
    eeat["has_reviewer"] = bool(reviewer.get("name"))
    eeat["author_name"] = author.get("name", "—")
    eeat["reviewer_name"] = reviewer.get("name", "—")

    # Authoritativeness: sources and internal links
    source_urls = result.get("source_urls", [])
    internal_links = result.get("internal_links_footer", [])
    eeat["source_count"] = len(source_urls)
    eeat["internal_links_count"] = len(internal_links)

    # Trustworthiness: key takeaways, FAQ, comparison
    eeat["key_takeaway_count"] = sum(
        1 for s in sections if s.get("key_takeaway"))
    eeat["has_faq"] = any(
        (s.get("type") or "").lower() == "faq" for s in sections)
    eeat["has_comparison"] = any(
        (s.get("type") or "").lower() in ("comparison", "table")
        for s in sections)

    # Score /10
    score = 0.0
    score += 1.5 if eeat["has_author"] else 0
    score += 1.0 if eeat["has_reviewer"] else 0
    score += 1.5 if eeat["has_expert_tip"] else 0
    score += 1.0 if eeat["has_specific_examples"] else 0
    score += 1.0 if eeat["has_faq"] else 0
    score += 1.0 if eeat["has_comparison"] else 0
    score += 1.0 if eeat["internal_links_count"] >= 3 else (
        0.5 if eeat["internal_links_count"] >= 1 else 0)
    score += 1.0 if eeat["key_takeaway_count"] >= 2 else (
        0.5 if eeat["key_takeaway_count"] >= 1 else 0)
    eeat["score"] = min(round(score, 1), 10.0)
    metrics["eeat"] = eeat

    # ---- SEO Markers ----
    seo = {}
    title = result.get("page_title", "")
    seo["title_length"] = len(title)
    seo["title_ok"] = 30 <= len(title) <= 65

    meta = result.get("meta_description", "")
    seo["meta_length"] = len(meta)
    seo["meta_ok"] = 120 <= len(meta) <= 160

    h2_list = [s.get("heading", "") for s in sections if s.get("heading")]
    seo["h2_count"] = len(h2_list)
    seo["h2_ok"] = len(h2_list) >= 5

    faq_count = 0
    for s in sections:
        if (s.get("type") or "").lower() == "faq":
            items = s.get("content", {})
            if isinstance(items, dict):
                faq_count = len(items.get("items", []))
    seo["faq_count"] = faq_count
    seo["faq_ok"] = faq_count >= 4

    seo["internal_links_count"] = len(internal_links)
    seo["internal_links_ok"] = len(internal_links) >= 3

    slug = result.get("suggested_slug", "")
    seo["slug"] = slug
    seo["slug_ok"] = bool(slug) and len(slug) <= 60 and "-" in slug

    seo["content_format"] = result.get("content_format", "—")
    seo["layout_type"] = result.get("layout_type", "—")
    metrics["seo"] = seo

    return metrics


# ---------------------------------------------------------------------------
# Infer secondary questions from cluster data
# ---------------------------------------------------------------------------

def _infer_secondary_questions(cluster: Dict) -> List[str]:
    """Generate secondary questions a reader might ask based on the cluster's
    consumer question and theme.  Uses simple heuristic patterns — no API call."""
    q = cluster.get("consumer_question", "").lower()
    theme = cluster.get("theme", "").lower()
    secondary = []

    # Cost / price questions
    if any(w in q for w in ["what", "how", "which", "buy", "get", "need"]):
        if "cost" not in q and "price" not in q and "premium" not in q:
            secondary.append("How much does {} cost in India?".format(theme or "this"))
    # Comparison questions
    if "difference" not in q and "vs" not in q and "compare" not in q:
        if "third" in q or "comprehensive" in q or "own damage" in q:
            secondary.append("What's the difference between third-party and comprehensive insurance?")
        else:
            secondary.append("Which {} option is best for me?".format(theme or "insurance"))
    # Process questions
    if "how to" not in q and "claim" not in q:
        secondary.append("How do I file a claim with Acko?")
    # Coverage questions
    if "cover" not in q and "include" not in q:
        secondary.append("What does {} typically cover?".format(theme or "car insurance"))
    # Requirements
    if "document" not in q and "require" not in q:
        secondary.append("What documents do I need for {}?".format(theme or "car insurance"))

    # Deduplicate and limit to 3
    seen = set()
    unique = []
    for s in secondary:
        key = s.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:3]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(page_title="Generate — Acko Content Studio", page_icon="●", layout="wide")

    # Theme import (local to avoid top-level sys.path issues)
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ui import apply_theme, sidebar as ui_sidebar, page_header, section_label  # noqa: E402

    apply_theme()
    ui_sidebar(current="generate")

    page_header(
        eyebrow="Step 3",
        title="Generate",
        meta="Write from clusters or briefs",
    )

    init_articles_db()

    # ---- Sidebar settings ----
    deployment_key = get_openai_key()
    with st.sidebar:
        st.markdown(
            '<div style="padding:18px 12px 8px;font-family:Inter,sans-serif;font-size:0.7rem;'
            'font-weight:600;letter-spacing:1.5px;color:#8d969e;text-transform:uppercase;">Settings</div>',
            unsafe_allow_html=True,
        )
        if deployment_key:
            api_key = deployment_key
            st.caption("API key active")
        else:
            api_key = st.text_input("OpenAI API key", type="password", placeholder="sk-...")
        model = st.selectbox("Model", MODELS, index=0, label_visibility="collapsed")

        st.markdown(
            '<div style="padding:18px 12px 4px;font-family:Inter,sans-serif;font-size:0.7rem;'
            'font-weight:600;letter-spacing:1.5px;color:#8d969e;text-transform:uppercase;">Quality pipeline</div>',
            unsafe_allow_html=True,
        )
        enable_extraction = st.checkbox("Smart source extraction", value=True,
                                        help="Pre-extract facts from source pages (faster, cleaner input)")
        enable_editor = st.checkbox("Editor pass", value=True,
                                    help="Self-edit pass to fix formatting and depth issues")
        enable_auto_eval = st.checkbox("Auto-evaluate", value=True,
                                       help="Score article and regenerate if below threshold")

    # ---- Load data ----
    clusters = load_clusters()
    articles = load_articles()

    if not clusters:
        st.warning("No clusters yet. Run **Crawl** then **Cluster** first.")
        return

    # ================================================================
    # STEP 1 — Select cluster
    # ================================================================
    section_label("1 · Pick a cluster")

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])
    with filter_col1:
        themes = sorted(set(c.get("theme", "") for c in clusters if c.get("theme")))
        theme_filter = st.selectbox("Theme", ["All themes"] + themes, index=0)
    with filter_col2:
        bl_filter = st.selectbox("Business line", ["All", "enterprise", "retail", "longtail"], index=0)
    with filter_col3:
        search_text = st.text_input("Search", placeholder="Search by question or theme...", label_visibility="collapsed")

    filtered = clusters
    if theme_filter != "All themes":
        filtered = [c for c in filtered if c.get("theme") == theme_filter]
    if bl_filter != "All":
        filtered = [c for c in filtered if c.get("business_line", "retail") == bl_filter]
    if search_text.strip():
        q = search_text.strip().lower()
        filtered = [c for c in filtered if q in c["consumer_question"].lower() or q in (c.get("theme") or "").lower()]

    st.caption("Showing {} of {} clusters".format(len(filtered), len(clusters)))

    if not filtered:
        st.warning("No clusters match your filters.")
        return

    _BL_ICONS = {"enterprise": "🏢", "retail": "👤", "longtail": "🔍"}
    cluster_options = {}
    for c in filtered:
        bl_icon = _BL_ICONS.get(c.get("business_line", "retail"), "")
        source = "brief" if c.get("input_type") == "brief" else "{} pages".format(len(c["urls"]))
        label = "{} [{}] {} ({})".format(bl_icon, c["theme"], c["consumer_question"][:65], source)
        cluster_options[label] = c

    selected_label = st.selectbox("Cluster", list(cluster_options.keys()), label_visibility="collapsed")
    selected_cluster = cluster_options[selected_label]

    # ---- Cluster context: two columns ----
    col_q, col_meta = st.columns([3, 2], gap="medium")

    with col_q:
        st.markdown("**Primary question**")
        st.info(selected_cluster["consumer_question"])
        # Use cluster secondary questions if available, else infer
        secondary_qs = selected_cluster.get("secondary_questions") or _infer_secondary_questions(selected_cluster)
        if secondary_qs:
            st.markdown("**Readers will also ask**")
            for sq in secondary_qs:
                st.caption("→ {}".format(sq))
        if selected_cluster.get("audience_persona"):
            st.caption("👤 **Audience:** {}".format(selected_cluster["audience_persona"]))
        if selected_cluster.get("search_trigger"):
            st.caption("🔍 **Search trigger:** {}".format(selected_cluster["search_trigger"]))

    with col_meta:
        m1, m2, m3 = st.columns(3)
        m1.metric("Pages", len(selected_cluster["urls"]))
        m2.metric("Theme", selected_cluster.get("theme", "—")[:12])
        m3.metric("Type", selected_cluster.get("page_group", "info")[:5])
        with st.expander("Source URLs"):
            for url in selected_cluster["urls"]:
                st.caption(url)

    # ================================================================
    # STEP 2 — Generate
    # ================================================================
    st.markdown("---")
    section_label("2 · Launch generation")

    # Dark launch bar — meta line above the primary button
    st.markdown(
        f'<div style="background:#0a0b13;color:#ffffff;border-radius:14px;'
        f'padding:20px 24px;margin:8px 0 12px;display:flex;align-items:center;'
        f'justify-content:space-between;gap:16px;">'
        f'<div>'
        f'<div style="font-family:Inter,sans-serif;font-weight:600;font-size:15px;'
        f'letter-spacing:-0.005em;">3-pass pipeline — extract · generate · editor · evaluate</div>'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:12px;'
        f'color:rgba(255,255,255,0.64);margin-top:4px;">~2 min · {model} · estimated cost $0.14</div>'
        f'</div>'
        f'<div style="font-family:Inter,sans-serif;font-size:12px;'
        f'color:rgba(255,255,255,0.52);">Click Generate below ↓</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    generate_btn = st.button("Generate article  →", type="primary", use_container_width=True)

    if generate_btn:
        if not api_key:
            st.error("Set your OpenAI API key in the sidebar.")
        else:
            _input_type = selected_cluster.get("input_type", "crawled")
            if _input_type in ("brief", "ref_url"):
                # Brief-based cluster — no crawl lookup needed
                pages = []
            else:
                with st.spinner("Loading source pages..."):
                    pages = get_cluster_page_data(selected_cluster["urls"])
                if not pages:
                    st.error("No crawled data for this cluster. Run the crawler first.")
                    st.stop()
            if pages is not None:
                status_box = st.empty()
                def _status(msg):
                    status_box.info(msg)

                try:
                    result = generate_with_quality(
                        api_key, selected_cluster, pages, model,
                        enable_extraction=enable_extraction,
                        enable_editor=enable_editor,
                        enable_auto_eval=enable_auto_eval,
                        status_callback=_status,
                    )
                except Exception as e:
                    st.error("API error: {}".format(e))
                    result = None

                status_box.empty()

                if result and "error" in result:
                    st.error(result["error"])
                    if "raw_response" in result:
                        with st.expander("Raw response"):
                            st.code(result["raw_response"])
                elif result:
                    html_content = render_html(result)
                    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
                    slug = result.get("suggested_slug") or "article-{}".format(selected_cluster["cluster_id"])

                    article_id = save_article(
                        cluster_id=selected_cluster["cluster_id"],
                        question=selected_cluster["consumer_question"],
                        result=result, html=html_content,
                        source_urls=selected_cluster["urls"], model=model,
                        business_line=selected_cluster.get("business_line", "retail"))

                    # Persist EEAT + SEO/GEO eval if it was produced during generation
                    _eval_preview = result.get("_eval_preview")
                    if _eval_preview and "overall_score" in _eval_preview:
                        try:
                            update_article_eval(article_id, _eval_preview)
                        except Exception:
                            pass

                    html_path = ARTICLES_DIR / "{}.html".format(slug)
                    html_path.write_text(html_content, encoding="utf-8")

                    st.session_state["last_result"] = result
                    st.session_state["last_html"] = html_content
                    st.session_state["last_slug"] = slug
                    st.session_state["last_article_id"] = article_id
                    st.session_state["last_cluster"] = selected_cluster

    # ================================================================
    # STEP 3 — Results (only if we have an article)
    # ================================================================
    result = st.session_state.get("last_result")
    html_content = st.session_state.get("last_html")

    if result and html_content:
        st.markdown("---")
        section_label("3 · Results")
        st.success("Article #{} generated".format(st.session_state.get("last_article_id", "")))

        # ---- Two-column layout: main stats + EEAT/SEO panel ----
        col_main, col_panel = st.columns([3, 2], gap="large")

        sections = result.get("sections", [])
        h2_list = [s.get("heading", "") for s in sections if s.get("heading")]

        with col_main:
            # Quick stats
            s1, s2, s3 = st.columns(3)
            s1.metric("Sections", len(sections))
            s2.metric("Format", result.get("content_format", "—"))
            s3.metric("Type", result.get("page_classification", "—"))

            # Article structure
            if h2_list:
                with st.expander("Article structure ({} sections)".format(len(h2_list)), expanded=True):
                    for i, h in enumerate(h2_list):
                        st.markdown("{}. {}".format(i + 1, h))

            # SEO metadata (compact)
            with st.expander("SEO metadata"):
                st.markdown("**Title:** {}".format(result.get("page_title", "—")))
                st.markdown("**Meta:** {}".format(result.get("meta_description", "—")))
                st.markdown("**Slug:** /{}".format(result.get("suggested_slug", "—")))

        with col_panel:
            metrics = compute_eeat_seo_metrics(result)
            eeat = metrics["eeat"]
            seo = metrics["seo"]

            # ---- EEAT Panel ----
            st.markdown("#### EEAT Signals")
            st.metric("Score", "{}/10".format(eeat["score"]))

            st.markdown("**Experience**")
            st.caption("{} Specific data points: {}".format(
                "✅" if eeat["has_specific_examples"] else "⚠️",
                eeat["specific_data_points"]))

            st.markdown("**Expertise**")
            st.caption("{} Expert tip".format(
                "✅" if eeat["has_expert_tip"] else "❌"))
            st.caption("{} Author: {}".format(
                "✅" if eeat["has_author"] else "❌",
                eeat["author_name"]))
            st.caption("{} Reviewer: {}".format(
                "✅" if eeat["has_reviewer"] else "❌",
                eeat["reviewer_name"]))

            st.markdown("**Authoritativeness**")
            st.caption("{} Source pages: {}".format(
                "✅" if eeat["source_count"] >= 2 else "⚠️",
                eeat["source_count"]))
            st.caption("{} Internal links: {}".format(
                "✅" if eeat["internal_links_count"] >= 3 else "⚠️",
                eeat["internal_links_count"]))

            st.markdown("**Trustworthiness**")
            st.caption("{} Key takeaways: {}".format(
                "✅" if eeat["key_takeaway_count"] >= 2 else "⚠️",
                eeat["key_takeaway_count"]))
            st.caption("{} FAQ section".format(
                "✅" if eeat["has_faq"] else "❌"))
            st.caption("{} Comparison table".format(
                "✅" if eeat["has_comparison"] else "❌"))

            st.divider()

            # ---- SEO Markers ----
            st.markdown("#### SEO Markers")
            st.caption("{} Title ({} chars) {}".format(
                "✅" if seo["title_ok"] else "⚠️",
                seo["title_length"],
                "" if seo["title_ok"] else "— aim for 30-65"))
            st.caption("{} Meta ({} chars) {}".format(
                "✅" if seo["meta_ok"] else "⚠️",
                seo["meta_length"],
                "" if seo["meta_ok"] else "— aim for 120-160"))
            st.caption("{} H2 headings: {}".format(
                "✅" if seo["h2_ok"] else "⚠️", seo["h2_count"]))
            st.caption("{} FAQs: {}".format(
                "✅" if seo["faq_ok"] else "⚠️", seo["faq_count"]))
            st.caption("{} Internal links: {}".format(
                "✅" if seo["internal_links_ok"] else "⚠️",
                seo["internal_links_count"]))
            st.caption("{} Slug: /{}".format(
                "✅" if seo["slug_ok"] else "⚠️", seo["slug"]))

            # ---- Auto-eval preview (full 6-dimension breakdown) ----
            eval_preview = result.get("_eval_preview")
            if eval_preview and "weighted_average" in eval_preview:
                st.divider()
                avg = eval_preview["weighted_average"]
                verdict = eval_preview.get("verdict", "unknown")
                verdict_icon = {"approve": "✅", "conditional": "🟡", "reject": "❌"}.get(verdict, "❓")

                st.markdown("#### Northstar Quality Score")
                st.metric("Overall", "{} {:.1f}/5 — {}".format(verdict_icon, avg, verdict.upper()))

                scores = eval_preview.get("scores", {})
                with st.expander("📊 Dimension Breakdown", expanded=True):
                    for dim_key, dim_info in scores.items():
                        if not isinstance(dim_info, dict):
                            continue
                        score = dim_info.get("score", 0)
                        reasoning = dim_info.get("reasoning", "")
                        dim_label = dim_key.replace("_", " ").title()
                        bar_icon = "🟢" if score >= 4 else "🟡" if score >= 3 else "🔴"
                        st.markdown("{} **{}** — {}/5".format(bar_icon, dim_label, score))
                        st.progress(score / 5.0)
                        if reasoning:
                            st.caption(reasoning)

                col_str, col_imp = st.columns(2)
                with col_str:
                    strengths = eval_preview.get("top_strengths", [])
                    if strengths:
                        with st.expander("✅ Strengths"):
                            for s in strengths:
                                st.markdown("- {}".format(s))
                with col_imp:
                    issues = eval_preview.get("top_issues", [])
                    improvements = eval_preview.get("suggested_improvements", [])
                    if issues or improvements:
                        with st.expander("⚠️ Issues & Improvements"):
                            for issue in issues:
                                st.markdown("- ⚠️ {}".format(issue))
                            for imp in improvements:
                                st.markdown("- 💡 {}".format(imp))

        # ---- Preview tabs ----
        st.markdown("---")
        tab_preview, tab_before, tab_json = st.tabs(["✨ Article Preview", "📄 Source Pages (Before)", "📋 Raw JSON"])

        with tab_preview:
            components.html(html_content, height=800, scrolling=True)

        with tab_before:
            last_cluster = st.session_state.get("last_cluster", selected_cluster)
            for i, url in enumerate(last_cluster.get("urls", [])):
                pd_item = get_page_data(url)
                if pd_item:
                    with st.expander("{} — {}".format(
                        pd_item.get("h1", "")[:60] or "Page {}".format(i + 1),
                        url.split("/")[-2] if "/" in url else url
                    ), expanded=(i == 0)):
                        st.caption(url)
                        st.markdown("**{}**".format(pd_item.get("title", "")))
                        body = pd_item.get("body_text", "")
                        if body:
                            st.text_area("Content", body[:3000], height=180, disabled=True, key="src_{}".format(i))

        with tab_json:
            st.json(result)

        # ---- EEAT + SEO/GEO drawer ----
        _eval_v2 = result.get("_eval_preview")
        if _eval_v2 and isinstance(_eval_v2, dict) and "overall_score" in _eval_v2:
            st.markdown("---")
            section_label("Quality · EEAT + SEO/GEO")
            try:
                import evaluation_v2 as _ev_mod
                _aid = st.session_state.get("last_article_id", "new")

                def _on_fix(issue):
                    api_key_local = get_openai_key()
                    updated = _ev_mod.apply_fix(api_key_local, result, issue,
                                                full_article=result, model=model)
                    st.session_state["last_result"] = updated
                    st.session_state["last_html"] = render_html(updated)
                    if isinstance(_aid, int):
                        update_article(_aid, updated, st.session_state["last_html"])
                    st.rerun()

                _ev_mod.render_eval_drawer(_eval_v2, _aid, on_fix_callback=_on_fix)
            except Exception as _e:
                st.warning("Eval drawer error: {}".format(_e))

        # ---- Downloads ----
        slug = st.session_state.get("last_slug", "article")
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button("📄 Download HTML", html_content,
                               file_name="{}.html".format(slug), mime="text/html", key="dl_h")
        with dl2:
            st.download_button("📋 Download JSON", json.dumps(result, indent=2, ensure_ascii=False),
                               file_name="{}.json".format(slug), mime="application/json", key="dl_j")

    # ================================================================
    # Library (at the bottom, collapsed)
    # ================================================================
    if articles:
        st.markdown("---")
        with st.expander("📚 Article Library ({} articles)".format(len(articles))):
            for art in articles:
                score_txt = "⭐ {:.1f}".format(art["eval_score"]) if art.get("eval_score") else ""
                status_icon = {"draft": "📝", "approved": "✅", "published": "🚀", "rejected": "❌"}.get(
                    art.get("status", "draft"), "📝")
                st.markdown("{} **{}** {} [{}]".format(
                    status_icon, art["consumer_question"][:60], score_txt, art.get("status", "draft")))


main()
