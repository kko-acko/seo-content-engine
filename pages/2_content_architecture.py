"""
Step 2 — Content Architecture
==============================
Mines question signals from crawled pages, builds a complete question universe,
maps coverage, enriches with external data, and produces a prioritised content
roadmap with actions (merge / deepen / create / redirect / keep).

The output feeds into the existing Generate pipeline via "Export to Clusters".
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse, quote_plus

import openai
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRAWL_DB = PROJECT_ROOT / "crawl_state.db"
ARCH_DB = PROJECT_ROOT / "content_arch.db"
CLUSTER_DB = PROJECT_ROOT / "clusters.db"


def _get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_arch_db():
    conn = sqlite3.connect(str(ARCH_DB))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS question_signals (
            signal_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url          TEXT NOT NULL,
            signal_type         TEXT NOT NULL,
            raw_text            TEXT NOT NULL,
            normalized_question TEXT,
            theme_hint          TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS question_universe (
            question_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            theme           TEXT NOT NULL,
            sub_theme       TEXT,
            question_text   TEXT NOT NULL,
            persona         TEXT,
            parent_id       INTEGER REFERENCES question_universe(question_id),
            source          TEXT DEFAULT 'ai_generated',
            demand_hint     TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS coverage_map (
            mapping_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id     INTEGER NOT NULL REFERENCES question_universe(question_id),
            page_url        TEXT,
            coverage_status TEXT NOT NULL,
            coverage_score  INTEGER,
            ai_reasoning    TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS external_signals (
            signal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id     INTEGER REFERENCES question_universe(question_id),
            theme           TEXT,
            signal_type     TEXT NOT NULL,
            signal_text     TEXT NOT NULL,
            source_url      TEXT,
            fetched_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS content_decisions (
            decision_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            theme           TEXT NOT NULL,
            sub_theme       TEXT,
            target_question TEXT NOT NULL,
            action          TEXT NOT NULL,
            source_urls_json TEXT,
            redirect_target TEXT,
            priority_score  REAL,
            search_demand   INTEGER,
            authority_fit   INTEGER,
            gap_severity    INTEGER,
            ai_reasoning    TEXT,
            status          TEXT DEFAULT 'proposed',
            cluster_id      INTEGER,
            created_at      TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def _q(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _exec(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def _exec_many(db_path, sql, rows):
    conn = sqlite3.connect(str(db_path))
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


def _count(db_path, table):
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _clear_table(table):
    conn = sqlite3.connect(str(ARCH_DB))
    conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Crawled page helpers
# ---------------------------------------------------------------------------

def get_crawled_pages() -> List[Dict]:
    if not CRAWL_DB.exists():
        return []
    return _q(CRAWL_DB, "SELECT url, title, h1, meta_description, headings_json, body_text FROM pages ORDER BY url")


def extract_raw_signals(pages: List[Dict]) -> List[Dict]:
    """Extract all headings + titles as raw question signals from crawled pages."""
    signals = []
    for p in pages:
        url = p.get("url", "")
        # Title
        title = (p.get("title") or "").strip()
        if title and len(title) > 10:
            signals.append({"source_url": url, "signal_type": "title", "raw_text": title})
        # H1
        h1 = (p.get("h1") or "").strip()
        if h1 and len(h1) > 5 and h1 != title:
            signals.append({"source_url": url, "signal_type": "h1", "raw_text": h1})
        # H2, H3 from headings_json
        try:
            headings = json.loads(p.get("headings_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            headings = []
        for h in headings:
            if isinstance(h, dict):
                tag = (h.get("tag") or h.get("level") or "").upper()
                text = (h.get("text") or "").strip()
                if text and len(text) > 5 and tag in ("H2", "H3"):
                    signals.append({"source_url": url, "signal_type": tag.lower(), "raw_text": text})
    return signals


# ---------------------------------------------------------------------------
# AI prompts
# ---------------------------------------------------------------------------

MINE_SIGNALS_SYSTEM = """You are an SEO content analyst for Acko, an Indian digital insurance company.

You receive raw headings (H1, H2, H3) and page titles extracted from crawled car insurance pages.

Your job:
1. For each signal, infer the IMPLICIT QUESTION a reader would search.
   - H2 "Key Differences Between Cashless and Reimbursement" → "What are the differences between cashless and reimbursement car insurance claims?"
   - Title "Zero Depreciation Car Insurance - Acko" → "What is zero depreciation car insurance and is it worth it?"
2. Normalize each into a clean, natural-language question (how a real person would type it into Google)
3. Assign a rough theme label (2-4 words, e.g., "claim process", "coverage types", "renewal")
4. DEDUPLICATE: if multiple signals map to the same question, output ONE entry with all source URLs

