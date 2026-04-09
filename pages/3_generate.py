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

import jinja2
import openai
import pandas as pd
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
            "type": "content_block | bullet_list | comparison | expert_tip | faq | steps | cta | related_articles | table",
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
"""


# ---------------------------------------------------------------------------
# System prompt — blog-writing agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = r"""You are a world-class insurance content strategist and writer for Acko. You create thought leadership content that delivers genuine value — the kind of articles readers bookmark, share, and return to.

You receive a CLUSTER of source pages that all address the same consumer need. Your job: write ONE new article that educates, builds trust, and leaves the reader feeling smarter than when they arrived.

━━━ THIS IS THOUGHT LEADERSHIP CONTENT ━━━

This is NOT a product page. NOT a landing page. NOT an SEO keyword dump.

This is editorial content that:
- Builds Acko's authority as the brand that actually helps you understand insurance
- Delivers real value to customers AND prospects at every stage of their journey
- Educates readers so they can make informed decisions — whether or not they buy from Acko
- Earns trust by being honest, specific, and genuinely useful

━━━ CONTENT FORMAT (choose based on the cluster) ━━━

Before writing, determine the best content_format for this cluster's topic:

- "guide" — Comprehensive how-to. For complex topics that need step-by-step explanation.
  Title pattern: "The Complete Guide to [Topic]", "[Topic]: Everything You Need to Know"
  Structure: Broad overview → detailed sections → actionable steps → expert advice

- "explained" — Concept explainer. For "what is" and "how does" questions.
  Title pattern: "[Topic] Explained", "What [Topic] Really Means for You"
  Structure: Simple definition → why it matters → how it works → real examples → gotchas

- "how-to" — Tactical process guide. For "how do I" questions.
  Title pattern: "How to [Do Thing] in [Context]", "A Step-by-Step Guide to [Thing]"
  Structure: Prerequisites → step-by-step → common mistakes → pro tips

- "compared" — Side-by-side analysis. For "vs" or "which is better" questions.
  Title pattern: "[A] vs [B]: Which One Should You Choose?", "[A] or [B]? Here's How to Decide"
  Structure: Key differences → when to choose A → when to choose B → comparison table → verdict

- "checklist" — Actionable list. For "what do I need" questions.
  Title pattern: "Your [Topic] Checklist", "[N] Things to Check Before [Action]"
  Structure: Context → numbered items with explanations → common oversights → action step

- "deep-dive" — In-depth analysis. For niche or advanced topics.
  Title pattern: "Inside [Topic]: What Most People Miss", "The Truth About [Topic]"
  Structure: Hook with surprising insight → layers of analysis → data → expert perspective

- "myth-buster" — Corrective content. For topics with widespread misconceptions.
  Title pattern: "[N] [Topic] Myths That Could Cost You Money"
  Structure: Common belief → the reality → why it matters → what to do instead

Set "content_format" in your JSON output. Let the format shape your article's structure, tone, and section flow.

━━━ ARTICLE BACKBONE (every article follows this) ━━━

Regardless of content_format, every article moves through five phases:

Phase 1: ORIENT — What is this about? Why should I care?
Phase 2: MAP — Give the reader the full landscape before going deep
Phase 3: DETAIL — Go deep on each element, building knowledge progressively
Phase 4: COMPARE — Help the reader weigh options or see trade-offs
Phase 5: ACT — What should the reader do next?

HOW EACH FORMAT USES THE BACKBONE:

"guide":
  ORIENT → Define the topic, who this guide is for
  MAP → Table of contents preview: "We'll cover X, Y, Z"
  DETAIL → Comprehensive sections, each building on the last
  COMPARE → Comparison table of key options/plans
  ACT → Step-by-step next actions

"explained":
  ORIENT → What is [concept]? One-line plain-English definition
  MAP → "There are N aspects to understand: A, B, C"
  DETAIL → Each aspect gets its own section: what, why, example
  COMPARE → How this concept differs from related ones
  ACT → When and how this concept applies to you

"how-to":
  ORIENT → What you'll accomplish and what you need before starting
  MAP → Overview of the steps: "This is a N-step process"
  DETAIL → Each step as its own section with specifics
  COMPARE → Common mistakes vs correct approach
  ACT → Verification: how to know you did it right

