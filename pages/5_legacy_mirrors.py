"""
Phase 3 — Adaptive Mirror Page Generator
==========================================
Reads crawled page data from SQLite, classifies the page type, sends it to
Claude to restructure into a FLEXIBLE section-based JSON schema (adapting to
whatever the original content actually contains), renders HTML via Jinja2
template, and provides preview + download.

Key design principle: the Final.pdf design is a VISUAL GUIDELINE (colors,
typography, card styles) — NOT a content template. The AI restructures the
original crawled content using the visual language, only creating sections
that the source content supports.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

import openai
import jinja2
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "crawl_state.db"
REGEN_DB_PATH = PROJECT_ROOT / "regenerated_content.db"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
TEMPLATE_FILE = "acko_page.html"  # fallback
TEMPLATE_MAP = {
    "transactional": "transactional.html",
    "informational": "informational.html",
    "longtail": "longtail.html",
}
MIRROR_DIR = PROJECT_ROOT / "mirror_pages"


def get_deployment_openai_api_key() -> str:
    """API key from the host: env var or Streamlit secrets (no UI paste required when hosted)."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        sec = st.secrets["OPENAI_API_KEY"]
        return str(sec).strip() if sec else ""
    except Exception:
        return ""


# All section types the template supports
ALL_SECTION_TYPES = [
    "hero", "qa", "steps", "comparison", "expert_tip",
    "faq", "content_block", "bullet_list", "cta",
    "related_articles", "table",
]

# ---------------------------------------------------------------------------
# JSON schema description for the AI prompt
# ---------------------------------------------------------------------------

MIRROR_JSON_SCHEMA = r"""{
    "page_classification": "transactional | informational | longtail",
    "layout_type": "explainer | listicle | how-to | essay (informational pages only — omit for transactional/longtail)",
    "page_title": "str - SEO optimized title tag",
    "meta_description": "str - 155 char meta description",
    "canonical_url": "str - from crawled data",
    "breadcrumb": [{"text": "str", "url": "str"}],
    "product_label": "str - short uppercase label, e.g. CAR INSURANCE, HEALTH INSURANCE, BIKE INSURANCE",
    "h1": "str - conversational H1",
    "subtitle": "str - benefit-focused subtitle",
    "author": {"name": "str", "title": "str"},
    "reviewer": {"name": "str", "title": "str"},
    "sections": [
        {
            "type": "hero | qa | steps | comparison | expert_tip | faq | content_block | bullet_list | cta | related_articles | table",
            "heading": "str or null - H2 heading for the section, use question-format for AEO",
            "content": "varies by type — see SECTION CONTENT SHAPES below"
        }
    ],
    "graph_data": [
        {
            "title": "str - chart title shown above the chart",
            "type": "bar | line | pie",
            "labels": ["str"],
            "values": [0],
            "unit": "str or null - e.g. %, ₹, years",
            "source": "str or null - data source attribution"
        }
    ],
    "internal_links_footer": [{"href": "str", "text": "str"}]
}

SECTION CONTENT SHAPES:
- hero:             {"text": "str"} — 1-2 sentence intro paragraph
- qa:               {"cards": [{"question": "str", "answers": [{"bold": "str", "detail": "str"}], "cta_text": "str or null", "cta_url": "str or null"}]}
- steps:            {"steps": [{"title": "str", "description": "str"}]}
- comparison:       {"rows": [{"feature": "str", "option_a": "str", "option_b": "str"}], "header_a": "str", "header_b": "str"}
- expert_tip:       {"quote": "str", "name": "str", "title": "str"}
- faq:              {"items": [{"question": "str", "answer": "str"}]}
- content_block:    {"html": "str"} — rendered as-is, may contain <p>, <strong>, <a href>, <ul>/<li>
- bullet_list:      {"items": ["str"]}
- cta:              {"heading": "str", "description": "str", "button_text": "str", "button_url": "str"}
- related_articles: {"articles": [{"title": "str", "description": "str", "url": "str"}]}
- table:            {"headers": ["str"], "rows": [["str"]]}

LAYOUT TYPE GUIDE (informational pages only):
- explainer:  default — sidebar TOC, two-column, best for concept explanations (what is IDV, what is NCB)
- listicle:   numbered sections with visual count — best for "top X", "best Y", "reasons to Z" articles
- how-to:     step-card sections with timeline connectors — best for process guides (how to claim, how to renew)
- essay:      single-column wide body, no sidebar — best for opinion or deep long-form content

GRAPH DATA RULES:
- Only include graph_data if the source content contains actual numbers or statistics
- Never invent values — every number in graph_data must come from the source page
- Ideal candidates: depreciation rates by year, premium ranges by city/variant, claim settlement percentages, coverage limits by plan
- Omit graph_data entirely (empty array or omit the key) if no numeric data exists in the source
"""