Return a JSON array:
[
  {
    "normalized_question": "What is the difference between cashless and reimbursement claims?",
    "theme_hint": "claim process",
    "sources": [
      {"url": "https://...", "raw_text": "Key Differences Between Cashless...", "type": "h2"},
      {"url": "https://...", "raw_text": "Cashless vs Reimbursement Claims", "type": "title"}
    ]
  }
]

Rules:
- Be aggressive about deduplication — "What is IDV?" and "IDV in Car Insurance Explained" are the SAME question
- Skip signals that are navigation elements ("Home", "Contact Us") or too generic ("Car Insurance")
- Every output question must be specific and searchable
- Return ONLY valid JSON. No markdown fences."""

UNIVERSE_SYSTEM = """You are a content strategist building the COMPLETE question map for car insurance buyers in India.

You receive two inputs:
1. Question signals mined from an existing corpus of pages (real questions the current site tries to answer)
2. The domain context: "{domain_context}"

Your job: Create the IDEAL question taxonomy. This is NOT limited to what the existing site covers — include what SHOULD exist.

Structure:
- 8-12 top-level THEMES
- 2-5 SUB-THEMES per theme
- 3-8 SPECIFIC QUESTIONS per sub-theme
- Each question tagged with:
  - persona: "first_time_buyer", "renewer", "claimant", "comparison_shopper", "anxious_confused"
  - source: "mined_from_corpus" (matches a signal from existing site) or "ai_generated" (gap you identified)
  - demand: "high", "medium", "low"

Suggested themes (adapt as needed):
- Buying your first policy
- Understanding coverage types
- Add-ons & extras
- Premium & pricing
- Making a claim
- Renewal & switching
- Comparing options
- Regulatory & legal
- Regional & vehicle-specific
- Digital & online insurance

Target: 300-500 total questions.

Return JSON:
{
  "themes": [
    {
      "theme": "Understanding coverage types",
      "sub_themes": [
        {
          "sub_theme": "Comprehensive vs third-party",
          "questions": [
            {
              "question_text": "What is the difference between comprehensive and third-party car insurance?",
              "persona": "first_time_buyer",
              "source": "mined_from_corpus",
              "demand": "high"
            }
          ]
        }
      ]
    }
  ]
}

Return ONLY valid JSON. No markdown fences."""

COVERAGE_SYSTEM = """You are a content coverage analyst for Acko.

You receive:
1. A list of questions from the ideal question taxonomy (for one theme)
2. A list of crawled pages with their titles, H1s, and body text snippets

For EACH question, determine:
- Which existing page(s) attempt to answer it (by URL). A page "covers" a question if its title/H1/body addresses that question's topic.
- coverage_status:
  "covered" = a good, substantial page exists that answers this well
  "thin" = a page exists but is shallow, outdated, or incomplete
  "duplicate" = multiple pages cover essentially the same ground
  "gap" = no existing page meaningfully addresses this question
- coverage_score: 1-5 (5=excellent coverage, 1=barely touched, 0=gap)
- Brief reasoning (1 sentence)

Return JSON array:
[
  {
    "question_id": 1,
    "question_text": "What is comprehensive car insurance?",
    "coverage_status": "covered",
    "coverage_score": 4,
    "page_urls": ["https://www.acko.com/car-insurance/comprehensive/"],
    "reasoning": "Dedicated page with detailed explanation, though lacks comparison table"
  }
]

Return ONLY valid JSON. No markdown fences."""

ROADMAP_SYSTEM = """You are a senior content strategist deciding the content architecture for Acko's car insurance section.

You receive:
1. The question universe (themes → sub-themes → questions)
2. Coverage mapping (which questions are covered, thin, duplicate, or gap)
3. External signals (optional: People Also Ask, competitor coverage, trends)

For each sub-theme (NOT each individual question), recommend ONE action:

- MERGE: Multiple thin/duplicate pages exist covering questions in this sub-theme. Consolidate into one authoritative article answering the primary question + related ones.
- DEEPEN: A page exists but is thin or outdated. Regenerate with more depth.
- CREATE: No page exists for this important sub-theme. New content needed.
- REDIRECT: Clear duplicate at sub-theme level. 301 redirect weaker pages to stronger one.
- KEEP: Existing coverage is already strong. No action needed.

For each decision provide:
- target_question: the primary question this article will answer
- action: merge/deepen/create/redirect/keep
- source_urls: existing URLs involved (empty array for CREATE)
- search_demand: 1-10 (how much search volume this topic likely has)
- authority_fit: 1-10 (how well Acko can answer this authoritatively)
- gap_severity: 1-10 (how badly this gap hurts — 10 for total gap on high-demand topic)
- reasoning: 1-2 sentences