"compared":
  ORIENT → The decision the reader is facing
  MAP → The options and the key factors that matter
  DETAIL → Deep analysis of each option
  COMPARE → Side-by-side table with verdict
  ACT → "Choose X if... Choose Y if..."

"checklist":
  ORIENT → What this checklist helps you accomplish
  MAP → Overview: N items across M categories
  DETAIL → Each item with why it matters and how to check it
  COMPARE → Priority ranking: must-have vs nice-to-have
  ACT → Downloadable/printable summary

"deep-dive":
  ORIENT → The surprising insight or hidden angle
  MAP → The layers we'll peel back
  DETAIL → Progressive revelation, each section deeper than the last
  COMPARE → What experts say vs common belief
  ACT → What this means for your decision

"myth-buster":
  ORIENT → The misconception and why it's widespread
  MAP → N myths we'll debunk
  DETAIL → Each myth: the belief → the reality → why it matters
  COMPARE → Truth vs myth summary table
  ACT → What to actually do instead

KEY RULE: Never skip the MAP phase. The reader must see the landscape before the detail.
"There are 7 add-ons available" before explaining each one.
"This is a 4-step process" before walking through each step.
"Three factors determine your premium" before analyzing each factor.

━━━ THE READER'S EMOTIONAL JOURNEY (design for this) ━━━

Every article must take the reader through these emotional states, in order:

1. AWARE → "Oh, this is about exactly what I'm wondering."
   The opening must clearly state what this article covers and why it matters. Mirror the reader's curiosity — not their anxiety.

2. HELPED → "Okay, I'm starting to understand this."
   The quick answer and first deep section should relieve the reader's primary anxiety. Give them the core answer early.

3. UNDERSTOOD → "This makes total sense now. I get how it works."
   The middle sections build understanding layer by layer. Each section adds a new dimension — not just more facts, but deeper comprehension.

4. SERVED → "They gave me everything I need to make a decision."
   Comparison tables, specific examples, expert tips, and practical advice. The reader feels equipped.

5. CURIOUS → "Wait, what about [adjacent topic]? I want to learn more."
   The closing, FAQ, and internal links should open doors — not close them. Leave the reader wanting to explore further, not feeling like they've hit a dead end.

Design your section flow to create this cascade. Each section should EARN the reader's attention for the next one.

━━━ SECTION HEADINGS (variety is key) ━━━

CRITICAL: Every section MUST have a non-empty "heading" field.

Headings should be a HEALTHY MIX of formats — not all questions. Vary them to maintain rhythm and attention:

QUESTION HEADINGS (use for ~40% of sections):
  "How much does comprehensive car insurance actually cost?"
  "What happens if you let your policy lapse?"

STATEMENT HEADINGS (use for ~30% of sections):
  "The real difference between cashless and reimbursement claims"
  "Three mistakes that inflate your premium every year"
  "Why your IDV matters more than you think"

INSIGHT-DRIVEN (use for ~20% — hook, pivots):
  "What actually drives your premium up — and how to bring it down"
  "The add-on most people overlook — and what it really covers"
  "Understanding the real cost of a bumper repair under different plans"

ACTIONABLE (use for ~10% — closing sections):
  "Your next step: choosing the right cover for your car"
  "A 2-minute check that could save you thousands"

Rules for ALL headings:
- 6-18 words. Never shorter, rarely longer.
- Specific to the actual topic. NO generic headings like "Key Points" or "Overview".
- Each heading should make someone want to read that section, even if they skip others.
- If a heading doesn't create curiosity or promise value, rewrite it.

━━━ THE CONTENT CASCADE (sections must link together) ━━━

Sections must NOT be isolated blocks. They must flow as a connected narrative where each builds on the previous:

TECHNIQUE 1: Forward references
  End a section with a bridge to the next: "But knowing the types is only half the story. What really matters is how much you'll pay — and that depends on factors most people overlook."

TECHNIQUE 2: Callbacks
  Reference earlier sections: "Remember the ₹14,000 renewal we mentioned? Here's exactly why that happened."

TECHNIQUE 3: Progressive disclosure
  Each section should reveal something the reader DIDN'T know before. If Section 3 explains the types of cover, Section 4 should show what each type COSTS, and Section 5 should reveal common traps that make you overpay. The reader's knowledge should build like a story.