SYSTEM_PROMPT = r"""You are Acko's expert insurance content writer. Your job is not to rewrite old pages — it is to write the BEST possible article that answers the real question an Indian consumer is typing into Google about car insurance.

You use the crawled page data as raw research material: facts, figures, policy details, and internal links to preserve. But the article you write should be better than what currently exists — clearer, more useful, better structured, and genuinely helpful to someone making an insurance decision.

Think of yourself as a knowledgeable friend who happens to understand Indian motor insurance deeply. You explain things plainly, you don't hedge, and you always answer the actual question.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1: IDENTIFY THE REAL CONSUMER QUESTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before writing anything, ask: what is the real question this person is trying to answer?

Google users often search with keywords, not clean questions. Your job is to infer the underlying question:

• URL: /car-insurance/zero-depreciation → Question: "What does zero depreciation cover and is it worth the extra premium?"
• URL: /car-insurance/maruti-swift → Question: "How much does car insurance cost for a Maruti Swift and what affects the price?"
• URL: /car-insurance/claims → Question: "How do I file a car insurance claim and how long does it take?"
• URL: /car-insurance/ncb → Question: "What is NCB in car insurance and how do I make sure I don't lose it?"

The consumer question becomes the spine of your article. Every section must contribute to answering it.

If the source page is thin, repetitive, or poorly written — do not replicate that. Use the facts it contains and write a better article around the real question.

At the same time, infer the `layout_type` for informational pages:
- Does the content naturally break into a numbered list of items? → `listicle`
- Is it primarily explaining a sequential process (how to do X)? → `how-to`
- Is it a deep conceptual explainer with multiple sub-topics? → `explainer`
- Is it opinion-led or a single long argument? → `essay`
For transactional and longtail pages, omit `layout_type`.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2: CLASSIFY THE PAGE TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• "transactional" — Pillar/product pages (e.g. /car-insurance/, /health-insurance/).
  User intent: compare plans, check price, buy now.
  Structure: lead with trust signals and CTA, support with education. Keep the path to purchase frictionless.

• "informational" — Guides, explainers, how-to articles (e.g. /car-insurance/what-is-idv/, /car-insurance/claims/).
  User intent: understand something before deciding.
  Structure: answer the question completely and authoritatively. Build trust through depth. Funnel at the end.

• "longtail" — Niche or specific-intent pages (e.g. /car-insurance/cng-kit/, /car-insurance/maruti-swift/).
  User intent: one specific, narrow question.
  Structure: answer fast and precisely. Don't pad. Link back to the pillar page.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3: ACCURACY & TRUST RULES (non-negotiable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Insurance content has real consequences. These rules are absolute:

NEVER fabricate:
• Premium amounts or ranges not present in the source data
• Claim settlement ratios or timelines not stated in the source
• IRDAI regulations, policy clauses, or legal requirements not in the source
• Coverage limits, exclusion lists, or add-on features not mentioned in the source
• Competitor comparisons or positioning not in the source

ALWAYS preserve:
• Every specific number, percentage, and rupee figure from the source (verify it appears in the source before using it)
• Every legal reference (Motor Vehicles Act, IRDAI circulars, etc.)
• Every product-specific detail (what is and isn't covered, how claims work, what documents are required)
• Every internal link from the source page

IF the source content is thin and lacks specific data:
• Write around what IS there — structure, clarity, and usefulness can still be high even with limited data
• Do NOT invent specifics to fill gaps
• Use general insurance principles that are universally true (e.g. "IDV decreases each year as your car depreciates") rather than fabricating specific numbers

GRAPH DATA — accuracy is critical:
• Only populate `graph_data` if the source contains actual numbers (depreciation rates, premium figures, claim stats, coverage limits)
• Every value in graph_data must be directly traceable to the source text — do not estimate, round up, or infer
• If no clean numeric data exists in the source, return `"graph_data": []` — an empty chart is worse than no chart
• Ideal graph candidates for insurance content: depreciation % by year, IDV loss over time, premium range by car variant, claim settlement ratio trend, add-on cost comparison

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4: WRITING QUALITY STANDARDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VOICE — Conversational expert:
• Second person always: "your policy", "you can claim", "your premium" — never "the policyholder" or "one should"
• Active voice, present tense
• Sentences under 20 words. If a sentence needs a comma, consider splitting it.
• Confident and direct — state facts plainly, don't hedge unnecessarily
• Inform first, sell second — the reader should feel helped, not sold to

SCANNABILITY — Every page must be easy to read at a glance:
• No paragraph longer than 3 sentences in a content_block
• Bullet lists for 3+ parallel items — never prose lists ("first... second... third...")
• Bold the first 2-4 words of every bullet as a scannable lead-in
• Each bullet = one clear fact or action, not a mini-paragraph

DEPTH — Thin content fails on Google and fails users:
• Informational pages: 5-8 meaty sections, 1,400-1,800 words equivalent depth
• Longtail pages: 3-5 focused sections, 600-900 words equivalent depth
• Transactional pages: 4-6 sections — hero, overview, how it works, why Acko, FAQ, CTA
• Every section must add new information — no repeating the same point in different words

WHAT TO CUT:
• Keyword stuffing (same keyword 3+ times in one paragraph)
• Filler openers: "In this article...", "Let's explore...", "Read on to know...", "In today's world..."
• References to images, videos, or infographics that don't exist in the source text
• Boilerplate disclaimers repeated across every section
• Actuarial jargon without plain-English translation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5: SEO & AEO OPTIMISATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TITLE TAG (50-60 characters):
• Lead with the primary keyword or the consumer question
• Format: "[Question or topic] | Acko"
• ✅ "Zero Depreciation Car Insurance — What It Covers | Acko"
• ❌ "Zero Depreciation Add-On Cover Car Insurance Policy India"

META DESCRIPTION (150-155 characters):
• Must contain the primary keyword and a value hook (speed, price, coverage)
• End with a soft CTA: "Compare plans →" or "Get an instant quote."
• Write for the click, not the crawler

H1 (one per page):
• Question format for informational/longtail: "What Does Zero Depreciation Cover in Car Insurance?"
• Benefit format for transactional: "Buy Car Insurance Online — Instant Policy, No Paperwork"
• ✅ Conversational, specific, benefit-led
• ❌ "Zero Depreciation Car Insurance Add On Cover"

H2 HEADINGS — this is the most important SEO decision you make:
• Every H2 must be a full natural-language question that a person would actually type or speak
• The paragraph immediately after each H2 must answer it in 40 words or fewer — this is your featured snippet candidate
• ✅ "Does zero depreciation cover tyre and battery replacement?"
• ✅ "How much extra does zero depreciation cost per year?"
• ❌ "Coverage Details"
• ❌ "About Zero Depreciation"

INTERNAL LINKS:
• Embed EVERY internal link from the source in content_block HTML or related_articles
• Use descriptive anchor text: "how to file a cashless claim" not "click here" or "read more"
• related_articles must have a title and a one-line description for each link

FAQ SECTION — targets AI Overviews and featured snippets directly:
• 5-8 questions that real users ask about this topic
• Each answer: 2-4 sentences, self-contained, answering the question without needing context
• Use question-format H3s inside the FAQ
• Include at least 2 questions that are adjacent/related to the main topic (these capture longtail traffic)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6: SECTION STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REQUIRED ON EVERY PAGE:
• "hero" — 2 sentences max. State what this page answers and why it matters to the reader. Primary keyword must appear.
• "faq" — 5-8 Q&A pairs. These are your featured snippet bids. Every answer must be standalone.
• "cta" — One primary CTA relevant to the page topic. Never generic.
• "related_articles" — Every internal link from the source, formatted as article cards.

USE WHEN THE CONTENT SUPPORTS IT:
• "qa" — 3+ related sub-questions that can be card-ised. Each card: question + 3-5 bullets with bold lead-ins + optional CTA link.
• "content_block" — Explanatory prose. HTML only: <p>, <strong>, <a href>, <ul>/<li>. Max 3 sentences per <p>.
• "bullet_list" — Features, documents required, eligibility criteria, what's covered/excluded.
• "steps" — Any process: buying, claiming, renewing, calculating. Numbered. Each step needs a title and a description.
• "comparison" — Two options side by side: comprehensive vs third-party, high IDV vs low IDV, cashless vs reimbursement. Two columns.
• "table" — Structured data users can act on: depreciation rates by year, premium ranges by city, coverage limits by plan. Max 8 rows.
• "expert_tip" — One genuinely useful insight that goes beyond the obvious. Must feel like advice, not a sales pitch. Attributed to a named advisor.

SECTION ORDER:
1. hero
2. qa (only if 3+ sub-questions exist in the content)
3. content_block / bullet_list / steps / comparison / table — ordered by user journey logic (define → explain → how to use → what to watch out for)
4. expert_tip
5. faq
6. cta
7. related_articles

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 7: SELF-EVALUATE BEFORE OUTPUTTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before generating the final JSON, ask yourself:

1. Does the H1 and hero directly answer the consumer question I identified in Step 1?
2. Are all H2s genuine questions a person would type into Google?
3. Does each section add new information, or am I repeating myself?
4. Have I included every internal link from the source?
5. Is every number, statistic, and policy detail present in the source data — or did I invent it?
6. Would a first-time car insurance buyer in India find this genuinely useful?
7. Is there any paragraph longer than 3 sentences that should be broken up?
8. Does the FAQ capture the questions someone would still have after reading the main article?

If the answer to any of these is no, revise before outputting.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY a valid JSON object. No markdown code fences. No explanation text. No trailing commas. No comments.

""" + MIRROR_JSON_SCHEMA