Return JSON array:
[
  {
    "theme": "Add-ons & extras",
    "sub_theme": "Types of add-ons",
    "target_question": "What are the different types of car insurance add-ons and when do you need them?",
    "action": "merge",
    "source_urls": ["https://...", "https://..."],
    "search_demand": 8,
    "authority_fit": 9,
    "gap_severity": 6,
    "reasoning": "5 thin pages each covering 1-2 add-ons. Merge into one comprehensive guide covering all 7 add-ons with comparison table."
  }
]

Return ONLY valid JSON. No markdown fences."""


# ---------------------------------------------------------------------------
# AI calls
# ---------------------------------------------------------------------------

def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _call_openai(api_key: str, system: str, user: str, model: str = "gpt-4o",
                 max_tokens: int = 8192) -> dict | list:
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = _strip_json_fences(resp.choices[0].message.content)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Tab 1: Mine Signals
# ---------------------------------------------------------------------------

def run_mine_signals(api_key: str, model: str, progress_cb=None):
    """Extract raw signals from crawled pages, then AI-normalize and deduplicate."""
    pages = get_crawled_pages()
    if not pages:
        return 0

    raw_signals = extract_raw_signals(pages)
    if not raw_signals:
        return 0

    # Batch signals for AI (50 pages worth at a time)
    BATCH_SIZE = 80
    all_normalized = []

    for i in range(0, len(raw_signals), BATCH_SIZE):
        batch = raw_signals[i:i + BATCH_SIZE]
        user_prompt = "Here are {} raw signals from crawled car insurance pages:\n\n".format(len(batch))
        for s in batch:
            user_prompt += "- [{}] {}: \"{}\"\n".format(s["signal_type"], s["source_url"].split("/")[-2] if "/" in s["source_url"] else s["source_url"], s["raw_text"])

        try:
            result = _call_openai(api_key, MINE_SIGNALS_SYSTEM, user_prompt, model)
            if isinstance(result, list):
                all_normalized.extend(result)
        except Exception as e:
            st.warning("Batch {} failed: {}".format(i // BATCH_SIZE + 1, str(e)[:100]))

        if progress_cb:
            progress_cb(min((i + BATCH_SIZE) / len(raw_signals), 1.0))

    # Save to DB
    _clear_table("question_signals")
    rows = []
    for item in all_normalized:
        q = item.get("normalized_question", "")
        theme = item.get("theme_hint", "")
        for src in item.get("sources", []):
            rows.append((
                src.get("url", ""),
                src.get("type", "ai_inferred"),
                src.get("raw_text", ""),
                q,
                theme,
            ))
        # If no sources listed, save with empty URL
        if not item.get("sources"):
            rows.append(("", "ai_inferred", q, q, theme))

    if rows:
        _exec_many(ARCH_DB,
                    "INSERT INTO question_signals (source_url, signal_type, raw_text, normalized_question, theme_hint) VALUES (?,?,?,?,?)",
                    rows)

    return len(all_normalized)


# ---------------------------------------------------------------------------
# Tab 2: Question Universe
# ---------------------------------------------------------------------------

def run_build_universe(api_key: str, model: str, domain_context: str):
    """Build the complete question taxonomy from mined signals."""
    signals = _q(ARCH_DB, "SELECT DISTINCT normalized_question, theme_hint FROM question_signals WHERE normalized_question IS NOT NULL")
    if not signals:
        return 0

    # Build user prompt with all mined signals
    user_prompt = "MINED QUESTION SIGNALS FROM EXISTING PAGES ({} unique questions):\n\n".format(len(signals))
    for s in signals:
        user_prompt += "- [{}] {}\n".format(s["theme_hint"] or "unknown", s["normalized_question"])

    system = UNIVERSE_SYSTEM.replace("{domain_context}", domain_context)

    result = _call_openai(api_key, system, user_prompt, model, max_tokens=16384)

    # Parse and save
    _clear_table("question_universe")
    count = 0
    themes = result.get("themes", []) if isinstance(result, dict) else result

    conn = sqlite3.connect(str(ARCH_DB))
    for t in themes:
        theme_name = t.get("theme", "")
        for st_item in t.get("sub_themes", []):
            sub_theme = st_item.get("sub_theme", "")
            for q in st_item.get("questions", []):
                conn.execute(
                    """INSERT INTO question_universe
                       (theme, sub_theme, question_text, persona, source, demand_hint)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (theme_name, sub_theme, q.get("question_text", ""),
                     q.get("persona", ""), q.get("source", "ai_generated"),
                     q.get("demand", "medium"))
                )
                count += 1
    conn.commit()
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Tab 3: Coverage Map
# ---------------------------------------------------------------------------

