"""
Acko SEO Content Pipeline — Home
"""

import streamlit as st

st.set_page_config(
    page_title="Acko SEO Pipeline",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    div[data-testid="stSidebarNav"] { padding-top: 0.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Pipeline")
    st.page_link("app.py", label="Home", icon="🏠")
    st.page_link("pages/1_crawler.py", label="1. Crawl", icon="🕷️")
    st.page_link("pages/2_clusters.py", label="2. Cluster", icon="🧩")
    st.page_link("pages/3_generate.py", label="3. Generate", icon="✍️")
    st.page_link("pages/4_evaluate.py", label="4. Evaluate", icon="📊")
    st.divider()
    st.caption("Acko SEO Pipeline · v2.0")

st.title("Acko SEO Content Pipeline")
st.markdown("Transform ~3,500 legacy pages into high-quality, SEO-optimised articles using AI.")

# ---------------------------------------------------------------------------
# Live stats
# ---------------------------------------------------------------------------
import sqlite3
from pathlib import Path

_root = Path(__file__).resolve().parent
_crawl_db = _root / "crawl_state.db"
_cluster_db = _root / "clusters.db"
_articles_db = _root / "articles.db"


def _count(db, table, where=""):
    if not db.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db))
        q = "SELECT COUNT(*) FROM {}".format(table) + (" WHERE " + where if where else "")
        n = conn.execute(q).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


pages_crawled = _count(_crawl_db, "pages")
clusters_total = _count(_cluster_db, "clusters")
clusters_ready = _count(_cluster_db, "clusters", "status='ready'")
articles_gen = _count(_articles_db, "articles")
articles_approved = _count(_articles_db, "articles", "status='approved'")

# ---------------------------------------------------------------------------
# Process flow — visual pipeline
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### How it works")

flow_html = """
<div style="display:flex; align-items:stretch; gap:0; margin:24px 0 32px; font-family:Inter,sans-serif;">

  <div style="flex:1; background:linear-gradient(135deg,#EDE9FE,#F3F0FF); border-radius:16px 0 0 16px; padding:24px 20px; text-align:center; position:relative;">
    <div style="font-size:2rem; margin-bottom:8px;">🕷️</div>
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#7C3AED; margin-bottom:6px;">STEP 1</div>
    <div style="font-size:1.05rem; font-weight:800; color:#1A1A2E; margin-bottom:6px;">Crawl</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">Headless browser extracts content, headings, links & metadata from legacy pages</div>
    <div style="margin-top:12px; font-size:0.78rem; font-weight:600; color:#522ED3;">""" + str(pages_crawled) + """ pages</div>
    <div style="position:absolute; right:-14px; top:50%; transform:translateY(-50%); z-index:2; font-size:1.2rem; color:#7C3AED;">→</div>
  </div>

  <div style="flex:1; background:linear-gradient(135deg,#E0F2FE,#EFF6FF); padding:24px 20px; text-align:center; position:relative;">
    <div style="font-size:2rem; margin-bottom:8px;">🧩</div>
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#0284C7; margin-bottom:6px;">STEP 2</div>
    <div style="font-size:1.05rem; font-weight:800; color:#1A1A2E; margin-bottom:6px;">Cluster</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">AI groups pages by the real consumer question they answer. Many pages → one cluster.</div>
    <div style="margin-top:12px; font-size:0.78rem; font-weight:600; color:#0284C7;">""" + str(clusters_total) + """ clusters (""" + str(clusters_ready) + """ ready)</div>
    <div style="position:absolute; right:-14px; top:50%; transform:translateY(-50%); z-index:2; font-size:1.2rem; color:#0284C7;">→</div>
  </div>

  <div style="flex:1; background:linear-gradient(135deg,#D1FAE5,#ECFDF5); padding:24px 20px; text-align:center; position:relative;">
    <div style="font-size:2rem; margin-bottom:8px;">✍️</div>
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#059669; margin-bottom:6px;">STEP 3</div>
    <div style="font-size:1.05rem; font-weight:800; color:#1A1A2E; margin-bottom:6px;">Generate</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">AI writes one new article per cluster — better than any source page. Production-ready HTML.</div>
    <div style="margin-top:12px; font-size:0.78rem; font-weight:600; color:#059669;">""" + str(articles_gen) + """ articles</div>
    <div style="position:absolute; right:-14px; top:50%; transform:translateY(-50%); z-index:2; font-size:1.2rem; color:#059669;">→</div>
  </div>

  <div style="flex:1; background:linear-gradient(135deg,#FEF3C7,#FFFBEB); border-radius:0 16px 16px 0; padding:24px 20px; text-align:center;">
    <div style="font-size:2rem; margin-bottom:8px;">📊</div>
    <div style="font-size:0.7rem; font-weight:700; letter-spacing:2px; color:#D97706; margin-bottom:6px;">STEP 4</div>
    <div style="font-size:1.05rem; font-weight:800; color:#1A1A2E; margin-bottom:6px;">Evaluate</div>
    <div style="font-size:0.82rem; color:#4B5563; line-height:1.5;">Northstar framework scores on 6 dimensions. Only articles above the quality bar get published.</div>
    <div style="margin-top:12px; font-size:0.78rem; font-weight:600; color:#D97706;">""" + str(articles_approved) + """ approved</div>
  </div>

</div>
"""

