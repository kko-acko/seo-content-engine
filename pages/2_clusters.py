"""
Step 2 — Clustering Engine
===========================
Reads all crawled pages from SQLite, sends URLs + titles + H1s to OpenAI,
and groups them into clusters by inferred consumer question.

Each cluster represents ONE real question a user is trying to answer.
Multiple legacy pages may map to the same cluster.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Dict

import sys
import openai
import pandas as pd
import streamlit as st

# Add project root to path for ai_helpers import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_helpers import MODELS, build_messages, build_api_kwargs, extract_json
from ui import apply_theme, sidebar as ui_sidebar, page_header, section_label, stat_row, pill, empty_state  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "crawl_state.db"
CLUSTER_DB_PATH = PROJECT_ROOT / "clusters.db"


def get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_cluster_db() -> None:
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            consumer_question   TEXT NOT NULL,
            theme               TEXT,
            page_group          TEXT DEFAULT 'informational',
            priority            INTEGER DEFAULT 0,
            urls_json           TEXT NOT NULL,
            audience_persona    TEXT,
            search_trigger      TEXT,
            secondary_questions_json TEXT,
            status              TEXT DEFAULT 'draft',
            created_at          TEXT DEFAULT (datetime('now'))
        )
    """)
    # Migrate: add new columns if they don't exist yet
    for col, coltype in [
        ("audience_persona", "TEXT"),
        ("search_trigger", "TEXT"),
        ("secondary_questions_json", "TEXT"),
        ("enrichment_json", "TEXT"),
        ("page_details_json", "TEXT"),
        ("enriched_at", "TEXT"),
        ("business_line", "TEXT DEFAULT 'retail'"),
        ("brief_text", "TEXT"),
        ("input_type", "TEXT DEFAULT 'crawled'"),
    ]:
        try:
            conn.execute("ALTER TABLE clusters ADD COLUMN {} {}".format(col, coltype))
        except Exception:
            pass

    # Cross-cluster analysis table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cross_cluster_analysis (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            content_gaps_json        TEXT,
            cross_cluster_links_json TEXT,
            prioritization_json      TEXT,
            created_at               TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def save_clusters(clusters: List[Dict], replace: bool = True) -> int:
    """Save clusters to DB. If replace=True, deletes old clusters first. Otherwise appends."""
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    if replace:
        conn.execute("DELETE FROM clusters")
    count = 0
    for c in clusters:
        conn.execute(
            "INSERT INTO clusters (consumer_question, theme, page_group, priority, urls_json, "
            "audience_persona, search_trigger, secondary_questions_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                c.get("consumer_question", ""),
                c.get("theme", ""),
                c.get("page_group", "informational"),
                c.get("priority", 0),
                json.dumps(c.get("urls", []), ensure_ascii=False),
                c.get("audience_persona", ""),
                c.get("search_trigger", ""),
                json.dumps(c.get("secondary_questions", []), ensure_ascii=False),
            ),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def load_clusters() -> List[Dict]:
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM clusters ORDER BY theme, cluster_id"
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
        # New fields (may not exist in older DBs)
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
        try:
            d["enriched_at"] = r["enriched_at"]
        except (IndexError, KeyError):
            d["enriched_at"] = None
        # Content Brief fields
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


def update_cluster_status(cluster_id: int, status: str) -> None:
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.execute("UPDATE clusters SET status = ? WHERE cluster_id = ?", (status, cluster_id))
    conn.commit()
    conn.close()