def run_coverage_map(api_key: str, model: str, progress_cb=None):
    """Map questions from universe to existing crawled pages."""
    questions = _q(ARCH_DB, "SELECT question_id, theme, sub_theme, question_text FROM question_universe ORDER BY theme, sub_theme")
    pages = get_crawled_pages()

    if not questions or not pages:
        return 0

    # Build page summaries for the AI
    page_summaries = []
    for p in pages:
        title = p.get("title", "")
        h1 = p.get("h1", "")
        body = (p.get("body_text") or "")[:500]
        page_summaries.append({
            "url": p["url"],
            "title": title,
            "h1": h1,
            "snippet": body,
        })

    # Batch by theme
    themes = {}
    for q in questions:
        themes.setdefault(q["theme"], []).append(q)

    _clear_table("coverage_map")
    total = 0
    done = 0

    for theme_name, theme_qs in themes.items():
        # Build user prompt
        user_prompt = "THEME: {}\n\nQUESTIONS ({}):\n".format(theme_name, len(theme_qs))
        for q in theme_qs:
            user_prompt += "  [ID:{}] {}\n".format(q["question_id"], q["question_text"])

        user_prompt += "\nEXISTING PAGES ({}):\n".format(len(page_summaries))
        for p in page_summaries:
            user_prompt += "  URL: {}\n  Title: {}\n  H1: {}\n  Snippet: {}...\n\n".format(
                p["url"], p["title"], p["h1"], p["snippet"][:200])

        try:
            result = _call_openai(api_key, COVERAGE_SYSTEM, user_prompt, model, max_tokens=8192)
            if isinstance(result, list):
                conn = sqlite3.connect(str(ARCH_DB))
                for item in result:
                    qid = item.get("question_id")
                    status = item.get("coverage_status", "gap")
                    score = item.get("coverage_score", 0)
                    reasoning = item.get("reasoning", "")
                    page_urls = item.get("page_urls", [])
                    if page_urls:
                        for url in page_urls:
                            conn.execute(
                                "INSERT INTO coverage_map (question_id, page_url, coverage_status, coverage_score, ai_reasoning) VALUES (?,?,?,?,?)",
                                (qid, url, status, score, reasoning))
                    else:
                        conn.execute(
                            "INSERT INTO coverage_map (question_id, page_url, coverage_status, coverage_score, ai_reasoning) VALUES (?,?,?,?,?)",
                            (qid, None, status, score, reasoning))
                    total += 1
                conn.commit()
                conn.close()
        except Exception as e:
            st.warning("Coverage mapping for theme '{}' failed: {}".format(theme_name, str(e)[:100]))

        done += 1
        if progress_cb:
            progress_cb(done / len(themes))

    return total


# ---------------------------------------------------------------------------
# Tab 4: External Enrichment
# ---------------------------------------------------------------------------

def fetch_google_suggest(query: str) -> List[str]:
    """Fetch Google Autocomplete suggestions for a query."""
    import urllib.request
    url = "http://suggestqueries.google.com/complete/search?client=firefox&q={}".format(
        quote_plus(query))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data[1] if len(data) > 1 else []
    except Exception:
        return []


def run_enrichment(themes_to_enrich: List[str]):
    """Fetch external signals for selected themes."""
    conn = sqlite3.connect(str(ARCH_DB))
    total = 0

    for theme in themes_to_enrich:
        queries = [
            "car insurance {} India".format(theme),
            "{} car insurance".format(theme),
            "what is {} in car insurance".format(theme),
            "how to {} car insurance".format(theme),
        ]
        for query in queries:
            suggestions = fetch_google_suggest(query)
            for s in suggestions:
                if s.lower() != query.lower():
                    conn.execute(
                        "INSERT INTO external_signals (theme, signal_type, signal_text) VALUES (?,?,?)",
                        (theme, "search_suggest", s))
                    total += 1

    conn.commit()
    conn.close()
    return total


# ---------------------------------------------------------------------------
# Tab 5: Content Roadmap
# ---------------------------------------------------------------------------