USER_PROMPT_TEMPLATE = """You are writing a new, high-quality insurance article for Acko.com. Use the crawled page data below as your research source — extract the facts, figures, links, and structure from it — but write an article that is genuinely better than what currently exists.

━━━ SOURCE PAGE DATA ━━━

URL: {url}
CURRENT TITLE: {title}
CURRENT META DESCRIPTION: {meta_description}
CANONICAL: {canonical}
CURRENT H1: {h1}

━━━ EXISTING HEADING STRUCTURE ━━━
{headings}

━━━ EXISTING BODY CONTENT (use as research — extract facts, don't copy) ━━━
{body_text}

━━━ EXISTING LISTS & Q&A ━━━
{lists}

━━━ INTERNAL LINKS (preserve ALL of these in your output) ━━━
{internal_links}

━━━ AUTHORSHIP ━━━
{authorship}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YOUR TASK — follow all 7 steps in your system instructions:

1. IDENTIFY the real consumer question this URL is trying to answer.
2. CLASSIFY the page type (transactional / informational / longtail).
3. For informational pages, infer the layout_type (explainer / listicle / how-to / essay) from the content shape.
4. WRITE a new article that answers the consumer question better than the current page does.
5. Use only facts, figures, and policy details that appear in the source data above — never invent specifics.
6. If the source contains numeric data (rates, percentages, price ranges), populate graph_data with up to 2 charts. Otherwise return graph_data as an empty array.
7. Every H2 must be a full question. The first paragraph under each H2 must answer it in ≤40 words.
8. Include every internal link from the source — in content_block HTML or related_articles.
9. Self-evaluate before outputting — run through the 8 quality checks in Step 7 of your instructions.

Return ONLY valid JSON. No markdown fences. No explanation."""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_mirror_db() -> None:
    """Create the mirror_data table if it does not exist."""
    conn = sqlite3.connect(str(REGEN_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mirror_data (
            url              TEXT PRIMARY KEY,
            page_type        TEXT,
            section_types    TEXT,
            structured_json  TEXT,
            html_content     TEXT,
            generated_at     TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_mirror_data(
    url: str,
    page_type: str,
    section_types: str,
    structured_json: str,
    html_content: str,
) -> None:
    conn = sqlite3.connect(str(REGEN_DB_PATH))
    try:
        conn.execute("""
            INSERT OR REPLACE INTO mirror_data
            (url, page_type, section_types, structured_json, html_content, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (url, page_type, section_types, structured_json, html_content,
              datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()


def get_crawled_pages() -> pd.DataFrame:
    """Return all rows from crawl_state.db pages table."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        df = pd.read_sql_query("SELECT * FROM pages ORDER BY crawled_at DESC", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def get_page_data(url: str) -> Optional[dict]:
    """Fetch a single crawled page by URL."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
    conn.close()
    if not row:
        return None
    cols = [
        "url", "http_status", "title", "meta_description", "canonical",
        "h1", "headings_json", "body_text", "lists_json", "authorship",
        "internal_links_json", "crawled_at",
    ]
    data = dict(zip(cols, row))
    for jcol in ["headings_json", "lists_json", "internal_links_json"]:
        if data.get(jcol) and isinstance(data[jcol], str):
            try:
                data[jcol] = json.loads(data[jcol])
            except (json.JSONDecodeError, TypeError):
                pass
    return data


# ---------------------------------------------------------------------------
# Content formatting helpers
# ---------------------------------------------------------------------------

def _format_headings(page_data: dict) -> str:
    headings = page_data.get("headings_json", [])
    if isinstance(headings, list):
        lines = []  # type: List[str]
        for h in headings:
            if isinstance(h, dict):
                lines.append("- {}: {}".format(h.get("level", "?"), h.get("text", "")))
        return "\n".join(lines) if lines else "(none extracted)"
    if isinstance(headings, str):
        return headings
    return "(none extracted)"


def _format_lists(page_data: dict) -> str:
    lists_data = page_data.get("lists_json", [])
    if isinstance(lists_data, list):
        parts = []  # type: List[str]
        for i, lst in enumerate(lists_data):
            if isinstance(lst, list):
                part = "List {}:\n".format(i + 1)
                for item in lst:
                    part += "  - {}\n".format(item)
                parts.append(part)
        return "\n".join(parts) if parts else "(none)"
    if isinstance(lists_data, str):
        return lists_data
    return "(none)"


def _format_links(page_data: dict) -> str:
    links = page_data.get("internal_links_json", [])
    if isinstance(links, list):
        lines = []  # type: List[str]
        for link in links:
            if isinstance(link, dict):
                lines.append("- [{}]({})".format(link.get("text", ""), link.get("href", "")))
        return "\n".join(lines) if lines else "(none found)"
    if isinstance(links, str):
        return links
    return "(none found)"


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def _parse_ai_json(text: str) -> dict:
    """Robustly parse JSON from AI response, handling markdown fences and junk."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []  # type: List[str]
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```") and not in_block:
                in_block = True
                continue
            elif stripped == "```" and in_block:
                break
            elif in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find the outermost JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return {"error": "Failed to parse AI response as JSON", "raw_response": text[:2000]}


# ---------------------------------------------------------------------------
# OpenAI API caller
# ---------------------------------------------------------------------------

def call_claude_mirror(api_key: str, page_data: dict, model: str = "gpt-4o") -> dict:
    """Send crawled content to OpenAI and get flexible structured JSON back."""
    client = openai.OpenAI(api_key=api_key)

    body_text = page_data.get("body_text", "") or "(no body text)"
    # Send up to 12000 chars of body to give the AI enough context
    if len(body_text) > 12000:
        body_text = body_text[:20000] + "\n\n... [truncated — {} total chars]".format(
            len(page_data.get("body_text", ""))
        )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        url=page_data.get("url", ""),
        title=page_data.get("title", ""),
        meta_description=page_data.get("meta_description", ""),
        canonical=page_data.get("canonical", ""),
        h1=page_data.get("h1", ""),
        headings=_format_headings(page_data),
        body_text=body_text,
        lists=_format_lists(page_data),
        internal_links=_format_links(page_data),
        authorship=page_data.get("authorship", "") or "(none)",
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=8192,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    text = response.choices[0].message.content.strip()
    return _parse_ai_json(text)


# ---------------------------------------------------------------------------
# Result analysis helpers
# ---------------------------------------------------------------------------

def _extract_page_type(result: dict) -> str:
    """Get the page classification from the AI response."""
    raw = result.get("page_classification", "unknown")
    if isinstance(raw, str) and raw.lower() in ("transactional", "informational", "longtail"):
        return raw.lower()
    return "unknown"


def _extract_section_types(result: dict) -> List[str]:
    """Get list of section types that were generated."""
    sections = result.get("sections", [])
    if not isinstance(sections, list):
        return []
    types = []  # type: List[str]
    for s in sections:
        if isinstance(s, dict) and "type" in s:
            types.append(s["type"])
    return types


def _skipped_section_types(included: List[str]) -> List[str]:
    """Return section types that were NOT included."""
    return [t for t in ALL_SECTION_TYPES if t not in included]


# ---------------------------------------------------------------------------
# Jinja2 rendering
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    """Pull a plain-text / HTML string from any content shape the AI returns."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        # Try all known content keys in priority order
        for key in ("html", "text", "description", "content", "summary", "detail"):
            val = content.get(key)
            if val and isinstance(val, str):
                return val
        # If it has items/paragraphs list, join them
        for key in ("items", "paragraphs", "bullets", "points"):
            val = content.get(key)
            if val and isinstance(val, list):
                parts = []  # type: List[str]
                for item in val:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        parts.append(_extract_text(item))
                return "\n".join(parts)
        # Last resort: join all string values
        str_vals = [str(v) for v in content.values() if v]
        return " ".join(str_vals) if str_vals else ""
    if isinstance(content, list):
        parts = []  # type: List[str]
        for item in content:
            parts.append(_extract_text(item))
        return "\n".join(p for p in parts if p)
    return str(content)


def _extract_list(content, list_key: str = "items") -> list:
    """Pull a list from the AI content, regardless of wrapping."""
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        # {"cards": [...]}, {"items": [...]}, {"rows": [...]}
        for key in (list_key, "cards", "items", "rows", "steps", "questions",
                    "factors", "articles", "links", "features", "plans"):
            if key in content and isinstance(content[key], list):
                return content[key]
        # Maybe the dict IS a single item
        return [content]
    return []


def _transform_ai_response(raw: dict) -> dict:
    """Transform the AI's sections-based response into named template variables.

    The AI returns:  page_classification, sections: [{type, heading, content: {nested}}, ...]
    The templates expect:  page_type, qa_cards, plans, faqs, comparison, etc.
    Content may be: a string, a dict like {"text": "..."}, or {"cards": [...]}, etc.
    """
    out = {}  # type: dict

    # Map page_classification -> page_type
    classification = (raw.get("page_classification") or raw.get("page_type") or "unknown").lower()
    out["page_type"] = classification

    # Layout type (informational sub-template variant)
    layout_type = (raw.get("layout_type") or "explainer").lower().strip()
    if layout_type not in ("explainer", "listicle", "how-to", "essay"):
        layout_type = "explainer"
    out["layout_type"] = layout_type

    # Sanitise graph_data — ensure it is always a list
    raw_graph = raw.get("graph_data")
    if isinstance(raw_graph, list):
        out["graph_data"] = raw_graph
    else:
        out["graph_data"] = []

    # Pass through top-level metadata
    for key in (
        "page_title", "meta_description", "canonical_url", "breadcrumb",
        "product_label", "h1", "subtitle", "author", "reviewer",
        "internal_links", "internal_links_footer",
        "qa_cards", "plans", "expert_tip", "addons", "social_proof",
        "steps_renew", "steps_claim", "comparison", "premium_factors",
        "faqs", "articles", "body_sections", "quick_answer", "toc",
        "related_topics", "graph_data",
    ):
        if key in raw:
            out[key] = raw[key]

    # Transform generic sections array
    sections = raw.get("sections", [])
    if not isinstance(sections, list):
        sections = []

    body_sections = list(out.get("body_sections") or [])
    faqs = list(out.get("faqs") or [])
    qa_cards = list(out.get("qa_cards") or [])
    articles = list(out.get("articles") or [])
    steps_list = []  # type: list
    comparison_items = list(out.get("comparison") or [])
    premium_factors = list(out.get("premium_factors") or [])

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
            if cards:
                for c in cards:
                    if isinstance(c, dict):
                        qa_cards.append({
                            "question": c.get("question") or c.get("heading") or "",
                            "answers": c.get("answers") or c.get("items") or [],
                            "cta_text": c.get("cta_text") or "Learn more",
                            "cta_url": c.get("cta_url") or "#",
                        })
            elif heading:
                qa_cards.append({
                    "question": heading,
                    "answers": [{"bold": "", "detail": _extract_text(content)}],
                    "cta_text": "Learn more",
                    "cta_url": "#",
                })

        elif sec_type == "faq":
            items = _extract_list(content, "questions")
            if items:
                for item in items:
                    if isinstance(item, dict):
                        faqs.append({
                            "question": item.get("question") or item.get("q") or "",
                            "answer": item.get("answer") or item.get("a") or _extract_text(item.get("content")),
                        })
            elif heading:
                faqs.append({"question": heading, "answer": _extract_text(content)})

        elif sec_type == "steps":
            items = _extract_list(content, "steps")
            for item in items:
                if isinstance(item, dict):
                    steps_list.append({
                        "title": item.get("title") or item.get("heading") or item.get("step") or "",
                        "description": item.get("description") or item.get("content") or item.get("detail") or "",
                    })
                elif isinstance(item, str):
                    steps_list.append({"title": item, "description": ""})

        elif sec_type in ("comparison", "table"):
            items = _extract_list(content, "rows")
            if isinstance(content, dict) and "headers" in content:
                # Table format: {headers, rows} -> comparison format
                headers = content.get("headers", [])
                rows = content.get("rows", [])
                for row in rows:
                    if isinstance(row, list) and len(row) >= 2:
                        comparison_items.append({
                            "feature": row[0] if len(row) > 0 else "",
                            "acko": row[1] if len(row) > 1 else "",
                            "others": row[2] if len(row) > 2 else "",
                        })
                    elif isinstance(row, dict):
                        comparison_items.append(row)
            elif items:
                for item in items:
                    if isinstance(item, dict):
                        comparison_items.append(item)

            # Also add as body section for informational templates
            body_sections.append({
                "heading": heading,
                "content": _extract_text(content),
                "key_takeaway": None,
                "bullets": [],
            })

        elif sec_type in ("content_block", "bullet_list", "text"):
            text = _extract_text(content)
            bullets = []  # type: list
            items = _extract_list(content, "items")
            if items and isinstance(items[0], str):
                bullets = items
            elif items and isinstance(items[0], dict):
                bullets = [_extract_text(i) for i in items]
            body_sections.append({
                "heading": heading,
                "content": text,
                "key_takeaway": (content.get("key_takeaway") or content.get("takeaway")) if isinstance(content, dict) else None,
                "bullets": bullets,
            })

        elif sec_type == "expert_tip":
            if not out.get("expert_tip"):
                text = _extract_text(content)
                name = ""
                title = ""
                if isinstance(content, dict):
                    name = content.get("name") or content.get("author") or ""
                    title = content.get("title") or content.get("role") or ""
                out["expert_tip"] = {"quote": text, "name": name, "title": title}

        elif sec_type == "cta":
            pass  # Built into templates

        elif sec_type == "related_articles":
            items = _extract_list(content, "articles")
            for item in items:
                if isinstance(item, dict):
                    articles.append({
                        "title": item.get("title") or "",
                        "description": item.get("description") or item.get("summary") or "",
                        "url": item.get("url") or item.get("href") or "#",
                    })
                elif isinstance(item, str):
                    articles.append({"title": item, "description": "", "url": "#"})

        elif sec_type == "plans":
            items = _extract_list(content, "plans")
            plans = list(out.get("plans") or [])
            for item in items:
                if isinstance(item, dict):
                    plans.append(item)
            out["plans"] = plans

        elif sec_type == "premium_factors":
            items = _extract_list(content, "factors")
            for item in items:
                if isinstance(item, dict):
                    premium_factors.append({
                        "title": item.get("title") or item.get("factor") or "",
                        "description": item.get("description") or item.get("detail") or "",
                    })

        else:
            # Unknown section — add as body section
            body_sections.append({
                "heading": heading,
                "content": _extract_text(content),
                "key_takeaway": None,
                "bullets": [],
            })

    # Write back
    if qa_cards:
        out["qa_cards"] = qa_cards
    if faqs:
        out["faqs"] = faqs
    if body_sections:
        out["body_sections"] = body_sections
    if articles:
        out["articles"] = articles
    if steps_list:
        out["steps_renew"] = steps_list
    if comparison_items:
        out["comparison"] = comparison_items
    if premium_factors:
        out["premium_factors"] = premium_factors

    # Generate TOC from body_sections
    if body_sections and not out.get("toc"):
        toc = []  # type: list
        for i, sec in enumerate(body_sections):
            h = sec.get("heading", "")
            if h:
                toc.append({"id": "section-{}".format(i), "text": h})
        out["toc"] = toc

    # Map internal_links_footer -> internal_links
    if not out.get("internal_links") and out.get("internal_links_footer"):
        out["internal_links"] = out["internal_links_footer"]

    return out


def render_html(template_vars: dict) -> str:
    """Transform AI response and render the appropriate Jinja2 template."""
    # Transform the AI's generic format into template-specific variables
    transformed = _transform_ai_response(template_vars)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
        undefined=jinja2.Undefined,
    )
    page_type = (transformed.get("page_type") or "").lower().strip()
    template_name = TEMPLATE_MAP.get(page_type, TEMPLATE_FILE)

    # Fall back to generic if the specific template doesn't exist
    try:
        template = env.get_template(template_name)
    except jinja2.TemplateNotFound:
        template = env.get_template(TEMPLATE_FILE)

    return template.render(**transformed)


# ---------------------------------------------------------------------------
# URL to filename helper
# ---------------------------------------------------------------------------

def url_to_filename(url: str) -> str:
    """Convert a URL to a safe filename."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_")
    if not path:
        path = "index"
    return path + ".html"


# ---------------------------------------------------------------------------
# UI helper: display section badges
# ---------------------------------------------------------------------------

PAGE_TYPE_COLORS = {
    "transactional": "#10B981",
    "informational": "#3B82F6",
    "longtail": "#F59E0B",
    "unknown": "#6B7280",
}


def _render_page_type_badge(page_type: str) -> str:
    """Return HTML for a colored page-type badge."""
    color = PAGE_TYPE_COLORS.get(page_type, "#6B7280")
    return (
        '<span style="display:inline-block;background:{color};color:#fff;'
        'font-size:0.75rem;font-weight:700;padding:4px 12px;border-radius:8px;'
        'letter-spacing:0.5px;text-transform:uppercase;">{label}</span>'
    ).format(color=color, label=page_type)


def _render_section_pills(included: List[str], skipped: List[str]) -> str:
    """Return HTML showing included and skipped section pills."""
    parts = []  # type: List[str]
    for s in included:
        parts.append(
            '<span style="display:inline-block;background:#EDE9FE;color:#522ED3;'
            'font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:6px;'
            'margin:2px 4px 2px 0;">{}</span>'.format(s)
        )
    for s in skipped:
        parts.append(
            '<span style="display:inline-block;background:#F3F4F6;color:#9CA3AF;'
            'font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:6px;'
            'margin:2px 4px 2px 0;text-decoration:line-through;">{}</span>'.format(s)
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def get_library_pages() -> pd.DataFrame:
    """Return all previously generated mirror pages."""
    if not REGEN_DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(REGEN_DB_PATH))
    try:
        df = pd.read_sql_query(
            "SELECT url, page_type, section_types, generated_at FROM mirror_data ORDER BY generated_at DESC",
            conn,
        )
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def get_mirror_html(url: str) -> Optional[str]:
    """Fetch stored HTML for a mirror page."""
    if not REGEN_DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(REGEN_DB_PATH))
    row = conn.execute("SELECT html_content FROM mirror_data WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_mirror_json(url: str) -> Optional[str]:
    """Fetch stored structured JSON for a mirror page."""
    if not REGEN_DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(REGEN_DB_PATH))
    row = conn.execute("SELECT structured_json FROM mirror_data WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_already_generated_urls() -> set:
    """Return set of URLs that already have mirror pages."""
    if not REGEN_DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(REGEN_DB_PATH))
    try:
        rows = conn.execute("SELECT url FROM mirror_data").fetchall()
    except Exception:
        rows = []
    conn.close()
    return set(r[0] for r in rows)


def main() -> None:
    st.set_page_config(
        page_title="Mirror pages · Acko SEO",
        page_icon="🪞",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("Mirror page generator")
    st.caption(
        "Turn crawled SQLite rows into structured JSON and visual HTML using Claude — "
        "then edit, batch, or export from the library."
    )

    nav1, nav2, _ = st.columns([1, 1, 4])
    with nav1:
        st.page_link("app.py", label="Home", icon="🏠")
    with nav2:
        st.page_link("pages/1_crawler.py", label="Crawler", icon="🕷️")

    init_mirror_db()

    # ---- Sidebar ----
    deployment_key = get_deployment_openai_api_key()
    with st.sidebar:
        st.header("Navigation")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_crawler.py", label="Crawler", icon="🕷️")
        st.divider()

        st.subheader("OpenAI")
        if deployment_key:
            st.success("Server API key is set.")
            st.caption(
                "`OPENAI_API_KEY` or Streamlit secret. Optional override below."
            )
            override = st.text_input(
                "Override API key (optional)",
                type="password",
                help="Leave empty to use the server key.",
                value=st.session_state.get("mirror_api_key_override", ""),
                key="mirror_api_key_override_input",
            )
            st.session_state["mirror_api_key_override"] = override
            api_key = (override.strip() or deployment_key)
        else:
            api_key = st.text_input(
                "OpenAI API key",
                type="password",
                help=(
                    "Local: paste from platform.openai.com. Hosted: set OPENAI_API_KEY "
                    "or add it to Streamlit secrets / .streamlit/secrets.toml."
                ),
                value=st.session_state.get("mirror_api_key", ""),
                key="mirror_api_key_input",
            )
            st.session_state["mirror_api_key"] = api_key

        model = st.selectbox(
            "Model",
            [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
            ],
            index=0,
            help="gpt-4o — balanced. gpt-4-turbo — highest quality. gpt-4o-mini — fastest / lowest cost.",
            key="mirror_model_select",
        )

        st.divider()

        library_df = get_library_pages()
        already_done = get_already_generated_urls()
        crawled_df = get_crawled_pages()
        total_crawled = len(crawled_df) if not crawled_df.empty else 0
        total_generated = len(library_df)

        with st.container(border=True):
            st.markdown("**Progress**")
            st.metric("Crawled (DB)", total_crawled)
            st.metric("Mirrors generated", total_generated)
            if total_crawled > 0:
                st.progress(min(total_generated / total_crawled, 1.0))
                st.caption("{}/{} mirrored".format(total_generated, total_crawled))

    with st.expander("Quick start", expanded=False):
        st.markdown(
            """
            1. Finish a **crawl** so `crawl_state.db` has pages.  
            2. Configure **OpenAI** in the sidebar (server key or paste).
            3. **Generate** one page to validate, then use **Batch** for volume.  
            4. **Library** filters and ZIP export live under the last tab.
            """
        )

    # ---- Tabs ----
    tab_generate, tab_content, tab_batch, tab_library = st.tabs([
        "Generate",
        "Edit content",
        "Batch",
        "Library",
    ])

    # =====================================================================
    # TAB 1: Generate a single page
    # =====================================================================
    with tab_generate:
        if crawled_df.empty:
            st.info(
                "**No crawled pages yet.** Run the crawler first, then return here — "
                "this step reads from `crawl_state.db`."
            )
            st.page_link("pages/1_crawler.py", label="Open crawler →", icon="🕷️")
        else:
            url_list = crawled_df["url"].tolist()

            # Mark already-generated pages in the selector
            labels = []  # type: List[str]
            for u in url_list:
                if u in already_done:
                    labels.append(u + "  [done]")
                else:
                    labels.append(u)

            selected_idx = st.selectbox(
                "Select a crawled page",
                range(len(url_list)),
                format_func=lambda i: labels[i],
                key="gen_page_select",
            )
            selected_url = url_list[selected_idx]

            # Show existing mirror page if available
            existing_html = get_mirror_html(selected_url)
            if existing_html:
                st.success(
                    "This URL already has a mirror. Preview in **Edit content**, or regenerate below to overwrite."
                )
                col_view, col_regen = st.columns(2)
                with col_view:
                    view_existing = st.button(
                        "View existing",
                        use_container_width=True,
                    )
                with col_regen:
                    regenerate = st.button(
                        "Regenerate (overwrite)",
                        type="primary",
                        use_container_width=True,
                    )
            else:
                view_existing = False
                regenerate = st.button(
                    "Generate Mirror Page",
                    type="primary",
                    use_container_width=True,
                )

            # Show crawled content summary
            page_data = get_page_data(selected_url)
            if page_data:
                with st.expander("Crawled content summary", expanded=False):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown("**Title:** {}".format(page_data.get("title", "(none)")))
                        st.markdown("**H1:** {}".format(page_data.get("h1", "(none)")))
                    with col2:
                        st.markdown("**Meta:** {}".format(
                            (page_data.get("meta_description", "") or "(none)")[:100]
                        ))
                    with col3:
                        headings = page_data.get("headings_json", [])
                        heading_count = len(headings) if isinstance(headings, list) else 0
                        links = page_data.get("internal_links_json", [])
                        link_count = len(links) if isinstance(links, list) else 0
                        body = page_data.get("body_text", "") or ""
                        st.caption("Headings: {} | Links: {} | Body: {:,} chars".format(
                            heading_count, link_count, len(body)
                        ))

            # --- View existing mirror page ---
            if view_existing and existing_html:
                st.subheader("Mirror Page Preview")
                components.html(existing_html, height=800, scrolling=True)
                filename = url_to_filename(selected_url)
                st.download_button(
                    label="Download HTML",
                    data=existing_html.encode("utf-8"),
                    file_name=filename,
                    mime="text/html",
                    use_container_width=True,
                    key="gen_dl_existing",
                )

            # --- Generate / Regenerate ---
            if regenerate:
                if not api_key:
                    st.error(
                        "No OpenAI API key: set `OPENAI_API_KEY` on the server or in Streamlit "
                        "secrets, or enter a key in the sidebar."
                    )
                elif not page_data:
                    st.error("Could not load page data for: {}".format(selected_url))
                else:
                    with st.spinner("Sending to {} ...".format(model)):
                        try:
                            result = call_claude_mirror(api_key, page_data, model)
                        except Exception as e:
                            st.error("API call failed: {}".format(e))
                            result = None

                    if result and "error" in result:
                        st.error("Error: {}".format(result["error"]))
                        if "raw_response" in result:
                            with st.expander("Raw response"):
                                st.code(result["raw_response"])
                    elif result:
                        page_type = _extract_page_type(result)
                        included = _extract_section_types(result)
                        skipped = _skipped_section_types(included)

                        st.success("Generated! Type: {} | Sections: {}".format(
                            page_type, len(included)
                        ))
                        st.markdown(
                            _render_page_type_badge(page_type) + "  " +
                            _render_section_pills(included, skipped),
                            unsafe_allow_html=True,
                        )

                        with st.expander("View Structured JSON", expanded=False):
                            st.json(result)

                        try:
                            html_content = render_html(result)
                        except Exception as e:
                            st.error("Template rendering failed: {}".format(e))
                            html_content = None

                        if html_content:
                            structured_json = json.dumps(result, ensure_ascii=False)
                            section_types_str = ",".join(included)
                            save_mirror_data(
                                selected_url, page_type, section_types_str,
                                structured_json, html_content,
                            )

                            st.subheader("Mirror Page Preview")
                            components.html(html_content, height=800, scrolling=True)

                            filename = url_to_filename(selected_url)
                            st.download_button(
                                label="Download HTML",
                                data=html_content.encode("utf-8"),
                                file_name=filename,
                                mime="text/html",
                                use_container_width=True,
                                key="gen_dl_new",
                            )

    # =====================================================================
    # TAB 2: Content Editor — old vs new side-by-side with inline editing
    # =====================================================================
    with tab_content:
        if crawled_df.empty:
            st.info(
                "**No crawled pages.** Complete a crawl before generating mirrors."
            )
            st.page_link("pages/1_crawler.py", label="Open crawler →", icon="🕷️")
        else:
            # Only show pages that have been generated
            generated_urls = sorted(already_done)
            if not generated_urls:
                st.info(
                    "**Nothing to edit yet.** Use **Generate** (or **Batch**) to create at least one mirror, "
                    "then pick it here for the scorecard and JSON edits."
                )
            else:
                edit_url = st.selectbox(
                    "Select a generated page to edit",
                    generated_urls,
                    key="content_editor_select",
                )

                if edit_url:
                    page_data = get_page_data(edit_url)
                    raw_json_str = get_mirror_json(edit_url)

                    if not page_data or not raw_json_str:
                        st.error("Could not load data for this page.")
                    else:
                        struct = json.loads(raw_json_str)

                        # ---- SEO SCORECARD ----
                        st.markdown("### SEO & Content Scorecard")

                        title_len = len(struct.get("page_title", ""))
                        meta_len = len(struct.get("meta_description", ""))
                        sections = struct.get("sections", [])
                        section_count = len(sections)
                        faq_count = 0
                        link_count = len(struct.get("internal_links_footer", []))
                        has_hero = False
                        has_cta = False
                        question_h2s = 0
                        for sec in sections:
                            stype = sec.get("type", "")
                            if stype == "faq":
                                items = sec.get("content", {}).get("items", [])
                                faq_count = len(items)
                            if stype == "hero":
                                has_hero = True
                            if stype == "cta":
                                has_cta = True
                            heading = sec.get("heading", "") or ""
                            if any(heading.lower().startswith(q) for q in ["what ", "how ", "why ", "when ", "which ", "is ", "can ", "does ", "do "]):
                                question_h2s += 1

                        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
                        with sc1:
                            color = "normal" if 50 <= title_len <= 60 else "off"
                            st.metric("Title length", "{} chars".format(title_len),
                                      delta="OK" if color == "normal" else ("too short" if title_len < 50 else "too long"))
                        with sc2:
                            color = "normal" if 145 <= meta_len <= 160 else "off"
                            st.metric("Meta desc length", "{} chars".format(meta_len),
                                      delta="OK" if color == "normal" else ("too short" if meta_len < 145 else "too long"))
                        with sc3:
                            st.metric("Sections", section_count,
                                      delta="good" if section_count >= 5 else "add more")
                        with sc4:
                            st.metric("FAQs", faq_count,
                                      delta="good" if faq_count >= 5 else "add more")
                        with sc5:
                            st.metric("Question H2s (AEO)", question_h2s,
                                      delta="great" if question_h2s >= 3 else "rephrase headings")

                        checks = []  # type: List[str]
                        warnings = []  # type: List[str]
                        if has_hero:
                            checks.append("Hero section present")
                        else:
                            warnings.append("Missing hero section")
                        if has_cta:
                            checks.append("CTA section present")
                        else:
                            warnings.append("Missing CTA section")
                        if link_count >= 3:
                            checks.append("{} internal links preserved".format(link_count))
                        else:
                            warnings.append("Only {} internal links — check for lost links".format(link_count))
                        if faq_count >= 5:
                            checks.append("{} FAQs for rich snippets".format(faq_count))

                        if checks:
                            st.success(" | ".join(checks))
                        if warnings:
                            st.warning(" | ".join(warnings))

                        st.markdown("---")

                        # ---- SIDE-BY-SIDE: OLD vs NEW ----
                        st.markdown("### Old vs New Content")

                        old_col, new_col = st.columns(2)

                        with old_col:
                            st.markdown(
                                '<div style="background:#FEF2F2;padding:12px 16px;border-radius:8px;'
                                'border-left:4px solid #EF4444;margin-bottom:12px;">'
                                '<strong style="color:#991B1B;">Original (crawled)</strong></div>',
                                unsafe_allow_html=True,
                            )

                            st.markdown("**Title:** {}".format(page_data.get("title", "(none)")))
                            st.markdown("**H1:** {}".format(page_data.get("h1", "(none)")))
                            st.markdown("**Meta:** {}".format(
                                page_data.get("meta_description", "") or "(none)"
                            ))
                            st.markdown("---")

                            # Show original headings
                            orig_headings = page_data.get("headings_json", [])
                            if isinstance(orig_headings, list) and orig_headings:
                                st.markdown("**Heading Structure:**")
                                for h in orig_headings:
                                    if isinstance(h, dict):
                                        level = h.get("level", "?")
                                        text = h.get("text", "")
                                        indent = "  " * (int(level[1]) - 1) if level[0] == "H" and level[1:].isdigit() else ""
                                        st.markdown("{}**{}:** {}".format(indent, level, text))
                            st.markdown("---")

                            # Show original body (truncated)
                            orig_body = page_data.get("body_text", "") or "(empty)"
                            st.markdown("**Body content:**")
                            st.text_area(
                                "Original body (read-only)",
                                value=orig_body[:5000],
                                height=300,
                                disabled=True,
                                key="old_body",
                                label_visibility="collapsed",
                            )

                        with new_col:
                            st.markdown(
                                '<div style="background:#F0FDF4;padding:12px 16px;border-radius:8px;'
                                'border-left:4px solid #22C55E;margin-bottom:12px;">'
                                '<strong style="color:#166534;">New (AI-generated)</strong></div>',
                                unsafe_allow_html=True,
                            )

                            st.markdown("**Title:** {}".format(struct.get("page_title", "(none)")))
                            st.markdown("**H1:** {}".format(struct.get("h1", "(none)")))
                            st.markdown("**Meta:** {}".format(struct.get("meta_description", "(none)")))
                            st.markdown("---")

                            # Show new section headings
                            if sections:
                                st.markdown("**Section Structure:**")
                                for sec in sections:
                                    stype = sec.get("type", "?")
                                    heading = sec.get("heading", "")
                                    icon = {
                                        "hero": "🎯", "qa": "❓", "content_block": "📝",
                                        "bullet_list": "📋", "steps": "🔢", "comparison": "⚖️",
                                        "expert_tip": "💡", "faq": "🙋", "cta": "🚀",
                                        "related_articles": "📚", "table": "📊",
                                    }.get(stype, "📌")
                                    if heading:
                                        st.markdown("{} **{}:** {}".format(icon, stype, heading))
                                    else:
                                        st.markdown("{} **{}**".format(icon, stype))
                            st.markdown("---")

                            # Show new body (all content blocks concatenated)
                            new_body_parts = []  # type: List[str]
                            for sec in sections:
                                stype = sec.get("type", "")
                                heading = sec.get("heading", "")
                                content = sec.get("content", {})
                                if heading:
                                    new_body_parts.append("## {}".format(heading))
                                if stype == "hero":
                                    new_body_parts.append(content.get("text", ""))
                                elif stype == "content_block":
                                    new_body_parts.append(content.get("html", ""))
                                elif stype == "bullet_list":
                                    for item in content.get("items", []):
                                        new_body_parts.append("- {}".format(item))
                                elif stype == "faq":
                                    for item in content.get("items", []):
                                        new_body_parts.append("**Q: {}**".format(item.get("question", "")))
                                        new_body_parts.append("A: {}".format(item.get("answer", "")))
                                elif stype == "steps":
                                    for j, step in enumerate(content.get("steps", [])):
                                        new_body_parts.append("{}. **{}** — {}".format(
                                            j + 1, step.get("title", ""), step.get("description", "")
                                        ))
                                elif stype == "qa":
                                    for card in content.get("cards", []):
                                        new_body_parts.append("**{}**".format(card.get("question", "")))
                                        for ans in card.get("answers", []):
                                            new_body_parts.append("- **{}** {}".format(
                                                ans.get("bold", ""), ans.get("detail", "")
                                            ))
                                elif stype == "comparison":
                                    ha = content.get("header_a", "Option A")
                                    hb = content.get("header_b", "Option B")
                                    new_body_parts.append("| Feature | {} | {} |".format(ha, hb))
                                    for row in content.get("rows", []):
                                        new_body_parts.append("| {} | {} | {} |".format(
                                            row.get("feature", ""), row.get("option_a", ""), row.get("option_b", "")
                                        ))
                                elif stype == "expert_tip":
                                    new_body_parts.append('"{}" — {}, {}'.format(
                                        content.get("quote", ""),
                                        content.get("name", ""),
                                        content.get("title", ""),
                                    ))
                                elif stype == "cta":
                                    new_body_parts.append("[{}] {}".format(
                                        content.get("button_text", "CTA"),
                                        content.get("description", ""),
                                    ))
                                elif stype == "related_articles":
                                    for art in content.get("articles", []):
                                        new_body_parts.append("- [{}]({})".format(
                                            art.get("title", ""), art.get("url", "#")
                                        ))
                                new_body_parts.append("")

                            new_body_text = "\n".join(new_body_parts)
                            st.markdown("**New content:**")
                            st.text_area(
                                "New content (read-only)",
                                value=new_body_text[:5000],
                                height=300,
                                disabled=True,
                                key="new_body",
                                label_visibility="collapsed",
                            )

                        st.markdown("---")

                        # ---- INLINE SECTION EDITOR ----
                        st.markdown("### Edit Sections")
                        st.caption(
                            "Edit the JSON for any section below. Changes are saved when you click "
                            "**Save & Re-render**."
                        )

                        # Editable metadata
                        with st.expander("Edit page metadata (title, meta, H1)", expanded=False):
                            edited_title = st.text_input(
                                "Page title",
                                value=struct.get("page_title", ""),
                                key="edit_title",
                            )
                            edited_meta = st.text_area(
                                "Meta description",
                                value=struct.get("meta_description", ""),
                                height=80,
                                key="edit_meta",
                            )
                            edited_h1 = st.text_input(
                                "H1",
                                value=struct.get("h1", ""),
                                key="edit_h1",
                            )
                            edited_subtitle = st.text_input(
                                "Subtitle",
                                value=struct.get("subtitle", ""),
                                key="edit_subtitle",
                            )

                        # Editable sections
                        edited_sections = []  # type: List[dict]
                        for idx, sec in enumerate(sections):
                            stype = sec.get("type", "?")
                            heading = sec.get("heading", "") or "(no heading)"
                            icon = {
                                "hero": "🎯", "qa": "❓", "content_block": "📝",
                                "bullet_list": "📋", "steps": "🔢", "comparison": "⚖️",
                                "expert_tip": "💡", "faq": "🙋", "cta": "🚀",
                                "related_articles": "📚", "table": "📊",
                            }.get(stype, "📌")

                            with st.expander(
                                "{} Section {}: {} — {}".format(icon, idx + 1, stype, heading),
                                expanded=False,
                            ):
                                # Heading editor
                                new_heading = st.text_input(
                                    "Section heading",
                                    value=sec.get("heading", "") or "",
                                    key="sec_heading_{}".format(idx),
                                )

                                # Content editor as JSON
                                content_json = json.dumps(
                                    sec.get("content", {}), indent=2, ensure_ascii=False
                                )
                                new_content_str = st.text_area(
                                    "Section content (JSON)",
                                    value=content_json,
                                    height=200,
                                    key="sec_content_{}".format(idx),
                                )

                                # Parse the edited content
                                try:
                                    new_content = json.loads(new_content_str)
                                except json.JSONDecodeError:
                                    st.error("Invalid JSON — fix before saving.")
                                    new_content = sec.get("content", {})

                                edited_sections.append({
                                    "type": stype,
                                    "heading": new_heading if new_heading else None,
                                    "content": new_content,
                                })

                        st.markdown("---")

                        # Save & re-render
                        if st.button("Save & Re-render", type="primary", use_container_width=True, key="save_rerender"):
                            # Build updated struct
                            updated = dict(struct)
                            updated["page_title"] = edited_title
                            updated["meta_description"] = edited_meta
                            updated["h1"] = edited_h1
                            updated["subtitle"] = edited_subtitle
                            updated["sections"] = edited_sections

                            try:
                                new_html = render_html(updated)
                            except Exception as e:
                                st.error("Render error: {}".format(e))
                                new_html = None

                            if new_html:
                                # Save back to DB
                                page_type = _extract_page_type(updated)
                                included = _extract_section_types(updated)
                                section_types_str = ",".join(included)
                                save_mirror_data(
                                    edit_url, page_type, section_types_str,
                                    json.dumps(updated, ensure_ascii=False),
                                    new_html,
                                )
                                st.success("Saved! Preview updated below.")
                                components.html(new_html, height=800, scrolling=True)

                                st.download_button(
                                    label="Download edited HTML",
                                    data=new_html.encode("utf-8"),
                                    file_name=url_to_filename(edit_url),
                                    mime="text/html",
                                    use_container_width=True,
                                    key="dl_edited",
                                )

                        # Always show current preview at bottom
                        st.markdown("---")
                        st.markdown("### Current Mirror Page Preview")
                        current_html = get_mirror_html(edit_url)
                        if current_html:
                            components.html(current_html, height=800, scrolling=True)

    # =====================================================================
    # TAB 2: Batch generation
    # =====================================================================
    with tab_batch:
        if crawled_df.empty:
            st.info(
                "**No crawled pages.** Batch mode needs rows in `crawl_state.db` from the crawler."
            )
            st.page_link("pages/1_crawler.py", label="Open crawler →", icon="🕷️")
        else:
            remaining = [u for u in crawled_df["url"].tolist() if u not in already_done]

            col_b1, col_b2 = st.columns(2)
            with col_b1:
                st.metric("Remaining to generate", len(remaining))
            with col_b2:
                st.metric("Already generated", len(already_done))

            if not remaining:
                st.success("All {} crawled pages have mirror pages!".format(total_crawled))
            else:
                batch_size = st.number_input(
                    "Pages to process in this batch",
                    min_value=1,
                    max_value=min(len(remaining), 200),
                    value=min(10, len(remaining)),
                )
                batch_delay = st.number_input(
                    "Delay between API calls (seconds)",
                    min_value=1, max_value=30, value=3,
                )

                batch_urls = remaining[:batch_size]
                with st.expander("Pages in this batch ({})".format(len(batch_urls))):
                    for u in batch_urls:
                        st.text(u)

                if st.button("Start Batch", type="primary", use_container_width=True):
                    if not api_key:
                        st.error(
                            "No Claude API key: set `ANTHROPIC_API_KEY` on the server or in Streamlit "
                            "secrets, or enter a key in the sidebar."
                        )
                    else:
                        MIRROR_DIR.mkdir(parents=True, exist_ok=True)

                        progress_bar = st.progress(0.0)
                        status_text = st.empty()
                        results_summary = st.empty()

                        successes = 0
                        failures = 0
                        generated_files = {}  # type: Dict[str, str]

                        for i, url in enumerate(batch_urls):
                            status_text.info("Processing {}/{}: {}".format(
                                i + 1, len(batch_urls), url
                            ))
                            progress_bar.progress(i / len(batch_urls))

                            page_data = get_page_data(url)
                            if not page_data:
                                failures += 1
                                continue

                            try:
                                result = call_claude_mirror(api_key, page_data, model)

                                if "error" in result:
                                    failures += 1
                                else:
                                    html_content = render_html(result)
                                    structured_json = json.dumps(result, ensure_ascii=False)
                                    page_type = _extract_page_type(result)
                                    included = _extract_section_types(result)
                                    section_types_str = ",".join(included)

                                    save_mirror_data(
                                        url, page_type, section_types_str,
                                        structured_json, html_content,
                                    )

                                    filename = url_to_filename(url)
                                    filepath = MIRROR_DIR / filename
                                    filepath.write_text(html_content, encoding="utf-8")
                                    generated_files[filename] = html_content
                                    successes += 1

                            except Exception as e:
                                failures += 1
                                status_text.warning("Failed on {}: {}".format(url, e))

                            results_summary.markdown(
                                "Succeeded: **{}** | Failed: **{}** | Processed: **{}/{}**".format(
                                    successes, failures, i + 1, len(batch_urls)
                                )
                            )

                            if i < len(batch_urls) - 1:
                                time.sleep(batch_delay)

                        progress_bar.progress(1.0)
                        status_text.success(
                            "Batch complete! {} generated, {} failed.".format(successes, failures)
                        )

                        if generated_files:
                            zip_buffer = io.BytesIO()
                            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                                for fname, content in generated_files.items():
                                    zf.writestr(fname, content)
                            zip_buffer.seek(0)

                            st.download_button(
                                label="Download batch as ZIP",
                                data=zip_buffer.getvalue(),
                                file_name="mirror_pages_{}.zip".format(
                                    datetime.now().strftime("%Y%m%d_%H%M%S")
                                ),
                                mime="application/zip",
                                use_container_width=True,
                                key="batch_dl_zip",
                            )

    # =====================================================================
    # TAB 3: Library — browse all generated mirror pages
    # =====================================================================
    with tab_library:
        library_df = get_library_pages()

        if library_df.empty:
            st.info(
                "**Library is empty.** Generate one page on the **Generate** tab, or run **Batch**, "
                "then come back to filter, preview, and download ZIPs."
            )
        else:
            st.subheader("Generated Mirror Pages ({})".format(len(library_df)))

            # Filters
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                type_filter = st.selectbox(
                    "Filter by page type",
                    ["All"] + sorted(library_df["page_type"].dropna().unique().tolist()),
                    key="lib_type_filter",
                )
            with col_f2:
                search_term = st.text_input(
                    "Search by URL",
                    key="lib_search",
                    placeholder="e.g. idv, claims, comprehensive",
                )

            filtered = library_df.copy()
            if type_filter != "All":
                filtered = filtered[filtered["page_type"] == type_filter]
            if search_term:
                filtered = filtered[filtered["url"].str.contains(search_term, case=False, na=False)]

            # Summary metrics
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Total", len(filtered))
            if "page_type" in filtered.columns:
                type_counts = filtered["page_type"].value_counts().to_dict()
                col_m2.metric("Transactional", type_counts.get("transactional", 0))
                col_m3.metric("Informational", type_counts.get("informational", 0))
                col_m4.metric("Longtail", type_counts.get("longtail", 0))

            # Data table
            st.dataframe(
                filtered,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "url": st.column_config.TextColumn("URL", width="large"),
                    "page_type": st.column_config.TextColumn("Type", width="small"),
                    "section_types": st.column_config.TextColumn("Sections", width="medium"),
                    "generated_at": st.column_config.TextColumn("Generated", width="medium"),
                },
            )

            st.divider()

            # Select a page to preview
            lib_url = st.selectbox(
                "Select a page to preview / download",
                filtered["url"].tolist(),
                key="lib_preview_select",
            )

            if lib_url:
                col_prev, col_dl, col_json = st.columns(3)
                with col_prev:
                    preview_btn = st.button(
                        "Preview",
                        use_container_width=True,
                        type="primary",
                    )
                with col_dl:
                    html = get_mirror_html(lib_url)
                    if html:
                        st.download_button(
                            label="Download HTML",
                            data=html.encode("utf-8"),
                            file_name=url_to_filename(lib_url),
                            mime="text/html",
                            use_container_width=True,
                            key="lib_dl_html_{}".format(hash(lib_url)),
                        )
                with col_json:
                    raw_json = get_mirror_json(lib_url)
                    if raw_json:
                        st.download_button(
                            label="Download JSON",
                            data=raw_json.encode("utf-8"),
                            file_name=url_to_filename(lib_url).replace(".html", ".json"),
                            mime="application/json",
                            use_container_width=True,
                            key="lib_dl_json_{}".format(hash(lib_url)),
                        )

                if preview_btn:
                    html = get_mirror_html(lib_url)
                    if html:
                        components.html(html, height=800, scrolling=True)
                    else:
                        st.error("No HTML found for this page.")

            # Bulk export
            st.divider()
            if st.button("Download entire library as ZIP", use_container_width=True):
                conn = sqlite3.connect(str(REGEN_DB_PATH))
                all_rows = conn.execute(
                    "SELECT url, html_content FROM mirror_data"
                ).fetchall()
                conn.close()

                if all_rows:
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                        for row_url, row_html in all_rows:
                            zf.writestr(url_to_filename(row_url), row_html)
                    zip_buffer.seek(0)

                    st.download_button(
                        label="Download ZIP ({} pages)".format(len(all_rows)),
                        data=zip_buffer.getvalue(),
                        file_name="mirror_library_{}.zip".format(
                            datetime.now().strftime("%Y%m%d_%H%M%S")
                        ),
                        mime="application/zip",
                        use_container_width=True,
                        key="lib_dl_full_zip",
                    )


if __name__ == "__main__":
    main()