st.markdown(flow_html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Key insight callout
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="background:#F8F7FF; border-left:4px solid #522ED3; border-radius:0 12px 12px 0; padding:20px 24px; margin:0 0 32px; font-family:Inter,sans-serif;">
        <div style="font-size:0.72rem; font-weight:700; letter-spacing:2px; text-transform:uppercase; color:#522ED3; margin-bottom:6px;">KEY CONCEPT</div>
        <p style="font-size:0.95rem; color:#374151; line-height:1.7; margin:0;">
            This is <strong>not</strong> a page rewriter. It's a <strong>blog-writing agent</strong>.
            3,500 legacy pages are raw research material — the AI reads all source pages in a cluster,
            then writes one new article that answers the consumer question better than any individual page.
            Think of it as turning a messy wiki into a polished editorial blog.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Quick-launch cards
# ---------------------------------------------------------------------------
st.markdown("### Quick launch")

col1, col2, col3, col4 = st.columns(4, gap="medium")

with col1:
    with st.container(border=True):
        st.markdown("**🕷️ Crawl**")
        st.caption("Extract content from acko.com legacy pages into `crawl_state.db`")
        st.page_link("pages/1_crawler.py", label="Open →", icon="🕷️")

with col2:
    with st.container(border=True):
        st.markdown("**🧩 Cluster**")
        st.caption("Group pages by consumer question using AI")
        st.page_link("pages/2_clusters.py", label="Open →", icon="🧩")

with col3:
    with st.container(border=True):
        st.markdown("**✍️ Generate**")
        st.caption("Write new articles from clusters with inferred questions")
        st.page_link("pages/3_generate.py", label="Open →", icon="✍️")

with col4:
    with st.container(border=True):
        st.markdown("**📊 Evaluate**")
        st.caption("Score articles against Northstar quality framework")
        st.page_link("pages/4_evaluate.py", label="Open →", icon="📊")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
with st.expander("Configuration tips", expanded=False):
    st.markdown(
        """
        - **API key:** Set `OPENAI_API_KEY` as an env variable or in Streamlit Secrets.
        - **Playwright:** The crawler needs Chromium — run `playwright install chromium`.
        - **Order:** Crawl → Cluster → Generate → Evaluate. Each step reads from the previous.
        - **Northstar:** The quality framework is defined in `northstar.md` — edit it to change evaluation criteria.
        """
    )

st.divider()
st.caption("Acko SEO Content Pipeline v2.0 — Blog-writing agent architecture")