def get_crawled_pages() -> List[Dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT url, title, h1, meta_description, body_text, headings_json FROM pages ORDER BY url"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Clustering prompt
# ---------------------------------------------------------------------------

CLUSTER_SYSTEM_PROMPT = """You are an SEO content strategist for Acko, an Indian digital insurance company.

You are given a list of crawled pages with their URLs, titles, H1 headings, body excerpts, and sub-headings. Your job is to:

1. READ the actual content (body text + headings) to understand what each page covers
2. INFER the SPECIFIC consumer question each page is trying to answer
3. GROUP pages that answer the same or closely adjacent questions into clusters
4. For each cluster, state ONE primary consumer question — make it SPECIFIC, not generic
5. Infer WHO is searching (audience persona) and WHAT triggered the search (search trigger)
6. Infer 2-3 secondary questions readers would also want answered
7. Classify as "transactional" or "informational"
8. INFER a natural theme label (2-5 words)

━━━ SPECIFICITY RULES ━━━

BAD consumer questions (too generic):
  - "What is car insurance?"
  - "How does car insurance work?"
  - "What are the types of car insurance?"

GOOD consumer questions (specific, decision-enabling):
  - "Is zero depreciation add-on worth the extra ₹2,000-3,000 per year?"
  - "How do I transfer my NCB discount when switching insurers?"
  - "What's the real difference between comprehensive and third-party-only cover?"
  - "Which car insurance company has the fastest claim settlement in India?"

The question should reflect what someone would ACTUALLY type into Google or ask a friend.

━━━ CLUSTERING RULES ━━━

- Cluster AGGRESSIVELY — if 5 pages all discuss aspects of "car insurance premium factors", they belong in ONE cluster, not 5 separate ones
- A cluster can contain 1 page (unique topic) or up to 15 pages (many pages on the same question)
- Transactional pages (buy/renew/compare intent) go in a single "Core Product Pages" cluster
- Every informational cluster should have enough source material to write a comprehensive article

━━━ OUTPUT FORMAT ━━━

Return ONLY valid JSON — an array of cluster objects:
[
  {
    "consumer_question": "Is zero depreciation add-on worth the extra cost for your car?",
    "theme": "zero depreciation",
    "page_group": "informational",
    "audience_persona": "New car owner considering add-ons during first insurance purchase",
    "search_trigger": "Buying first car insurance policy, comparing add-on options",
    "secondary_questions": [
      "How much does zero depreciation add-on cost?",
      "Does zero depreciation cover apply after 5 years?",
      "What's the difference between zero dep and bumper-to-bumper cover?"
    ],
    "urls": ["https://www.acko.com/car-insurance/zero-depreciation/", "https://www.acko.com/car-insurance/bumper-replacement/"]
  }
]

CRITICAL: You MUST assign EVERY page to a cluster. Do NOT skip any page.
If a page doesn't fit an existing cluster, create a new one for it.
After clustering, every URL from the input must appear in exactly one cluster.

No markdown fences. No explanation. Only the JSON array.
"""


BATCH_SIZE = 30  # pages per API call — keeps prompt within safe token limits


def _format_page(p: Dict) -> str:
    """Format a single page for the clustering prompt."""
    line = "URL: {}\n  Title: {}\n  H1: {}\n  Meta: {}".format(
        p.get("url", ""),
        p.get("title", ""),
        p.get("h1", ""),
        (p.get("meta_description") or "")[:120],
    )

    # Include first 500 chars of body text for content signals
    body_text = (p.get("body_text") or "")[:500]
    if body_text.strip():
        line += "\n  Body excerpt: {}".format(body_text.strip())

    # Include H2/H3 headings list
    try:
        headings = json.loads(p.get("headings_json") or "[]")
        h_list = []
        for h in headings:
            if isinstance(h, dict):
                tag = h.get("tag", "")
                text = h.get("text", "")
                if tag in ("h2", "h3") and text:
                    h_list.append("{}: {}".format(tag.upper(), text))
        if h_list:
            line += "\n  Headings: {}".format(" | ".join(h_list[:10]))
    except (json.JSONDecodeError, TypeError):
        pass

    return line


def _call_clustering_api(client, model: str, page_lines: List[str],
                         num_pages: int, batch_label: str = "") -> List[Dict]:
    """Make a single clustering API call and parse the response."""
    label = " ({})".format(batch_label) if batch_label else ""
    user_prompt = (
        "Here are {} crawled pages from acko.com{}. "
        "Read the body excerpts and headings carefully, then cluster them by SPECIFIC consumer question.\n"
        "IMPORTANT: Every single URL below must appear in exactly one cluster. Do NOT skip any.\n\n{}"
    ).format(num_pages, label, "\n\n".join(page_lines))

    messages = build_messages(CLUSTER_SYSTEM_PROMPT, user_prompt, model)
    api_kwargs = build_api_kwargs(model, 16384, messages)
    response = client.chat.completions.create(**api_kwargs)

    text = response.choices[0].message.content.strip()

    try:
        clusters = extract_json(text)
        if isinstance(clusters, list):
            return clusters
    except json.JSONDecodeError:
        pass

    return [{"error": "Failed to parse clustering response", "raw": text}]


def run_clustering(api_key: str, pages: List[Dict], model: str = "gpt-4o",
                   status_callback=None) -> List[Dict]:
    """Cluster ALL crawled pages. Batches automatically if > BATCH_SIZE pages.
    Returns a flat list of cluster dicts. Retries for any uncovered pages."""
    client = openai.OpenAI(api_key=api_key)

    # Small page set — single call
    if len(pages) <= BATCH_SIZE:
        page_lines = [_format_page(p) for p in pages]
        return _call_clustering_api(client, model, page_lines, len(pages))

    # Large page set — batch processing
    all_clusters = []  # type: List[Dict]
    total_batches = (len(pages) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(pages))
        batch_pages = pages[start:end]

        if status_callback:
            status_callback("Clustering batch {}/{} ({} pages)...".format(
                batch_idx + 1, total_batches, len(batch_pages)))

        page_lines = [_format_page(p) for p in batch_pages]
        batch_clusters = _call_clustering_api(
            client, model, page_lines, len(batch_pages),
            "batch {}/{}".format(batch_idx + 1, total_batches),
        )

        if batch_clusters and "error" in batch_clusters[0]:
            return batch_clusters  # Propagate error

        all_clusters.extend(batch_clusters)

    # Validation pass: find pages not assigned to any cluster
    all_input_urls = {p.get("url", "") for p in pages}
    clustered_urls = set()
    for c in all_clusters:
        for url in c.get("urls", []):
            clustered_urls.add(url)

    missed_urls = all_input_urls - clustered_urls
    if missed_urls and len(missed_urls) <= 50:
        # Retry for missed pages
        if status_callback:
            status_callback("Clustering {} missed pages...".format(len(missed_urls)))

        missed_pages = [p for p in pages if p.get("url", "") in missed_urls]
        page_lines = [_format_page(p) for p in missed_pages]
        retry_clusters = _call_clustering_api(
            client, model, page_lines, len(missed_pages), "missed pages retry",
        )
        if retry_clusters and "error" not in retry_clusters[0]:
            all_clusters.extend(retry_clusters)

    return all_clusters


# ---------------------------------------------------------------------------
# Phase 2: Cluster Enrichment
# ---------------------------------------------------------------------------

ENRICHMENT_SYSTEM_PROMPT = """You are an SEO content strategist performing a deep analysis of a single content cluster for Acko, an Indian digital insurance company.

You receive:
- The cluster's consumer question, theme, and audience persona
- FULL body text and headings for every page in this cluster

Analyze ALL the source content carefully and return a JSON object with:

{
  "subtopics": ["specific sub-theme 1", "sub-theme 2", "sub-theme 3"],
  "consolidation_strategy": "CREATE_COMPREHENSIVE_GUIDE | MERGE_DUPLICATES | KEEP_AND_LINK | FILL_CONTENT_GAP",
  "user_journey_stage": "awareness | consideration | decision | post_purchase",
  "question_type": "what_is | how_to | comparison | cost | eligibility | process",
  "content_depth_needed": "overview | deep_dive | how_to_guide | comparison_page",
  "suggested_pillar_question": "The ideal H1 for the consolidated article — specific, decision-enabling",
  "estimated_impact": "HIGH | MEDIUM | LOW",
  "page_details": [
    {
      "url": "https://...",
      "content_quality": "THIN | ADEQUATE | COMPREHENSIVE",
      "consolidation_role": "MERGE_INTO_PILLAR | REDIRECT | KEEP_AS_SUPPORTING",
      "quality_rationale": "1-sentence explanation of why this rating"
    }
  ]
}

━━━ FIELD DEFINITIONS ━━━

consolidation_strategy:
  CREATE_COMPREHENSIVE_GUIDE — Multiple thin pages on the same topic → combine into one deep guide
  MERGE_DUPLICATES — Near-duplicate pages with overlapping content → merge and redirect
  KEEP_AND_LINK — Pages cover distinct sub-topics well → keep separate but interlink as hub+spokes
  FILL_CONTENT_GAP — Existing pages are thin and miss key angles → create new comprehensive content

content_quality (per page):
  THIN — < 300 words of useful content, mostly boilerplate, navigation, or generic text
  ADEQUATE — Covers the topic but lacks depth, specific examples, or actionable data
  COMPREHENSIVE — Deep coverage with specific facts, ₹ amounts, examples, and actionable advice

consolidation_role (per page):
  MERGE_INTO_PILLAR — This page's content should be absorbed into the new pillar article
  REDIRECT — This page adds little value; just 301-redirect to the new article
  KEEP_AS_SUPPORTING — This page has unique depth; keep it and link from the pillar

user_journey_stage:
  awareness — "What is...?", "Why do I need...?" (user doesn't know they need this yet)
  consideration — "How to choose...", "What's the difference between..." (evaluating options)
  decision — "Best X for Y", "X vs Y", "How to buy..." (ready to act)
  post_purchase — "How to claim...", "How to renew...", "How to cancel..." (already a customer)

estimated_impact:
  HIGH — High search volume topic + poor existing content = big opportunity
  MEDIUM — Moderate search volume or already adequate content
  LOW — Niche topic or already well-covered

subtopics:
  List 4-8 specific sub-themes that the consolidated article MUST cover.
  Be specific: not "types of insurance" but "comprehensive vs third-party vs own-damage cover".
  Every subtopic should be something a reader would expect to find in a definitive article on this question.

━━━ RULES ━━━

- You MUST include a page_details entry for EVERY URL in the cluster
- subtopics should come from actually reading the source pages, not guessing
- suggested_pillar_question should be better than the current consumer_question — more specific, more decision-enabling
- If all pages are THIN, the strategy is almost always CREATE_COMPREHENSIVE_GUIDE or FILL_CONTENT_GAP

Return ONLY valid JSON. No markdown fences. No explanation.
"""


CROSS_CLUSTER_SYSTEM_PROMPT = """You are an SEO content strategist analyzing ALL content clusters together for Acko insurance.

You receive a summary of every cluster (question, theme, subtopics, impact, strategy).

Analyze them as a whole and return:

{
  "content_gaps": [
    {
      "gap_description": "What topic/question is missing?",
      "why_it_matters": "Why users need this content",
      "suggested_question": "The consumer question for a new article",
      "estimated_impact": "HIGH | MEDIUM | LOW"
    }
  ],
  "cross_cluster_opportunities": [
    {
      "opportunity_type": "INTERNAL_LINKING | PILLAR_SPOKE | CONTENT_SERIES",
      "description": "What to do",
      "clusters_involved": ["cluster question 1", "cluster question 2"]
    }
  ],
  "prioritization": {
    "high_priority": ["cluster question 1", "cluster question 2"],
    "rationale": "Why these should be tackled first"
  }
}

Focus on:
- Topics users clearly search for but no cluster covers well
- Clusters that should link to each other for better SEO
- Which clusters to prioritize based on impact and opportunity size

Return ONLY valid JSON. No markdown fences. No explanation.
"""


def _get_page_data_for_cluster(urls: List[str]) -> List[Dict]:
    """Load full crawled data for all URLs in a cluster."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    pages = []
    for url in urls:
        row = conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
        if row:
            pages.append(dict(row))
    conn.close()
    return pages


def _format_page_full(p: Dict, body_budget: int = 12000) -> str:
    """Format a page with full body text for enrichment analysis."""
    parts = []
    parts.append("URL: {}".format(p.get("url", "")))
    parts.append("Title: {}".format(p.get("title", "")))
    parts.append("H1: {}".format(p.get("h1", "")))
    parts.append("Meta: {}".format((p.get("meta_description") or "")[:200]))

    # Full headings
    try:
        headings = json.loads(p.get("headings_json") or "[]")
        h_lines = []
        for h in headings:
            if isinstance(h, dict):
                h_lines.append("{}: {}".format(h.get("tag", "").upper(), h.get("text", "")))
        if h_lines:
            parts.append("Headings:\n  {}".format("\n  ".join(h_lines)))
    except (json.JSONDecodeError, TypeError):
        pass

    # Body text (up to budget)
    body = (p.get("body_text") or "")[:body_budget]
    if body.strip():
        parts.append("Body text:\n{}".format(body.strip()))

    return "\n".join(parts)


def enrich_cluster(api_key: str, cluster: Dict, model: str = "gpt-4o") -> Dict:
    """Phase 2: Deep-analyze a single cluster with full page content."""
    client = openai.OpenAI(api_key=api_key)

    pages = _get_page_data_for_cluster(cluster.get("urls", []))
    if not pages:
        return {"error": "No crawled page data found for this cluster's URLs"}

    # Dynamic body budget to stay within token limits
    per_page_budget = min(12000, max(2000, 100000 // max(len(pages), 1)))

    page_blocks = []
    for i, p in enumerate(pages):
        page_blocks.append("━━━ PAGE {} ━━━\n{}".format(i + 1, _format_page_full(p, per_page_budget)))

    user_prompt = """Analyze this content cluster:

CONSUMER QUESTION: {question}
THEME: {theme}
AUDIENCE: {audience}
SEARCH TRIGGER: {trigger}
NUMBER OF PAGES: {num_pages}

{pages}

Analyze ALL pages carefully. Return the enrichment JSON.""".format(
        question=cluster.get("consumer_question", ""),
        theme=cluster.get("theme", ""),
        audience=cluster.get("audience_persona", ""),
        trigger=cluster.get("search_trigger", ""),
        num_pages=len(pages),
        pages="\n\n".join(page_blocks),
    )

    enrich_msgs = build_messages(ENRICHMENT_SYSTEM_PROMPT, user_prompt, model)
    enrich_kwargs = build_api_kwargs(model, 4096, enrich_msgs)
    response = client.chat.completions.create(**enrich_kwargs)

    text = response.choices[0].message.content.strip()

    try:
        return extract_json(text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse enrichment response", "raw": text}


def save_enrichment(cluster_id: int, enrichment: Dict) -> None:
    """Save enrichment data to the cluster row."""
    page_details = enrichment.pop("page_details", [])
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.execute(
        "UPDATE clusters SET enrichment_json = ?, page_details_json = ?, enriched_at = datetime('now') "
        "WHERE cluster_id = ?",
        (
            json.dumps(enrichment, ensure_ascii=False),
            json.dumps(page_details, ensure_ascii=False),
            cluster_id,
        ),
    )
    conn.commit()
    conn.close()


def run_cross_cluster_analysis(api_key: str, clusters: List[Dict],
                                model: str = "gpt-4o") -> Dict:
    """Analyze all clusters together for gaps and cross-linking opportunities."""
    client = openai.OpenAI(api_key=api_key)

    cluster_summaries = []
    for c in clusters:
        enrichment = c.get("enrichment", {})
        summary = "- Question: {}\n  Theme: {}\n  Pages: {}\n  Impact: {}\n  Strategy: {}".format(
            c["consumer_question"],
            c.get("theme", ""),
            len(c.get("urls", [])),
            enrichment.get("estimated_impact", "unknown"),
            enrichment.get("consolidation_strategy", "unknown"),
        )
        subtopics = enrichment.get("subtopics", [])
        if subtopics:
            summary += "\n  Subtopics: {}".format(", ".join(subtopics))
        cluster_summaries.append(summary)

    user_prompt = "Here are {} content clusters for acko.com insurance content.\n\n{}\n\nAnalyze them for gaps, linking opportunities, and prioritization.".format(
        len(clusters),
        "\n\n".join(cluster_summaries),
    )

    cross_msgs = build_messages(CROSS_CLUSTER_SYSTEM_PROMPT, user_prompt, model)
    cross_kwargs = build_api_kwargs(model, 8192, cross_msgs)
    response = client.chat.completions.create(**cross_kwargs)

    text = response.choices[0].message.content.strip()

    try:
        return extract_json(text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse cross-cluster analysis", "raw": text}


def save_cross_cluster_analysis(analysis: Dict) -> None:
    """Save cross-cluster analysis to its own table."""
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.execute(
        "INSERT INTO cross_cluster_analysis (content_gaps_json, cross_cluster_links_json, prioritization_json) "
        "VALUES (?, ?, ?)",
        (
            json.dumps(analysis.get("content_gaps", []), ensure_ascii=False),
            json.dumps(analysis.get("cross_cluster_opportunities", []), ensure_ascii=False),
            json.dumps(analysis.get("prioritization", {}), ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def load_cross_cluster_analysis() -> Dict:
    """Load the latest cross-cluster analysis."""
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM cross_cluster_analysis ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return {}
    try:
        return {
            "content_gaps": json.loads(row["content_gaps_json"] or "[]"),
            "cross_cluster_opportunities": json.loads(row["cross_cluster_links_json"] or "[]"),
            "prioritization": json.loads(row["prioritization_json"] or "{}"),
            "created_at": row["created_at"],
        }
    except (json.JSONDecodeError, KeyError):
        return {}


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Clusters — Acko Content Studio", page_icon="●", layout="wide")

    apply_theme()
    ui_sidebar(current="patha")

    page_header(
        eyebrow="Path A · Crawl-based",
        title="Crawl Studio",
        meta="Crawl acko.com → cluster by consumer question → generate",
    )

    init_cluster_db()

    # Sidebar settings
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
            api_key = st.text_input("OpenAI API key", type="password")
        model = st.selectbox("Model", MODELS, index=0, label_visibility="collapsed")

    # Load data
    pages = get_crawled_pages()
    existing_clusters = load_clusters()

    stat_row([
        ("Crawled pages",       f"{len(pages):,}"),
        ("Existing clusters",   str(len(existing_clusters))),
        ("Unclustered pages",   str(max(0, len(pages) - sum(len(c["urls"]) for c in existing_clusters)))),
    ])

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    tab_run, tab_enrich, tab_view = st.tabs(["Run clustering", "Enrich clusters", "View clusters"])

    # ---- TAB: Run Clustering (v2: discover-then-cluster) ----
    with tab_run:
        if not pages:
            st.warning("No crawled pages found. Run the crawler first.")
        else:
            from clustering_v2 import (
                discover_intent_taxonomy, assign_pages_to_intents, consolidate_into_clusters,
            )

            st.markdown("### Pages in corpus")
            df = pd.DataFrame(pages)
            st.dataframe(df[["url", "title", "h1"]], use_container_width=True, height=220)

            st.markdown("---")
            section_label("Step 1 · Discover intents")
            st.caption(
                "LLM reads compact summaries of every page and proposes the consumer intents "
                "present in this corpus. No fixed count — the corpus decides."
            )

            col_a, col_b = st.columns([2, 1])
            with col_a:
                discover_btn = st.button(
                    "Discover intents from corpus",
                    type="primary",
                    use_container_width=True,
                    key="discover_intents_btn",
                )
            with col_b:
                if st.session_state.get("v2_taxonomy"):
                    if st.button("Reset taxonomy", use_container_width=True, key="reset_tax_btn"):
                        st.session_state.pop("v2_taxonomy", None)
                        st.session_state.pop("v2_assignments", None)
                        st.rerun()

            if discover_btn:
                if not api_key:
                    st.error("No API key. Set OPENAI_API_KEY or paste in sidebar.")
                else:
                    status_box = st.empty()
                    try:
                        with st.spinner("Reading corpus and discovering intents…"):
                            taxonomy = discover_intent_taxonomy(
                                api_key, pages, model,
                                status_callback=lambda m: status_box.info(m),
                            )
                        if taxonomy:
                            st.session_state["v2_taxonomy"] = taxonomy
                            status_box.success(
                                "Discovered {} intents. Review/edit below, then run Step 2.".format(len(taxonomy))
                            )
                        else:
                            status_box.error("Discovery returned no intents. Check the model + API key.")
                    except Exception as e:
                        st.error("Discovery error: {}".format(e))

            # ---- Editor checkpoint: review/edit taxonomy ----
            taxonomy = st.session_state.get("v2_taxonomy")
            if taxonomy:
                st.markdown("---")
                section_label("Editor checkpoint · review intents")
                st.caption(
                    "Edit the `name` to rename. Set `keep` to false to drop an intent. "
                    "Pages assigned to a dropped intent will fall through to `__unassigned__` in Step 2."
                )

                tax_df = pd.DataFrame([
                    {
                        "keep": True,
                        "intent_id": t.get("intent_id", ""),
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "stage": t.get("search_stage", ""),
                        "examples": " | ".join(t.get("example_questions", [])[:3]),
                    }
                    for t in taxonomy
                ])
                edited = st.data_editor(
                    tax_df,
                    use_container_width=True,
                    num_rows="fixed",
                    height=min(420, 60 + 36 * len(tax_df)),
                    key="taxonomy_editor",
                    column_config={
                        "keep": st.column_config.CheckboxColumn("Keep", width="small"),
                        "intent_id": st.column_config.TextColumn("Intent ID", disabled=True, width="medium"),
                        "name": st.column_config.TextColumn("Name", width="medium"),
                        "description": st.column_config.TextColumn("Description", width="large"),
                        "stage": st.column_config.TextColumn("Stage", width="small"),
                        "examples": st.column_config.TextColumn("Example questions", disabled=True),
                    },
                )

                # Reconcile edits back into the taxonomy structure
                kept_taxonomy = []
                edited_records = edited.to_dict(orient="records") if hasattr(edited, "to_dict") else list(edited)
                for orig, row in zip(taxonomy, edited_records):
                    if not row.get("keep", True):
                        continue
                    kept_taxonomy.append({
                        **orig,
                        "name": row.get("name") or orig.get("name", ""),
                        "description": row.get("description") or orig.get("description", ""),
                        "search_stage": row.get("stage") or orig.get("search_stage", ""),
                    })

                st.markdown("---")
                section_label("Step 2 · Assign pages & save clusters")
                st.caption(
                    "Each page is mapped to exactly one intent from your edited taxonomy. "
                    "Pages that don't fit any intent are flagged as `__unassigned__` (not silently merged)."
                )

                col1, col2 = st.columns([2, 1])
                with col2:
                    cluster_mode = st.radio(
                        "Save mode",
                        ["Replace all clusters", "Append to existing"],
                        index=0,
                        key="v2_save_mode",
                    )
                with col1:
                    assign_btn = st.button(
                        "Assign pages & save clusters  →",
                        type="primary",
                        use_container_width=True,
                        disabled=len(kept_taxonomy) == 0,
                        key="assign_save_btn",
                    )

                if assign_btn:
                    if not api_key:
                        st.error("No API key. Set OPENAI_API_KEY or paste in sidebar.")
                    else:
                        status_box = st.empty()
                        try:
                            with st.spinner("Assigning {} pages to {} intents…".format(len(pages), len(kept_taxonomy))):
                                assignments = assign_pages_to_intents(
                                    api_key, pages, kept_taxonomy, model,
                                    status_callback=lambda m: status_box.info(m),
                                )
                            clusters = consolidate_into_clusters(kept_taxonomy, assignments, pages)
                            replace = cluster_mode == "Replace all clusters"
                            count = save_clusters(clusters, replace=replace)

                            # Coverage report
                            real = sum(1 for c in clusters if not c.get("is_outlier") and c.get("intent_id") != "__unassigned__")
                            singletons = sum(1 for c in clusters if c.get("is_outlier"))
                            unassigned = sum(len(c["urls"]) for c in clusters if c.get("intent_id") == "__unassigned__")
                            status_box.success(
                                "Saved {} clusters · {} substantive · {} singletons · {} unassigned pages.".format(
                                    count, real, singletons, unassigned
                                )
                            )
                            st.session_state["v2_assignments"] = assignments
                        except Exception as e:
                            st.error("Assignment error: {}".format(e))

    # ---- TAB: Enrich Clusters ----
    with tab_enrich:
        if not existing_clusters:
            st.info("No clusters yet. Run clustering first.")
        else:
            enriched_count = sum(1 for c in existing_clusters if c.get("enriched_at"))
            unenriched = [c for c in existing_clusters if not c.get("enriched_at")]

            st.markdown("### Cluster Enrichment (Phase 2)")
            st.caption(
                "Deep-analyze each cluster's full page content to determine subtopics, "
                "content quality, consolidation strategy, and impact."
            )

            e1, e2, e3 = st.columns(3)
            e1.metric("Total clusters", len(existing_clusters))
            e2.metric("Enriched ✅", enriched_count)
            e3.metric("Pending", len(unenriched))

            st.markdown("---")

            # Cluster table
            for c in existing_clusters:
                enrichment = c.get("enrichment", {})
                status_icon = "✅" if c.get("enriched_at") else "⏳"
                impact = enrichment.get("estimated_impact", "—")
                strategy = enrichment.get("consolidation_strategy", "—")

                cols = st.columns([0.3, 3, 1, 1, 1, 1])
                cols[0].markdown(status_icon)
                cols[1].markdown("**{}**".format(c["consumer_question"][:60]))
                cols[2].caption("{} pages".format(len(c["urls"])))
                cols[3].caption(impact)
                cols[4].caption(strategy[:20] if strategy != "—" else "—")
                cols[5].caption(c.get("enriched_at", "—")[:10] if c.get("enriched_at") else "—")

            st.markdown("---")

            # Enrich All button
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                enrich_all_btn = st.button(
                    "🔬 Enrich All ({} pending)".format(len(unenriched)),
                    type="primary",
                    use_container_width=True,
                    disabled=not unenriched,
                )
            with btn_col2:
                cross_btn = st.button(
                    "🌐 Cross-Cluster Analysis",
                    use_container_width=True,
                    disabled=enriched_count == 0,
                )

            if enrich_all_btn:
                if not api_key:
                    st.error("No API key.")
                else:
                    progress = st.progress(0.0)
                    status_box = st.empty()

                    for i, cluster in enumerate(unenriched):
                        status_box.info("Enriching cluster {}/{}: {}...".format(
                            i + 1, len(unenriched), cluster["consumer_question"][:50]))
                        progress.progress((i + 1) / len(unenriched))

                        try:
                            result = enrich_cluster(api_key, cluster, model)
                            if result and "error" not in result:
                                save_enrichment(cluster["cluster_id"], result)
                            else:
                                status_box.warning("Failed on cluster #{}: {}".format(
                                    cluster["cluster_id"], result.get("error", "unknown")))
                        except Exception as exc:
                            status_box.warning("Error enriching cluster #{}: {}".format(
                                cluster["cluster_id"], exc))

                    status_box.success("Enrichment complete!")
                    st.rerun()

            if cross_btn:
                if not api_key:
                    st.error("No API key.")
                else:
                    with st.spinner("Running cross-cluster analysis..."):
                        try:
                            analysis = run_cross_cluster_analysis(api_key, existing_clusters, model)
                            if analysis and "error" not in analysis:
                                save_cross_cluster_analysis(analysis)
                                st.success("Cross-cluster analysis saved!")
                                st.rerun()
                            else:
                                st.error(analysis.get("error", "Unknown error"))
                        except Exception as exc:
                            st.error("Error: {}".format(exc))

    # ---- TAB: View Clusters ----
    with tab_view:
        if not existing_clusters:
            st.info("No clusters yet. Go to the Run Clustering tab first.")
        else:
            # Summary stats
            info_count = sum(1 for c in existing_clusters if c["page_group"] == "informational")
            tx_count = sum(1 for c in existing_clusters if c["page_group"] == "transactional")
            st.markdown("**{} informational** clusters · **{} transactional** clusters".format(info_count, tx_count))

            # Group by theme
            themes = {}
            for c in existing_clusters:
                t = c.get("theme") or "Uncategorized"
                themes.setdefault(t, []).append(c)

            # Filters
            filt_col1, filt_col2, filt_col3 = st.columns(3)
            with filt_col1:
                filter_group = st.selectbox(
                    "Type",
                    ["All", "informational", "transactional"],
                    index=0,
                )
            with filt_col2:
                impact_options = ["All impacts"] + sorted(set(
                    c.get("enrichment", {}).get("estimated_impact", "")
                    for c in existing_clusters if c.get("enrichment", {}).get("estimated_impact")))
                filter_impact = st.selectbox("Impact", impact_options, index=0)
            with filt_col3:
                journey_options = ["All stages"] + sorted(set(
                    c.get("enrichment", {}).get("user_journey_stage", "")
                    for c in existing_clusters if c.get("enrichment", {}).get("user_journey_stage")))
                filter_journey = st.selectbox("Journey stage", journey_options, index=0)

            for theme_name, theme_clusters in sorted(themes.items()):
                filtered = theme_clusters
                if filter_group != "All":
                    filtered = [c for c in filtered if c["page_group"] == filter_group]
                if filter_impact != "All impacts":
                    filtered = [c for c in filtered if c.get("enrichment", {}).get("estimated_impact") == filter_impact]
                if filter_journey != "All stages":
                    filtered = [c for c in filtered if c.get("enrichment", {}).get("user_journey_stage") == filter_journey]
                if not filtered:
                    continue

                st.markdown("#### {}".format(theme_name.title()))

                for cluster in filtered:
                    group_label = "📄" if cluster["page_group"] == "informational" else "💳"

                    with st.expander(
                        "{} **{}** ({} pages)".format(
                            group_label,
                            cluster["consumer_question"],
                            len(cluster["urls"]),
                        ),
                        expanded=False,
                    ):
                        st.markdown("**Theme:** {}".format(cluster["theme"]))
                        st.markdown("**Type:** {}".format(cluster["page_group"]))
                        st.markdown("**Status:** {}".format(cluster["status"]))
                        if cluster.get("audience_persona"):
                            st.markdown("**Audience:** {}".format(cluster["audience_persona"]))
                        if cluster.get("search_trigger"):
                            st.markdown("**Search trigger:** {}".format(cluster["search_trigger"]))
                        if cluster.get("secondary_questions"):
                            st.markdown("**Secondary questions:**")
                            for sq in cluster["secondary_questions"]:
                                st.caption("→ {}".format(sq))

                        # Enrichment data (Phase 2)
                        enrichment = cluster.get("enrichment", {})
                        if enrichment:
                            st.markdown("---")
                            st.markdown("**🔬 Enrichment Analysis**")
                            ec1, ec2, ec3 = st.columns(3)
                            ec1.markdown("**Strategy:** {}".format(
                                enrichment.get("consolidation_strategy", "—").replace("_", " ").title()))
                            ec2.markdown("**Journey:** {}".format(
                                enrichment.get("user_journey_stage", "—").replace("_", " ").title()))
                            ec3.markdown("**Impact:** {}".format(
                                enrichment.get("estimated_impact", "—")))

                            st.markdown("**Question type:** {} · **Depth needed:** {}".format(
                                enrichment.get("question_type", "—").replace("_", " "),
                                enrichment.get("content_depth_needed", "—").replace("_", " ")))

                            if enrichment.get("suggested_pillar_question"):
                                st.info("💡 **Suggested H1:** {}".format(enrichment["suggested_pillar_question"]))

                            subtopics = enrichment.get("subtopics", [])
                            if subtopics:
                                st.markdown("**Subtopics to cover:**")
                                for sub in subtopics:
                                    st.caption("  • {}".format(sub))
                            st.markdown("---")

                        # Source pages (with quality ratings if enriched)
                        page_details = cluster.get("page_details", [])
                        quality_map = {pdet.get("url", ""): pdet for pdet in page_details}

                        st.markdown("**Source pages:**")
                        for url in cluster["urls"]:
                            pdet = quality_map.get(url, {})
                            if pdet:
                                qi = {"THIN": "🔴", "ADEQUATE": "🟡", "COMPREHENSIVE": "🟢"}.get(
                                    pdet.get("content_quality", ""), "⚪")
                                st.markdown("- {} [{}]({}) — **{}** · {}".format(
                                    qi, url, url,
                                    pdet.get("content_quality", "?"),
                                    pdet.get("consolidation_role", "?").replace("_", " ").lower()))
                                if pdet.get("quality_rationale"):
                                    st.caption("    {}".format(pdet["quality_rationale"]))
                            else:
                                st.markdown("- [{}]({})".format(url, url))

                        col_a, col_b, col_c = st.columns(3)
                        with col_a:
                            if st.button("✅ Ready", key="ready_{}".format(cluster["cluster_id"])):
                                update_cluster_status(cluster["cluster_id"], "ready")
                                st.rerun()
                        with col_b:
                            if st.button("⏸️ Skip", key="skip_{}".format(cluster["cluster_id"])):
                                update_cluster_status(cluster["cluster_id"], "skipped")
                                st.rerun()
                        with col_c:
                            if st.button("🗑️ Remove", key="remove_{}".format(cluster["cluster_id"])):
                                conn = sqlite3.connect(str(CLUSTER_DB_PATH))
                                conn.execute("DELETE FROM clusters WHERE cluster_id = ?", (cluster["cluster_id"],))
                                conn.commit()
                                conn.close()
                                st.rerun()

            # ---- Cross-cluster analysis ----
            cross_analysis = load_cross_cluster_analysis()
            if cross_analysis:
                st.markdown("---")
                st.markdown("### 🌐 Cross-Cluster Analysis")
                st.caption("Last updated: {}".format(cross_analysis.get("created_at", "—")))

                # Content gaps
                gaps = cross_analysis.get("content_gaps", [])
                if gaps:
                    st.markdown("#### Content Gaps")
                    for gap in gaps:
                        with st.container(border=True):
                            g1, g2 = st.columns([3, 1])
                            g1.markdown("**{}**".format(gap.get("gap_description", "")))
                            g2.markdown("Impact: **{}**".format(gap.get("estimated_impact", "—")))
                            if gap.get("why_it_matters"):
                                st.caption(gap["why_it_matters"])
                            if gap.get("suggested_question"):
                                st.info("💡 Suggested: {}".format(gap["suggested_question"]))

                # Cross-cluster opportunities
                opps = cross_analysis.get("cross_cluster_opportunities", [])
                if opps:
                    st.markdown("#### Linking & Series Opportunities")
                    for opp in opps:
                        with st.container(border=True):
                            st.markdown("**{}** — {}".format(
                                opp.get("opportunity_type", "").replace("_", " "),
                                opp.get("description", "")))
                            clusters_involved = opp.get("clusters_involved", [])
                            if clusters_involved:
                                st.caption("Clusters: {}".format(" ↔ ".join(clusters_involved)))

                # Prioritization
                prio = cross_analysis.get("prioritization", {})
                if prio.get("high_priority"):
                    st.markdown("#### 🎯 High Priority Clusters")
                    for hp in prio["high_priority"]:
                        st.markdown("- **{}**".format(hp))
                    if prio.get("rationale"):
                        st.caption(prio["rationale"])


main()
