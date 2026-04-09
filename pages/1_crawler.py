"""
Acko Legacy Page Crawler & Content Extractor
=============================================
Streamlit app that crawls ~3,500 legacy pages from acko.com/car-insurance/
using a headless Playwright browser, extracts structured content, and exports
the data as CSV/JSON.

Uses SQLite for checkpoint/resume and respects robots.txt + configurable delay.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
import os
import re
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urljoin, urlparse

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = Path("crawl_state.db")
USER_AGENT = "AckoSEOCrawler/1.0 (+https://acko.com)"
MAX_RETRIES = 4  # total attempts = 1 original + 4 retries

# ---------------------------------------------------------------------------
# Database helpers (sync – called from the main thread & inside async via
# run_in_executor where needed)
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            url             TEXT PRIMARY KEY,
            http_status     INTEGER,
            title           TEXT,
            meta_description TEXT,
            canonical       TEXT,
            h1              TEXT,
            headings_json   TEXT,
            body_text       TEXT,
            lists_json      TEXT,
            authorship      TEXT,
            internal_links_json TEXT,
            crawled_at      TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            url     TEXT PRIMARY KEY,
            status  TEXT DEFAULT 'pending'   -- pending | done | failed
        )
    """)
    conn.commit()
    conn.close()


def enqueue_url(url: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("INSERT OR IGNORE INTO queue (url, status) VALUES (?, 'pending')", (url,))
    conn.commit()
    conn.close()


def mark_url(url: str, status: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("UPDATE queue SET status = ? WHERE url = ?", (status, url))
    conn.commit()
    conn.close()


def get_pending_urls(limit: int = 50) -> list[str]:
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT url FROM queue WHERE status = 'pending' LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def save_page(data: dict):
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("""
            INSERT OR REPLACE INTO pages
            (url, http_status, title, meta_description, canonical,
             h1, headings_json, body_text, lists_json, authorship,
             internal_links_json, crawled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["url"], data["http_status"], data["title"],
            data["meta_description"], data["canonical"],
            data["h1"], json.dumps(data["headings"]),
            data["body_text"], json.dumps(data["lists"]),
            data["authorship"], json.dumps(data["internal_links"]),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()


def count_queue() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM queue WHERE status='done'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM queue WHERE status='failed'").fetchone()[0]
    conn.close()
    return {"total": total, "done": done, "failed": failed, "pending": total - done - failed}


def get_all_pages_df() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM pages ORDER BY crawled_at DESC", conn)
    conn.close()
    return df


def get_recent_pages(n: int = 20) -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT url, http_status, h1 FROM pages ORDER BY crawled_at DESC LIMIT ?",
        conn, params=(n,),
    )
    conn.close()
    return df


def reset_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM pages")
    conn.execute("DELETE FROM queue")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Robots.txt helper
# ---------------------------------------------------------------------------

# Paths explicitly disallowed in acko.com/robots.txt that we must respect.
# We skip the wildcard query-string rules (e.g. *source=*) since Python's
# RobotFileParser misinterprets them and blocks all pages.
_DISALLOWED_PREFIXES = (
    "/wp-admin/", "/s/", "/policy/", "/amazonmobile/", "/endorsement/",
    "/claim/", "/customer/", "/health-product/", "/r2d2/", "/card/",
    "/mastersearch/", "/myaccount", "/support/", "/workspace/",
    "/lp/", "/logout/", "/set-tracker/", "/_next_static/", "/home2/",
    "/p/health/", "/ackology/", "/falcon/",
)


def check_robots(url: str) -> bool:
    """Return True if the URL path is not in the disallowed list."""
    path = urlparse(url).path
    for prefix in _DISALLOWED_PREFIXES:
        if path.startswith(prefix):
            return False
    return True


# ---------------------------------------------------------------------------
# Content extraction (runs inside Playwright page context)
# ---------------------------------------------------------------------------

EXTRACT_JS = """
() => {
    // Helper: get text content, trimmed
    const txt = el => (el ? el.textContent.trim() : '');

    // Identify main content area – exclude nav, header, footer, sidebar
    const main = document.querySelector('main')
                 || document.querySelector('[role="main"]')
                 || document.querySelector('article')
                 || document.querySelector('.content')
                 || document.querySelector('#content')
                 || document.body;

    // Remove unwanted sections from a cloned tree so we don't mutate the page
    const clone = main.cloneNode(true);
    clone.querySelectorAll('header, footer, nav, aside, [role="navigation"], [role="banner"], [role="contentinfo"], .sidebar, .nav, .footer, .header').forEach(el => el.remove());

    // Title & meta
    const title = document.title || '';
    const metaDesc = document.querySelector('meta[name="description"]');
    const canonical = document.querySelector('link[rel="canonical"]');

    // Headings
    const headings = [];
    clone.querySelectorAll('h1, h2, h3').forEach(h => {
        headings.push({ level: h.tagName, text: h.textContent.trim() });
    });

    // H1
    const h1El = clone.querySelector('h1');
    const h1 = h1El ? h1El.textContent.trim() : '';

    // Body paragraphs
    const paragraphs = [];
    clone.querySelectorAll('p').forEach(p => {
        const t = p.textContent.trim();
        if (t.length > 20) paragraphs.push(t);
    });

    // Lists (especially Q&A style)
    const lists = [];
    clone.querySelectorAll('ul, ol').forEach(list => {
        const items = [];
        list.querySelectorAll('li').forEach(li => {
            const t = li.textContent.trim();
            if (t) items.push(t);
        });
        if (items.length > 0) lists.push(items);
    });

    // Authorship
    let authorship = '';
    const authorEl = clone.querySelector('[class*="author"], [rel="author"], .author, [itemprop="author"]');
    if (authorEl) authorship = authorEl.textContent.trim();

    // Internal links (within main content only)
    const internalLinks = [];
    const seen = new Set();
    clone.querySelectorAll('a[href]').forEach(a => {
        const href = a.href;
        if (href && href.includes('acko.com') && !seen.has(href)) {
            seen.add(href);
            internalLinks.push({ href: href, text: a.textContent.trim() });
        }
    });

    return {
        title,
        meta_description: metaDesc ? metaDesc.getAttribute('content') : '',
        canonical: canonical ? canonical.getAttribute('href') : '',
        h1,
        headings,
        body_text: paragraphs.join('\\n\\n'),
        lists,
        authorship,
        internal_links: internalLinks,
    };
}
"""


# ---------------------------------------------------------------------------
# Async crawler core
# ---------------------------------------------------------------------------

async def crawl_page(page, url: str, delay: float) -> dict | None:
    """Navigate to url, extract content, return data dict or None on failure."""
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            # Use domcontentloaded first — networkidle can hang on heavy JS sites
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            status = resp.status if resp else 0

            # Retry on 429 / 5xx
            if status == 429 or status >= 500:
                if attempt <= MAX_RETRIES:
                    wait = delay * (2 ** (attempt - 1))
                    await asyncio.sleep(wait)
                    continue
                else:
                    return {"url": url, "http_status": status, "title": "", "meta_description": "",
                            "canonical": "", "h1": "", "headings": [], "body_text": "",
                            "lists": [], "authorship": "", "internal_links": []}

            # Wait for JS hydration — try networkidle with a shorter timeout
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass  # page may never go fully idle; that's fine
            await asyncio.sleep(1.0)  # extra buffer for React hydration

            data = await page.evaluate(EXTRACT_JS)
            data["url"] = url
            data["http_status"] = status
            return data

        except Exception as e:
            if attempt <= MAX_RETRIES:
                wait = delay * (2 ** (attempt - 1))
                await asyncio.sleep(wait)
                continue
            return {"url": url, "http_status": 0, "title": "", "meta_description": "",
                    "canonical": "", "h1": "ERROR: " + str(e)[:200], "headings": [],
                    "body_text": "", "lists": [], "authorship": "", "internal_links": []}

    return None


def discover_links(data: dict, base_domain: str, target_prefix: str) -> list:
    """Extract new URLs to crawl from a page's internal links.

    Follows all acko.com links that are either:
      1. Under the target prefix (e.g. /car-insurance/...), OR
      2. Contain 'car-insurance' anywhere in the path (catches sibling pages
         like /third-party-car-insurance/ or /what-is-idv-in-car-insurance/)
    """
    new_urls = []
    skip_patterns = ("/authn/", "/platform/", "/api/", "#", ".pdf", ".jpg", ".png",
                     "/login", "/wp-content/", "/wp-admin/", "/new-car/", "/garages/",
                     "/contact-us/", "/author/")
    # Extract the keyword from the target prefix path for broader matching
    # e.g. "car-insurance" from "https://www.acko.com/car-insurance/"
    prefix_path = urlparse(target_prefix).path.strip("/")  # "car-insurance"

    for link in data.get("internal_links", []):
        href = link.get("href", "")
        if not href:
            continue
        # Normalize
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != base_domain:
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if not clean.endswith("/"):
            clean = clean + "/"
        # Skip auth, API, asset, and utility URLs
        if any(skip in clean for skip in skip_patterns):
            continue
        # Accept if under target prefix OR path contains the keyword
        path = parsed.path.lower()
        if clean.startswith(target_prefix) or prefix_path in path:
            new_urls.append(clean)
    return new_urls


async def run_crawler(target_url: str, delay: float, status_placeholder, progress_bar,
                      df_placeholder, stop_event: asyncio.Event):
    """Main crawl loop using Playwright."""
    from playwright.async_api import async_playwright

    parsed = urlparse(target_url)
    base_domain = parsed.netloc
    # Ensure trailing slash on prefix
    target_prefix = target_url if target_url.endswith("/") else target_url + "/"

    # Seed the queue (force re-queue if previously marked done with no data)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM queue WHERE url = ? AND status = 'done' AND url NOT IN (SELECT url FROM pages)", (target_prefix,))
    conn.commit()
    conn.close()
    enqueue_url(target_prefix)

    # Pre-fetch robots.txt once
    robots_ok = True
    try:
        check_robots(target_prefix)
    except Exception:
        pass  # if robots.txt fails, we'll still crawl

    status_placeholder.info("Launching headless Chromium browser...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        status_placeholder.info("Browser launched. Starting crawl...")
        pages_crawled = 0

        try:
            while not stop_event.is_set():
                pending = get_pending_urls(limit=1)
                if not pending:
                    counts = count_queue()
                    status_placeholder.success(
                        f"Crawl complete! {counts['done']} pages crawled, "
                        f"{counts['failed']} failed, 0 pending."
                    )
                    break

                url = pending[0]

                # Check robots.txt (skip if it errors)
                try:
                    if not check_robots(url):
                        mark_url(url, "done")
                        continue
                except Exception:
                    pass  # allow crawl if robots check fails

                # Crawl the page
                status_placeholder.info(f"Crawling: **{url}** ...")
                data = await crawl_page(page, url, delay)

                if data is None:
                    mark_url(url, "failed")
                    status_placeholder.warning(f"Failed (no data): {url}")
                else:
                    try:
                        save_page(data)
                        mark_url(url, "done")
                        pages_crawled += 1
                    except Exception as e:
                        mark_url(url, "failed")
                        status_placeholder.warning(f"DB error saving {url}: {e}")
                        continue

                    # Discover new links
                    new_links = discover_links(data, base_domain, target_prefix)
                    for link in new_links:
                        enqueue_url(link)

                # Update UI
                counts = count_queue()
                total = counts["total"]
                done = counts["done"] + counts["failed"]
                pct = done / total if total > 0 else 0
                progress_bar.progress(min(pct, 1.0))
                status_placeholder.info(
                    f"Crawled **{done}** / **{total}** pages  |  "
                    f"Pending: {counts['pending']}  |  Failed: {counts['failed']}  |  "
                    f"Last: {data.get('h1', 'N/A')[:60] if data else 'N/A'}"
                )

                # Live table
                recent = get_recent_pages(30)
                df_placeholder.dataframe(recent, use_container_width=True, hide_index=True)

                # Respect delay
                await asyncio.sleep(delay)

        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Crawler · Acko SEO",
        page_icon="🕷️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "crawl_reset_pending" not in st.session_state:
        st.session_state.crawl_reset_pending = False

    st.title("Legacy page crawler")
    st.caption(
        "Discover and extract content under your target path. Progress is saved in "
        "**`crawl_state.db`** — you can stop and resume anytime."
    )

    nav1, nav2, nav3, _ = st.columns([1, 1, 1, 3])
    with nav1:
        st.page_link("app.py", label="Home", icon="🏠")
    with nav2:
        st.page_link("pages/2_clusters.py", label="Clusters", icon="🧩")
    with nav3:
        st.page_link("pages/3_generate.py", label="Generate", icon="✍️")

    init_db()

    # ---- Sidebar Controls ----
    with st.sidebar:
        st.header("Pipeline")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_crawler.py", label="1. Crawl", icon="🕷️")
        st.page_link("pages/2_clusters.py", label="2. Cluster", icon="🧩")
        st.page_link("pages/3_generate.py", label="3. Generate", icon="✍️")
        st.page_link("pages/4_evaluate.py", label="4. Evaluate", icon="📊")
        st.divider()

        st.subheader("OpenAI")
        _deploy_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if _deploy_key:
            api_key_sidebar = _deploy_key
            st.success("API key active", icon="🔑")
        else:
            api_key_sidebar = st.text_input("OpenAI API key", type="password", key="oai_key_crawl", placeholder="sk-...")

        st.divider()

        st.subheader("Run crawl")
        target_url = st.text_input(
            "Target URL",
            value="https://www.acko.com/car-insurance/",
            help="Crawl starts here; internal links under this section are enqueued.",
        )
        delay = st.slider(
            "Delay between requests (seconds)",
            min_value=1,
            max_value=5,
            value=2,
            help="Higher values are gentler on the origin server.",
        )

        col1, col2 = st.columns(2)
        with col1:
            start_btn = st.button("Start", use_container_width=True, type="primary")
        with col2:
            stop_btn = st.button("Stop", use_container_width=True, help="Stops after the current page; progress is kept.")

        st.divider()
        with st.expander("Export", expanded=False):
            df_all = get_all_pages_df()
            if not df_all.empty:
                csv_data = df_all.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download CSV",
                    data=csv_data,
                    file_name=f"acko_crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

                json_records = []
                for _, row in df_all.iterrows():
                    record = row.to_dict()
                    for col in ["headings_json", "lists_json", "internal_links_json"]:
                        if col in record and isinstance(record[col], str):
                            try:
                                record[col] = json.loads(record[col])
                            except (json.JSONDecodeError, TypeError):
                                pass
                    json_records.append(record)

                json_data = json.dumps(json_records, indent=2, ensure_ascii=False).encode("utf-8")
                st.download_button(
                    "Download JSON",
                    data=json_data,
                    file_name=f"acko_crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True,
                )
            else:
                st.caption("No rows yet — start a crawl to enable export.")

        st.divider()
        with st.container(border=True):
            st.markdown("**Queue**")
            counts = count_queue()
            c_a, c_b = st.columns(2)
            c_a.metric("Done", counts["done"])
            c_b.metric("Pending", counts["pending"])
            c_c, c_d = st.columns(2)
            c_c.metric("Failed", counts["failed"])
            c_d.metric("Total", counts["total"])

        st.divider()
        with st.expander("Danger zone", expanded=False):
            st.caption("Removes **all** rows from `pages` and `queue`. Use only if you need a clean slate.")
            if st.button("Request database reset", use_container_width=True):
                st.session_state.crawl_reset_pending = True
                st.rerun()

    # ---- Reset confirmation (main) ----
    if st.session_state.crawl_reset_pending:
        with st.container(border=True):
            st.error("**Reset the crawl database?** This permanently deletes crawled pages and the queue.")
            c_yes, c_no = st.columns(2)
            with c_no:
                if st.button("Cancel", use_container_width=True, key="crawl_reset_cancel"):
                    st.session_state.crawl_reset_pending = False
                    st.rerun()
            with c_yes:
                if st.button("Yes, delete everything", use_container_width=True, type="primary", key="crawl_reset_confirm"):
                    reset_db()
                    st.session_state.crawl_reset_pending = False
                    st.success("Database cleared.")
                    st.rerun()

    # ---- Main Area ----
    tab_live, tab_cluster, tab_help = st.tabs(["🕷️ Crawl", "🧩 Quick Cluster", "❓ How it works"])

    with tab_help:
        st.markdown("""
### Pipeline flow

<div style="font-family:Inter,sans-serif; margin:16px 0;">
<div style="display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap;">
  <div style="flex:1; min-width:200px; background:#F8F7FF; border-radius:12px; padding:16px; border-left:4px solid #522ED3;">
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#522ED3; margin-bottom:4px;">STEP 1</div>
    <div style="font-weight:700; color:#1A1A2E; margin-bottom:4px;">Crawl</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">Set a target URL and click Start. Playwright crawls pages, extracting headings, body text, links, and metadata. Stop anytime — progress is saved.</div>
  </div>
  <div style="flex:1; min-width:200px; background:#EFF6FF; border-radius:12px; padding:16px; border-left:4px solid #0284C7;">
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#0284C7; margin-bottom:4px;">STEP 2</div>
    <div style="font-weight:700; color:#1A1A2E; margin-bottom:4px;">Cluster</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">AI groups crawled pages by the consumer question they answer. Many legacy pages that cover the same topic → one cluster.</div>
  </div>
  <div style="flex:1; min-width:200px; background:#ECFDF5; border-radius:12px; padding:16px; border-left:4px solid #059669;">
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#059669; margin-bottom:4px;">STEP 3</div>
    <div style="font-weight:700; color:#1A1A2E; margin-bottom:4px;">Generate</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">AI reads ALL source pages in a cluster and writes one new article that answers the question better than any individual page.</div>
  </div>
  <div style="flex:1; min-width:200px; background:#FFFBEB; border-radius:12px; padding:16px; border-left:4px solid #D97706;">
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#D97706; margin-bottom:4px;">STEP 4</div>
    <div style="font-weight:700; color:#1A1A2E; margin-bottom:4px;">Evaluate</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">Northstar framework scores articles on 6 quality dimensions. Only articles above the bar get approved for publishing.</div>
  </div>
</div>
</div>

**Tip:** If the browser fails to launch, run `playwright install chromium` in your terminal.
        """, unsafe_allow_html=True)

    # ---- TAB: Quick Cluster ----
    with tab_cluster:
        df_all = get_all_pages_df()
        if df_all.empty:
            st.info("No crawled pages yet. Run the crawler first, then come back here to cluster.")
        else:
            st.markdown("### Cluster crawled pages by consumer question")
            st.caption("This groups your {} crawled pages into clusters. Each cluster becomes one new article.".format(len(df_all)))

            # Show preview of pages
            with st.expander("Preview crawled pages ({})".format(len(df_all)), expanded=False):
                st.dataframe(
                    df_all[["url", "title", "h1"]].head(50),
                    use_container_width=True,
                    hide_index=True,
                )

            # Check if clusters already exist
            _cluster_db_path = Path("clusters.db")
            _existing_count = 0
            if _cluster_db_path.exists():
                try:
                    _cconn = sqlite3.connect(str(_cluster_db_path))
                    _existing_count = _cconn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
                    _cconn.close()
                except Exception:
                    pass

            if _existing_count > 0:
                st.success("{} clusters already exist. You can re-cluster or proceed to **Generate**.".format(_existing_count))
                col_recluster, col_generate = st.columns(2)
                with col_generate:
                    st.page_link("pages/3_generate.py", label="Go to Generate →", icon="✍️")
                with col_recluster:
                    recluster_btn = st.button("🔄 Re-cluster pages", use_container_width=True)
            else:
                recluster_btn = True  # show the clustering UI

            if recluster_btn if isinstance(recluster_btn, bool) else recluster_btn:
                if not api_key_sidebar:
                    st.warning("Set your OpenAI API key in the sidebar to run clustering.")
                elif isinstance(recluster_btn, bool) or recluster_btn:
                    cluster_model = st.selectbox("Model for clustering", ["gpt-4o", "gpt-4o-mini"], index=0, key="cluster_model")

                    if st.button("🧩 Run Clustering", type="primary", use_container_width=True, key="quick_cluster_btn"):
                        # Import clustering logic
                        import importlib.util
                        _spec = importlib.util.spec_from_file_location("clusters_mod", str(Path(__file__).resolve().parent / "2_clusters.py"))
                        _clusters_mod = importlib.util.module_from_spec(_spec)

                        # We need to use the clustering function directly
                        import openai as _openai_mod

                        _cluster_prompt = """You are an SEO content strategist for Acko, an Indian digital insurance company.

You are given a list of crawled page URLs with their titles and H1 headings. Your job is to:

1. INFER the real consumer question each page is trying to answer
2. GROUP pages that answer the same or closely adjacent questions into clusters
3. For each cluster, state the ONE primary consumer question it addresses
4. Classify each cluster as "transactional" or "informational"
5. Assign a priority score 1-10 (10 = highest traffic potential)

Rules:
- A cluster can contain 1-10 pages
- consumer_question must be a natural-language question a real person would ask
- theme is a 2-4 word label (e.g. "zero depreciation cover", "claim process")
- Transactional product pages go in one "Core Product Pages" cluster

Return ONLY valid JSON array. No markdown fences.
[{"consumer_question": "...", "theme": "...", "page_group": "informational", "priority": 8, "urls": ["..."]}]"""

                        page_lines = []
                        for _, p in df_all.iterrows():
                            page_lines.append("URL: {}\n  Title: {}\n  H1: {}".format(
                                p.get("url", ""), p.get("title", ""), p.get("h1", "")
                            ))

                        _user_msg = "Here are {} crawled pages. Cluster them.\n\n{}".format(
                            len(df_all), "\n\n".join(page_lines[:200])
                        )

                        with st.spinner("Clustering {} pages with {}...".format(len(df_all), cluster_model)):
                            try:
                                _client = _openai_mod.OpenAI(api_key=api_key_sidebar)
                                _resp = _client.chat.completions.create(
                                    model=cluster_model,
                                    max_tokens=8192,
                                    messages=[
                                        {"role": "system", "content": _cluster_prompt},
                                        {"role": "user", "content": _user_msg},
                                    ],
                                )
                                _text = _resp.choices[0].message.content.strip()
                                if _text.startswith("```"):
                                    _text = _text.split("```")[1]
                                    if _text.startswith("json"):
                                        _text = _text[4:]
                                    _text = _text.strip()
                                _clusters = json.loads(_text)
                            except Exception as e:
                                st.error("Clustering error: {}".format(e))
                                _clusters = []

                        if _clusters and isinstance(_clusters, list):
                            # Save to clusters.db
                            _cconn = sqlite3.connect(str(_cluster_db_path))
                            _cconn.execute("""CREATE TABLE IF NOT EXISTS clusters (
                                cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                consumer_question TEXT NOT NULL, theme TEXT,
                                page_group TEXT DEFAULT 'informational',
                                priority INTEGER DEFAULT 0, urls_json TEXT NOT NULL,
                                status TEXT DEFAULT 'draft',
                                created_at TEXT DEFAULT (datetime('now')))""")
                            _cconn.execute("DELETE FROM clusters")
                            for c in _clusters:
                                _cconn.execute(
                                    "INSERT INTO clusters (consumer_question, theme, page_group, priority, urls_json, status) VALUES (?, ?, ?, ?, ?, 'ready')",
                                    (c.get("consumer_question", ""), c.get("theme", ""),
                                     c.get("page_group", "informational"), c.get("priority", 0),
                                     json.dumps(c.get("urls", []), ensure_ascii=False)),
                                )
                            _cconn.commit()
                            _cconn.close()

                            st.success("Created {} clusters! All marked as 'ready'.".format(len(_clusters)))

                            # Show clusters
                            for i, c in enumerate(_clusters):
                                with st.container(border=True):
                                    st.markdown("**{}** — {} ({} pages, P{})".format(
                                        c.get("consumer_question", ""),
                                        c.get("theme", ""),
                                        len(c.get("urls", [])),
                                        c.get("priority", 0),
                                    ))

                            st.markdown("---")
                            st.page_link("pages/3_generate.py", label="Go to Generate →", icon="✍️")

    with tab_live:
        status_placeholder = st.empty()
        progress_bar = st.progress(0)
        st.subheader("Recently crawled pages")
        df_placeholder = st.empty()

        # Show existing data on load
        recent = get_recent_pages(30)
        if not recent.empty:
            df_placeholder.dataframe(recent, use_container_width=True, hide_index=True)
            counts = count_queue()
            total = counts["total"]
            done = counts["done"] + counts["failed"]
            pct = done / total if total > 0 else 0
            progress_bar.progress(min(pct, 1.0))
            status_placeholder.info(
                f"Crawled **{done}** / **{total}** pages  |  "
                f"Pending: {counts['pending']}  |  Failed: {counts['failed']}"
            )
        else:
            status_placeholder.info(
                "No pages in the database yet. Click **Start** in the sidebar to begin crawling."
            )

        # ---- Crawl Execution ----
        if start_btn:
            status_placeholder.info("Launching headless browser...")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            stop_event = asyncio.Event()

            try:
                loop.run_until_complete(
                    run_crawler(target_url, delay, status_placeholder, progress_bar,
                                df_placeholder, stop_event)
                )
            except Exception as e:
                status_placeholder.error(f"Crawler error: {e}")
            finally:
                loop.close()

        if stop_btn and not start_btn:
            status_placeholder.warning(
                "Stop requested after the current page. Progress is saved — click **Start** to resume."
            )


if __name__ == "__main__":
    main()