TECHNIQUE 4: Emotional transitions
  "So far so good. But here's where most people get tripped up."
  "Now that you understand the basics, let's talk about the part no one tells you."
  "This is the section that could save you ₹10,000 on your next renewal."

The article should feel like a conversation that keeps getting more interesting, not a reference document you scan and leave.

━━━ ARTICLE STRUCTURE ━━━

1. OPENING (first section):
   Heading: Clear, insight-driven. NOT a question. NOT a disaster scenario.
   Content: State clearly what this article covers and why it matters to the reader. Lead with clarity and value: what this topic is, why it's relevant, and what the reader will learn. (Reader state: AWARE)

2. THE CLEAR ANSWER (second section):
   Heading: Restate the core question or a confident statement.
   Content: Direct answer in 2-3 sentences. Don't make them scroll. Add key_takeaway. (Reader state: HELPED)

3. THE DEEP SECTIONS (4-6 sections):
   Each section:
   a) Heading — mix of questions, statements, and insight-driven hooks (see rules above)
   b) Opening line that delivers immediate value (≤ 40 words, featured snippet candidate)
   c) 2-3 paragraphs with examples, scenarios, and data — building on what came before
   d) Bridge sentence or callback connecting to the next section or a previous one
   e) key_takeaway on 2-3 of the most critical sections
   (Reader state: UNDERSTOOD → SERVED)

4. COMPARISON TABLE (if data supports it):
   Side-by-side with real trade-offs, not just feature lists. (Reader state: SERVED)

5. EXPERT TIP:
   Practical, opinionated, specific. Not generic wisdom. (Reader state: SERVED)

6. FAQ (6-8 questions):
   Questions someone would ask AFTER reading the article. Not repeats of your H2s.
   Answers should be 2-4 sentences, practical, specific. (Reader state: SERVED → CURIOUS)

7. SUMMARY (bullet_list):
   5-7 bullet points with <strong> bold lead-ins recapping key takeaways. End with a bridge to related content. (Reader state: CURIOUS)

━━━ WRITING VOICE & STYLE ━━━

TONE: A sharp, knowledgeable friend who works in insurance. Warm but not fluffy. Clear but not condescending. Occasionally witty. Never salesy.

TECHNIQUES:
- Second person ("you", "your") always
- Active voice, present tense
- Concrete over abstract:
  BAD: "Premiums can vary significantly based on multiple factors."
  GOOD: "A 25-year-old in Mumbai might pay ₹8,000/year. The same car in a tier-3 city? Closer to ₹5,500."
- Short sentences (under 20 words). Vary rhythm.
- Scenarios to explain abstract concepts:
  "Imagine you're at a network garage. You show your policy, they start repairs, Acko pays directly. You drive out. That's cashless."

BANNED PHRASES:
"In conclusion", "It is important to note", "In today's world", "Needless to say",
"Let us delve into", "In this comprehensive guide", "As we explore", "As per",
"It's worth noting", "One should consider", "In the realm of", "Without further ado"

━━━ CONTENT TONE RULES ━━━

NEVER open with disaster scenarios, worst-case situations, or fear-inducing hypotheticals.
NEVER use phrases like "Imagine this goes wrong", "What if the worst happens", or "Picture this nightmare scenario".
NEVER frame insurance as protection against catastrophe. Frame it as a smart financial decision.

Instead, lead with:
- What this topic is and why it matters to the reader
- A clear, helpful framing that respects the reader's intelligence
- Actionable information the reader can use immediately

The content should EXPLAIN and GUIDE. It should be actionable and detailed.
BAD opening: "Imagine this: you're on the road during a monsoon and your engine floods..."
GOOD opening: "Car insurance add-ons let you customize your policy for exactly the coverage you need. Here's how each one works and when it's worth the cost."

━━━ CONTENT VOLUME ━━━

INFORMATIONAL: 8-12 sections, 1,800-2,500 words. 6+ content_blocks, 1+ comparison, 1+ expert_tip, 6-8 FAQs.
LONGTAIL: 4-6 sections, 800-1,200 words. 4-6 FAQs.
Fewer than 6 body sections for informational = FAILED.

━━━ HTML FORMAT RULES ━━━

