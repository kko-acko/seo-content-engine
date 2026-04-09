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

import openai
import pandas as pd
import streamlit as st

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
            status              TEXT DEFAULT 'draft',
            created_at          TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def save_clusters(clusters: List[Dict]) -> int:
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    # Clear old clusters
    conn.execute("DELETE FROM clusters")
    count = 0
    for c in clusters:
        conn.execute(
            "INSERT INTO clusters (consumer_question, theme, page_group, priority, urls_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                c.get("consumer_question", ""),
                c.get("theme", ""),
                c.get("page_group", "informational"),
                c.get("priority", 0),
                json.dumps(c.get("urls", []), ensure_ascii=False),
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


def update_cluster_status(cluster_id: int, status: str) -> None:
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.execute("UPDATE clusters SET status = ? WHERE cluster_id = ?", (status, cluster_id))
    conn.commit()
    conn.close()


def get_crawled_pages() -> List[Dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT url, title, h1, meta_description FROM pages ORDER BY url"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Clustering prompt
# ---------------------------------------------------------------------------

CLUSTER_SYSTEM_PROMPT = """You are an SEO content strategist for Acko, an Indian digital insurance company.

You are given a list of crawled page URLs with their titles and H1 headings. Your job is to:

1. INFER the real consumer question each page is trying to answer
2. GROUP pages that answer the same or closely adjacent questions into clusters
3. For each cluster, state the ONE primary consumer question it addresses
4. Classify each cluster as "transactional" (buy/renew/compare intent) or "informational" (understand/learn/evaluate intent)
5. Assign a priority score 1-10 (10 = highest traffic potential / strategic importance)

Rules:
- A cluster can contain 1 page (if the topic is unique) or up to 10 pages (if many pages address the same question)
- The consumer_question must be a natural-language question a real person would type or speak
- The theme is a short 2-4 word label (e.g., "zero depreciation cover", "claim process", "NCB transfer")
- Do NOT create clusters for pages that are clearly transactional product pages (e.g., /car-insurance/) — put those in a single "Core Product Pages" cluster with page_group = "transactional"
- Focus on identifying informational clusters where multiple legacy pages can be consolidated into one better article

Return ONLY valid JSON — an array of cluster objects:
[
  {
    "consumer_question": "What does zero depreciation cover and is it worth the extra cost?",
    "theme": "zero depreciation",
    "page_group": "informational",
    "priority": 8,
    "urls": ["https://www.acko.com/car-insurance/zero-depreciation/", "https://www.acko.com/car-insurance/bumper-replacement/"]
  }
]

No markdown fences. No explanation. Only the JSON array.
"""


def run_clustering(api_key: str, pages: List[Dict], model: str = "gpt-4o") -> List[Dict]:
    """Send all crawled page summaries to OpenAI and get clusters back."""
    client = openai.OpenAI(api_key=api_key)

    # Build the page list for the prompt
    page_lines = []
    for p in pages:
        line = "URL: {}\n  Title: {}\n  H1: {}\n  Meta: {}".format(
            p.get("url", ""),
            p.get("title", ""),
            p.get("h1", ""),
            (p.get("meta_description") or "")[:120],
        )
        page_lines.append(line)

    user_prompt = "Here are {} crawled pages from acko.com. Cluster them by consumer question.\n\n{}".format(
        len(pages),
        "\n\n".join(page_lines),
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=8192,
        messages=[
            {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
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
        clusters = json.loads(text)
        if isinstance(clusters, list):
            return clusters
    except json.JSONDecodeError:
        pass

    return [{"error": "Failed to parse clustering response", "raw": text}]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Clusters — Acko SEO", page_icon="🧩", layout="wide")
    st.title("🧩 Content Clusters")
    st.caption(
        "Group crawled pages by the consumer question they're trying to answer. "
        "Each cluster becomes one new article."
    )

    init_cluster_db()

    # Sidebar
    deployment_key = get_openai_key()
    with st.sidebar:
        st.header("Navigation")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_crawler.py", label="Crawler", icon="🕷️")
        st.page_link("pages/2_clusters.py", label="Clusters", icon="🧩")
        st.page_link("pages/3_generate.py", label="Generate", icon="✍️")
        st.page_link("pages/4_evaluate.py", label="Evaluate", icon="📊")
        st.divider()

        st.subheader("OpenAI")
        if deployment_key:
            st.success("API key set.")
            api_key = deployment_key
        else:
            api_key = st.text_input(
                "OpenAI API key",
                type="password",
                help="Paste from platform.openai.com",
            )

        model = st.selectbox(
            "Clustering model",
            ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            index=0,
            help="gpt-4o recommended for best clustering quality.",
        )

    # Load crawled pages
    pages = get_crawled_pages()
    existing_clusters = load_clusters()

    col1, col2, col3 = st.columns(3)
    col1.metric("Crawled pages", len(pages))
    col2.metric("Existing clusters", len(existing_clusters))
    col3.metric("Unclustered pages", max(0, len(pages) - sum(len(c["urls"]) for c in existing_clusters)))

    st.divider()

    # Tab layout
    tab_run, tab_view = st.tabs(["🔄 Run Clustering", "📋 View Clusters"])

    # ---- TAB: Run Clustering ----
    with tab_run:
        if not pages:
            st.warning("No crawled pages found. Run the crawler first.")
        else:
            st.markdown("### Pages to cluster")
            df = pd.DataFrame(pages)
            st.dataframe(
                df[["url", "title", "h1"]],
                use_container_width=True,
                height=300,
            )

            st.markdown("---")

            if st.button("🚀 Run Clustering", type="primary", use_container_width=True):
                if not api_key:
                    st.error("No API key. Set OPENAI_API_KEY or paste in sidebar.")
                else:
                    with st.spinner("Sending {} pages to {} for clustering...".format(len(pages), model)):
                        try:
                            clusters = run_clustering(api_key, pages, model)
                        except Exception as e:
                            st.error("API error: {}".format(e))
                            clusters = []

                    if clusters and "error" not in clusters[0]:
                        count = save_clusters(clusters)
                        st.success("Created {} clusters from {} pages.".format(count, len(pages)))
                        st.rerun()
                    elif clusters and "error" in clusters[0]:
                        st.error(clusters[0]["error"])
                        if "raw" in clusters[0]:
                            with st.expander("Raw response"):
                                st.code(clusters[0]["raw"])
                    else:
                        st.warning("No clusters returned.")

    # ---- TAB: View Clusters ----
    with tab_view:
        if not existing_clusters:
            st.info("No clusters yet. Go to the Run Clustering tab first.")
        else:
            # Summary stats
            info_count = sum(1 for c in existing_clusters if c["page_group"] == "informational")
            tx_count = sum(1 for c in existing_clusters if c["page_group"] == "transactional")
            st.markdown("**{} informational** clusters · **{} transactional** clusters".format(info_count, tx_count))

            # Filter
            filter_group = st.selectbox(
                "Filter by type",
                ["All", "informational", "transactional"],
                index=0,
            )

            filtered = existing_clusters
            if filter_group != "All":
                filtered = [c for c in existing_clusters if c["page_group"] == filter_group]

            for cluster in filtered:
                priority_label = "🔴" if cluster["priority"] >= 8 else "🟡" if cluster["priority"] >= 5 else "🟢"
                group_label = "📄" if cluster["page_group"] == "informational" else "💳"

                with st.expander(
                    "{} {} **{}** — {} ({} pages, priority {})".format(
                        priority_label,
                        group_label,
                        cluster["consumer_question"],
                        cluster["theme"],
                        len(cluster["urls"]),
                        cluster["priority"],
                    ),
                    expanded=False,
                ):
                    st.markdown("**Theme:** {}".format(cluster["theme"]))
                    st.markdown("**Type:** {}".format(cluster["page_group"]))
                    st.markdown("**Priority:** {}/10".format(cluster["priority"]))
                    st.markdown("**Status:** {}".format(cluster["status"]))
                    st.markdown("**Source pages:**")
                    for url in cluster["urls"]:
                        st.markdown("- [{}]({})".format(url, url))

                    # Status buttons
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


main()