def run_roadmap(api_key: str, model: str):
    """Generate content architecture decisions."""
    questions = _q(ARCH_DB, """
        SELECT qu.question_id, qu.theme, qu.sub_theme, qu.question_text, qu.persona, qu.source, qu.demand_hint,
               cm.coverage_status, cm.coverage_score, cm.page_url, cm.ai_reasoning
        FROM question_universe qu
        LEFT JOIN coverage_map cm ON qu.question_id = cm.question_id
        ORDER BY qu.theme, qu.sub_theme
    """)

    ext_signals = _q(ARCH_DB, "SELECT theme, signal_type, signal_text FROM external_signals")

    if not questions:
        return 0

    # Build user prompt — grouped by theme
    user_prompt = "QUESTION UNIVERSE WITH COVERAGE DATA:\n\n"
    current_theme = ""
    current_sub = ""
    for q in questions:
        if q["theme"] != current_theme:
            current_theme = q["theme"]
            user_prompt += "\n━━━ THEME: {} ━━━\n".format(current_theme)
        if q["sub_theme"] != current_sub:
            current_sub = q["sub_theme"]
            user_prompt += "\n  SUB-THEME: {}\n".format(current_sub)
        status = q.get("coverage_status") or "gap"
        score = q.get("coverage_score") or 0
        url = q.get("page_url") or "—"
        user_prompt += "    [{}] {} | status={} score={} url={}\n".format(
            q["question_id"], q["question_text"], status, score, url)

    if ext_signals:
        user_prompt += "\n\nEXTERNAL SIGNALS:\n"
        for s in ext_signals:
            user_prompt += "  [{}] {}: {}\n".format(s["theme"], s["signal_type"], s["signal_text"])

    result = _call_openai(api_key, ROADMAP_SYSTEM, user_prompt, model, max_tokens=16384)

    _clear_table("content_decisions")
    count = 0
    conn = sqlite3.connect(str(ARCH_DB))
    for item in (result if isinstance(result, list) else []):
        priority = (item.get("search_demand", 5) * item.get("authority_fit", 5) * item.get("gap_severity", 5)) / 100.0
        priority = round(min(priority * 2, 10), 1)  # normalize to 1-10
        conn.execute(
            """INSERT INTO content_decisions
               (theme, sub_theme, target_question, action, source_urls_json,
                priority_score, search_demand, authority_fit, gap_severity, ai_reasoning)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (item.get("theme", ""), item.get("sub_theme", ""),
             item.get("target_question", ""), item.get("action", "create"),
             json.dumps(item.get("source_urls", []), ensure_ascii=False),
             priority,
             item.get("search_demand", 5), item.get("authority_fit", 5),
             item.get("gap_severity", 5), item.get("reasoning", ""))
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def export_to_clusters(decisions: List[Dict]):
    """Export approved content decisions to clusters.db for the Generate pipeline."""
    # Ensure clusters DB exists
    conn = sqlite3.connect(str(CLUSTER_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            consumer_question TEXT NOT NULL,
            theme            TEXT,
            page_group       TEXT DEFAULT 'informational',
            priority         INTEGER DEFAULT 0,
            urls_json        TEXT NOT NULL,
            status           TEXT DEFAULT 'draft',
            created_at       TEXT DEFAULT (datetime('now'))
        )
    """)

    exported = 0
    for d in decisions:
        urls = json.loads(d.get("source_urls_json", "[]"))
        priority = int(d.get("priority_score", 5))
        conn.execute(
            """INSERT INTO clusters (consumer_question, theme, page_group, priority, urls_json, status)
               VALUES (?, ?, 'informational', ?, ?, 'ready')""",
            (d["target_question"], d.get("theme", ""),
             priority, json.dumps(urls, ensure_ascii=False))
        )
        # Update decision status
        exported += 1

    conn.commit()
    conn.close()

    # Mark decisions as exported
    arch_conn = sqlite3.connect(str(ARCH_DB))
    for d in decisions:
        arch_conn.execute("UPDATE content_decisions SET status='in_progress' WHERE decision_id=?",
                          (d["decision_id"],))
    arch_conn.commit()
    arch_conn.close()

    return exported


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

ACTION_COLORS = {
    "merge": "#7C3AED",   # purple
    "deepen": "#2563EB",  # blue
    "create": "#059669",  # green
    "redirect": "#D97706",# amber
    "keep": "#6B7280",    # gray
}

STATUS_COLORS = {
    "covered": "#059669",
    "thin": "#D97706",
    "duplicate": "#DC2626",
    "gap": "#EF4444",
}