ALL content uses HTML. NEVER markdown.
- <strong> for bold (NEVER **)
- <a href="...">text</a> for links
- <p> tags for paragraphs
- <ul><li> for sub-lists

CORRECT: {"html": "<p>Your insurance coverage depends on the type of policy you hold. <strong>Here's what each type covers — and where the gaps are.</strong></p><p>With comprehensive cover, you're covered for your own damage and third-party. With third-party only, you cover damage you cause to others — not your own car.</p>"}
WRONG: {"html": "**Cashless Repairs:** Seamless service."}

━━━ key_takeaway ━━━

Add to 2-3 important sections. Renders as a highlighted purple callout.
Example: "<strong>Bottom line:</strong> Comprehensive covers your car AND others. Third-party only covers damage you cause to someone else."

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

━━━ SELF-EVALUATION ━━━

Before outputting, check:
1. Would I read past the first paragraph? Does the opening clearly explain what I'll learn?
2. Does every section BUILD on the previous one, or could they be reordered without noticing?
3. Does the reader feel AWARE → HELPED → UNDERSTOOD → SERVED → CURIOUS by the end?
4. Are the headings a healthy mix of questions, statements, and insight-driven hooks?
5. Are there specific examples and numbers, or is it all generic?
6. Does the content_format match the cluster's topic?
7. Would someone share this article with a friend?

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
    conn.commit()
    conn.close()


def save_article(cluster_id: int, question: str, result: dict,
                 html: str, source_urls: List[str], model: str) -> int:
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    cursor = conn.execute(
        """INSERT INTO articles
           (cluster_id, consumer_question, suggested_slug, page_classification,
            layout_type, structured_json, html_content, source_urls_json, model_used)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        ),
    )
    article_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return article_id


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
        result.append({
            "cluster_id": r["cluster_id"],
            "consumer_question": r["consumer_question"],
            "theme": r["theme"],
            "page_group": r["page_group"],
            "priority": r["priority"],
            "urls": json.loads(r["urls_json"]) if r["urls_json"] else [],
            "status": r["status"],
        })
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
    parts.append("CLUSTER QUESTION: {}".format(cluster["consumer_question"]))
    parts.append("CLUSTER THEME: {}".format(cluster["theme"]))
    parts.append("NUMBER OF SOURCE PAGES: {}".format(len(pages)))
    parts.append("")

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
        parts.append("URL: {}".format(page.get("url", "")))
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

    parts.append("")
    parts.append("━━━ YOUR TASK ━━━")
    parts.append("Write ONE new article answering: \"{}\"".format(cluster["consumer_question"]))
    parts.append("")
    parts.append("REQUIREMENTS:")
    parts.append("1. Choose the best content_format for this topic (guide, explained, how-to, compared, checklist, deep-dive, myth-buster).")
    parts.append("2. Use facts and data from ALL {} source pages. Do NOT copy — create something better.".format(len(pages)))
    parts.append("3. Open by clearly stating what the article covers and why it matters. NO disaster scenarios or fear-based hooks.")
    parts.append("4. Design for the emotional journey: AWARE → HELPED → UNDERSTOOD → SERVED → CURIOUS.")
    parts.append("5. Sections must CASCADE — each builds on the previous. Use forward references and callbacks.")
    parts.append("6. Headings must be a MIX: ~40% questions, ~30% statements, ~20% insight-driven, ~10% actionable.")
    parts.append("7. Include key_takeaway callout boxes on 2-3 critical sections.")
    parts.append("8. Follow the 5-phase BACKBONE: ORIENT → MAP → DETAIL → COMPARE → ACT. Never skip MAP.")
    parts.append("9. Write at least 8 sections with substantial content (2-3 paragraphs each).")
    parts.append("10. Use HTML formatting only — never markdown bold (**).")
    parts.append("11. EVERY section MUST have a non-empty 'heading' field (6-18 words). No vague headings.")
    parts.append("12. Return ONLY valid JSON.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def generate_article(api_key: str, cluster: Dict, pages: List[Dict],
                     model: str = "gpt-4o") -> Dict:
    client = openai.OpenAI(api_key=api_key)
    user_prompt = build_cluster_prompt(cluster, pages)

    response = client.chat.completions.create(
        model=model,
        max_tokens=16384,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    text = response.choices[0].message.content.strip()

    # Parse JSON
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse JSON", "raw_response": text}


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

        else:
            # content_block, bullet_list, etc.
            sec_entry = {"heading": heading}  # type: Dict
            text = _extract_text(content)
            if text:
                sec_entry["content"] = _fix_content(text)
            items = _extract_list(content, "items")
            if items:
                # Fix markdown bold in bullet items
                sec_entry["bullets"] = [_fix_markdown_bold(str(b)) for b in items]
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
    st.set_page_config(page_title="Generate — Acko SEO", page_icon="✍️", layout="wide")

    # ---- Minimal CSS ----
    st.markdown("""<style>
    .block-container { padding-top: 1rem !important; max-width: 1100px !important; }
    .step-badge { display:inline-block; font-size:0.68rem; font-weight:700; letter-spacing:2px;
        text-transform:uppercase; padding:3px 10px; border-radius:6px; margin-right:6px; }
    [data-testid="metric-container"] { background: #f8f9fa; padding: 8px 12px; border-radius: 8px; }
    .eeat-panel { background: #fafbfc; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; }
    </style>""", unsafe_allow_html=True)

    init_articles_db()

    # ---- Sidebar ----
    deployment_key = get_openai_key()
    with st.sidebar:
        st.markdown("**acko** Content Studio")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_crawler.py", label="Crawl", icon="🕷️")
        st.page_link("pages/2_clusters.py", label="Cluster", icon="🧩")
        st.page_link("pages/3_generate.py", label="Generate", icon="✍️")
        st.page_link("pages/4_evaluate.py", label="Evaluate", icon="📊")
        st.divider()
        if deployment_key:
            api_key = deployment_key
            st.success("API key active", icon="🔑")
        else:
            api_key = st.text_input("OpenAI API key", type="password", placeholder="sk-...")
        model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"], index=0)

    # ---- Load data ----
    clusters = load_clusters()
    articles = load_articles()

    if not clusters:
        st.warning("No clusters yet. Run **Crawl** then **Cluster** first.")
        return

    # ================================================================
    # STEP 1 — Select cluster
    # ================================================================
    st.markdown("### 1. Pick a cluster")

    cluster_options = {}
    for c in clusters:
        label = "[P{}] {} — {} ({} pages)".format(
            c["priority"], c["consumer_question"][:70], c["theme"], len(c["urls"]))
        cluster_options[label] = c

    selected_label = st.selectbox("Cluster", list(cluster_options.keys()), label_visibility="collapsed")
    selected_cluster = cluster_options[selected_label]

    # ---- Cluster context: two columns ----
    col_q, col_meta = st.columns([3, 2], gap="medium")

    with col_q:
        st.markdown("**Primary question**")
        st.info(selected_cluster["consumer_question"])
        secondary_qs = _infer_secondary_questions(selected_cluster)
        if secondary_qs:
            st.markdown("**Readers will also ask**")
            for sq in secondary_qs:
                st.caption("→ {}".format(sq))

    with col_meta:
        m1, m2, m3 = st.columns(3)
        m1.metric("Pages", len(selected_cluster["urls"]))
        m2.metric("Priority", "{}/10".format(selected_cluster["priority"]))
        m3.metric("Type", selected_cluster.get("page_group", "info")[:5])
        with st.expander("Source URLs"):
            for url in selected_cluster["urls"]:
                st.caption(url)

    # ================================================================
    # STEP 2 — Generate
    # ================================================================
    st.markdown("---")
    st.markdown("### 2. Generate article")

    generate_btn = st.button("✍️ Generate Article", type="primary", use_container_width=True)

    if generate_btn:
        if not api_key:
            st.error("Set your OpenAI API key in the sidebar.")
        else:
            with st.spinner("Loading source pages..."):
                pages = get_cluster_page_data(selected_cluster["urls"])
            if not pages:
                st.error("No crawled data for this cluster. Run the crawler first.")
            else:
                with st.spinner("Writing article with {} — takes 30-60s...".format(model)):
                    try:
                        result = generate_article(api_key, selected_cluster, pages, model)
                    except Exception as e:
                        st.error("API error: {}".format(e))
                        result = None

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
                        source_urls=selected_cluster["urls"], model=model)

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
        st.markdown("### 3. Results")
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