def main():
    st.set_page_config(page_title="Content Architecture — Acko SEO", page_icon="🏗️", layout="wide")

    st.markdown("""<style>
    .block-container { padding-top: 1rem !important; max-width: 1200px !important; }
    [data-testid="metric-container"] { background: #f8f9fa; padding: 8px 12px; border-radius: 8px; }
    .action-badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.75rem;
        font-weight:700; color:white; text-transform:uppercase; letter-spacing:1px; }
    </style>""", unsafe_allow_html=True)

    init_arch_db()

    # ---- Sidebar ----
    deployment_key = _get_openai_key()
    with st.sidebar:
        st.markdown("**acko** Content Studio")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_crawler.py", label="1. Crawl", icon="🕷️")
        st.page_link("pages/2_content_architecture.py", label="2. Architecture", icon="🏗️")
        st.page_link("pages/3_generate.py", label="3. Generate", icon="✍️")
        st.page_link("pages/4_evaluate.py", label="4. Evaluate", icon="📊")
        st.divider()
        if deployment_key:
            api_key = deployment_key
            st.success("API key active", icon="🔑")
        else:
            api_key = st.text_input("OpenAI API key", type="password", placeholder="sk-...")
        model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"], index=0)
        st.divider()

        # Quick stats
        st.caption("Architecture stats")
        c1, c2 = st.columns(2)
        c1.metric("Signals", _count(ARCH_DB, "question_signals") if ARCH_DB.exists() else 0)
        c2.metric("Questions", _count(ARCH_DB, "question_universe") if ARCH_DB.exists() else 0)
        c3, c4 = st.columns(2)
        c3.metric("Mapped", _count(ARCH_DB, "coverage_map") if ARCH_DB.exists() else 0)
        c4.metric("Decisions", _count(ARCH_DB, "content_decisions") if ARCH_DB.exists() else 0)

    # ---- Title ----
    st.markdown("## Content Architecture")
    st.caption("Map the question space → identify gaps → build the content roadmap")

    # ---- Tabs ----
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "1. Mine Signals",
        "2. Question Universe",
        "3. Coverage Map",
        "4. Enrich",
        "5. Content Roadmap",
    ])

    # ==================================================================
    # TAB 1: Mine Signals
    # ==================================================================
    with tab1:
        st.markdown("### Mine Question Signals")
        st.caption("Extract implicit questions from crawled page headings, titles, and H1s")

        pages = get_crawled_pages()
        if not pages:
            st.warning("No crawled pages found. Run the **Crawl** step first.")
        else:
            st.info("{} crawled pages available".format(len(pages)))

            # Show existing signals if any
            existing = _q(ARCH_DB, "SELECT DISTINCT normalized_question, theme_hint FROM question_signals WHERE normalized_question IS NOT NULL ORDER BY theme_hint")
            if existing:
                st.success("{} question signals already mined".format(len(existing)))
                df = pd.DataFrame(existing)
                df.columns = ["Question", "Theme"]
                st.dataframe(df, use_container_width=True, height=400)

            col_run, col_clear = st.columns([3, 1])
            with col_run:
                if st.button("Extract Question Signals", type="primary", use_container_width=True,
                             disabled=not api_key):
                    if not api_key:
                        st.error("Set your OpenAI API key.")
                    else:
                        progress = st.progress(0)
                        with st.spinner("Mining question signals from {} pages...".format(len(pages))):
                            count = run_mine_signals(api_key, model, progress_cb=lambda p: progress.progress(p))
                        st.success("Extracted {} unique question signals".format(count))
                        st.rerun()
            with col_clear:
                if st.button("Clear", use_container_width=True):
                    _clear_table("question_signals")
                    st.rerun()

    # ==================================================================
    # TAB 2: Question Universe
    # ==================================================================
    with tab2:
        st.markdown("### Question Universe")
        st.caption("Build the complete taxonomy of questions a car insurance buyer needs answered")

        signal_count = _count(ARCH_DB, "question_signals")
        if signal_count == 0:
            st.warning("Run **Mine Signals** first (Tab 1).")
        else:
            domain_context = st.text_input("Domain context", value="car insurance in India",
                                           help="The domain/topic for the question universe")

            universe = _q(ARCH_DB, "SELECT * FROM question_universe ORDER BY theme, sub_theme, question_id")

            if universe:
                # Summary metrics
                themes = set(q["theme"] for q in universe)
                mined = sum(1 for q in universe if q["source"] == "mined_from_corpus")
                gaps = sum(1 for q in universe if q["source"] == "ai_generated")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Questions", len(universe))
                m2.metric("Themes", len(themes))
                m3.metric("From Corpus", mined)
                m4.metric("AI-Identified Gaps", gaps)

                # Filter
                persona_filter = st.multiselect("Filter by persona",
                    ["first_time_buyer", "renewer", "claimant", "comparison_shopper", "anxious_confused"],
                    default=[])
                source_filter = st.multiselect("Filter by source",
                    ["mined_from_corpus", "ai_generated"], default=[])

                filtered = universe
                if persona_filter:
                    filtered = [q for q in filtered if q["persona"] in persona_filter]
                if source_filter:
                    filtered = [q for q in filtered if q["source"] in source_filter]

                # Display by theme → sub-theme
                current_theme = ""
                for q in filtered:
                    if q["theme"] != current_theme:
                        current_theme = q["theme"]
                        st.markdown("#### {}".format(current_theme))

                    source_badge = "🔵" if q["source"] == "mined_from_corpus" else "🟠"
                    demand = q.get("demand_hint", "")
                    demand_badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(demand, "⚪")
                    st.caption("{} {} {} — _{}_  {}".format(
                        source_badge, demand_badge,
                        q["question_text"],
                        q.get("sub_theme", ""),
                        q.get("persona", "")))

            col_build, col_clear2 = st.columns([3, 1])
            with col_build:
                btn_label = "Rebuild Question Universe" if universe else "Build Question Universe"
                if st.button(btn_label, type="primary", use_container_width=True,
                             disabled=not api_key):
                    with st.spinner("Building question taxonomy with {} — this takes 30-60s...".format(model)):
                        count = run_build_universe(api_key, model, domain_context)
                    st.success("Built taxonomy with {} questions".format(count))
                    st.rerun()
            with col_clear2:
                if st.button("Clear", use_container_width=True, key="clear_universe"):
                    _clear_table("question_universe")
                    _clear_table("coverage_map")
                    st.rerun()

    # ==================================================================
    # TAB 3: Coverage Map
    # ==================================================================
    with tab3:
        st.markdown("### Coverage Map")
        st.caption("Which questions are covered by existing pages? Where are the gaps?")

        q_count = _count(ARCH_DB, "question_universe")
        if q_count == 0:
            st.warning("Build the **Question Universe** first (Tab 2).")
        else:
            coverage = _q(ARCH_DB, """
                SELECT qu.question_id, qu.theme, qu.sub_theme, qu.question_text,
                       cm.coverage_status, cm.coverage_score, cm.page_url, cm.ai_reasoning
                FROM question_universe qu
                LEFT JOIN coverage_map cm ON qu.question_id = cm.question_id
                ORDER BY qu.theme, qu.sub_theme
            """)

            mapped = [c for c in coverage if c.get("coverage_status")]
            if mapped:
                # Summary
                statuses = {}
                for c in mapped:
                    s = c["coverage_status"]
                    statuses[s] = statuses.get(s, 0) + 1
                total = len(mapped)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Covered", statuses.get("covered", 0))
                m2.metric("Thin", statuses.get("thin", 0))
                m3.metric("Duplicate", statuses.get("duplicate", 0))
                m4.metric("Gap", statuses.get("gap", 0))

                # Coverage % bar
                covered_pct = (statuses.get("covered", 0) / total * 100) if total else 0
                st.progress(covered_pct / 100)
                st.caption("{:.0f}% coverage ({} of {} questions have good coverage)".format(
                    covered_pct, statuses.get("covered", 0), total))

                # Filter
                status_filter = st.multiselect("Filter by status",
                    ["covered", "thin", "duplicate", "gap"], default=[], key="cov_filter")

                display = mapped
                if status_filter:
                    display = [c for c in display if c["coverage_status"] in status_filter]

                # Table
                df_data = []
                for c in display:
                    df_data.append({
                        "Theme": c["theme"],
                        "Question": c["question_text"][:80],
                        "Status": c["coverage_status"].upper(),
                        "Score": c.get("coverage_score") or "—",
                        "Page": (c.get("page_url") or "—").split("/")[-2] if c.get("page_url") and "/" in c["page_url"] else "—",
                        "Reasoning": (c.get("ai_reasoning") or "")[:80],
                    })
                if df_data:
                    st.dataframe(pd.DataFrame(df_data), use_container_width=True, height=500)

            col_map, col_clear3 = st.columns([3, 1])
            with col_map:
                btn = "Re-run Coverage Analysis" if mapped else "Run Coverage Analysis"
                if st.button(btn, type="primary", use_container_width=True,
                             disabled=not api_key):
                    progress = st.progress(0)
                    with st.spinner("Mapping questions to pages..."):
                        count = run_coverage_map(api_key, model, progress_cb=lambda p: progress.progress(p))
                    st.success("Mapped {} questions".format(count))
                    st.rerun()
            with col_clear3:
                if st.button("Clear", use_container_width=True, key="clear_coverage"):
                    _clear_table("coverage_map")
                    st.rerun()

    # ==================================================================
    # TAB 4: External Enrichment
    # ==================================================================
    with tab4:
        st.markdown("### External Enrichment")
        st.caption("Fetch Google Suggest and external signals to find questions outside the Acko universe")

        themes = _q(ARCH_DB, "SELECT DISTINCT theme FROM question_universe ORDER BY theme")
        theme_names = [t["theme"] for t in themes]

        if not theme_names:
            st.warning("Build the **Question Universe** first (Tab 2).")
        else:
            selected_themes = st.multiselect("Themes to enrich", theme_names, default=theme_names[:3])

            existing_signals = _q(ARCH_DB, "SELECT theme, signal_type, signal_text FROM external_signals ORDER BY theme")
            if existing_signals:
                st.success("{} external signals collected".format(len(existing_signals)))
                df = pd.DataFrame(existing_signals)
                df.columns = ["Theme", "Type", "Signal"]
                st.dataframe(df, use_container_width=True, height=300)

            col_enrich, col_clear4 = st.columns([3, 1])
            with col_enrich:
                if st.button("Fetch External Signals", type="primary", use_container_width=True,
                             disabled=not selected_themes):
                    with st.spinner("Fetching Google Suggest for {} themes...".format(len(selected_themes))):
                        count = run_enrichment(selected_themes)
                    st.success("Collected {} new signals".format(count))
                    st.rerun()
            with col_clear4:
                if st.button("Clear", use_container_width=True, key="clear_enrich"):
                    _clear_table("external_signals")
                    st.rerun()

    # ==================================================================
    # TAB 5: Content Roadmap
    # ==================================================================
    with tab5:
        st.markdown("### Content Roadmap")
        st.caption("AI-generated content decisions: what to merge, deepen, create, redirect, or keep")

        if _count(ARCH_DB, "question_universe") == 0:
            st.warning("Complete steps 1-3 first.")
        else:
            decisions = _q(ARCH_DB, "SELECT * FROM content_decisions ORDER BY priority_score DESC")

            if decisions:
                # Summary
                actions = {}
                for d in decisions:
                    a = d["action"]
                    actions[a] = actions.get(a, 0) + 1

                cols = st.columns(5)
                for i, (action, color) in enumerate(ACTION_COLORS.items()):
                    cols[i].metric(action.upper(), actions.get(action, 0))

                # Filter
                action_filter = st.multiselect("Filter by action",
                    list(ACTION_COLORS.keys()), default=[], key="road_filter")
                status_filter = st.multiselect("Filter by status",
                    ["proposed", "approved", "in_progress", "done"], default=[], key="road_status")

                display = decisions
                if action_filter:
                    display = [d for d in display if d["action"] in action_filter]
                if status_filter:
                    display = [d for d in display if d["status"] in status_filter]

                # Display decisions as cards
                for d in display:
                    action = d["action"]
                    color = ACTION_COLORS.get(action, "#6B7280")
                    urls = json.loads(d.get("source_urls_json", "[]"))

                    with st.container(border=True):
                        c_badge, c_q, c_pri = st.columns([1, 4, 1])
                        with c_badge:
                            st.markdown('<span class="action-badge" style="background:{}">{}</span>'.format(
                                color, action.upper()), unsafe_allow_html=True)
                        with c_q:
                            st.markdown("**{}**".format(d["target_question"]))
                            st.caption("{} › {}".format(d.get("theme", ""), d.get("sub_theme", "")))
                        with c_pri:
                            st.metric("Priority", "{:.1f}".format(d["priority_score"]), label_visibility="collapsed")

                        if d.get("ai_reasoning"):
                            st.caption(d["ai_reasoning"])
                        if urls:
                            with st.expander("Source URLs ({})".format(len(urls))):
                                for u in urls:
                                    st.caption(u)

                # Export button
                st.markdown("---")
                approved = [d for d in decisions if d["status"] in ("proposed", "approved")]
                if approved:
                    selected_for_export = st.multiselect(
                        "Select decisions to export to Generate pipeline",
                        options=range(len(approved)),
                        format_func=lambda i: "[{}] {}".format(approved[i]["action"].upper(), approved[i]["target_question"][:60]),
                        default=[])

                    if st.button("Export {} to Clusters →".format(len(selected_for_export)),
                                 type="primary", disabled=not selected_for_export):
                        to_export = [approved[i] for i in selected_for_export]
                        count = export_to_clusters(to_export)
                        st.success("Exported {} decisions to clusters. Go to **Generate** to create articles.".format(count))
                        st.rerun()

            col_road, col_clear5 = st.columns([3, 1])
            with col_road:
                btn = "Regenerate Roadmap" if decisions else "Generate Content Roadmap"
                if st.button(btn, type="primary", use_container_width=True,
                             disabled=not api_key):
                    with st.spinner("Generating content roadmap with {}...".format(model)):
                        count = run_roadmap(api_key, model)
                    st.success("Generated {} content decisions".format(count))
                    st.rerun()
            with col_clear5:
                if st.button("Clear", use_container_width=True, key="clear_roadmap"):
                    _clear_table("content_decisions")
                    st.rerun()


main()
