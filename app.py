"""
Acko Content Studio — Home (Studio v2 direction)
Dual-entry dashboard: Path A (crawl) · Path B (brief) · shared 3-pass pipeline.
"""
from __future__ import annotations
import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st

from ui import (
    apply_theme,
    sidebar,
    topbar,
    hero_grid,
    stat_row,
    activity_feed,
    side_card,
    tip_dark,
    pill,
    section_label,
    empty_state,
)

st.set_page_config(
    page_title="Studio · Acko Content",
    page_icon="●",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
sidebar(current="dashboard")

# ─── Data ────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent
CRAWL_DB     = ROOT / "crawl_state.db"
CLUSTER_DB   = ROOT / "clusters.db"
ARTICLES_DB  = ROOT / "articles.db"


def _count(db: Path, table: str, where: str = "") -> int:
    if not db.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db))
        q = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        n = conn.execute(q).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def _fetch(db: Path, query: str, params=()) -> list:
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


pages_crawled     = _count(CRAWL_DB,    "pages")
clusters_total    = _count(CLUSTER_DB,  "clusters")
clusters_ready    = _count(CLUSTER_DB,  "clusters", "status='ready'")
clusters_enriched = _count(CLUSTER_DB,  "clusters", "enriched_at IS NOT NULL")
articles_gen      = _count(ARTICLES_DB, "articles")
articles_approved = _count(ARTICLES_DB, "articles", "status='approved'")
articles_draft    = _count(ARTICLES_DB, "articles", "status='draft'")

scored = _fetch(ARTICLES_DB, "SELECT eval_score FROM articles WHERE eval_score IS NOT NULL")
avg_score = round(sum(r["eval_score"] for r in scored) / len(scored), 1) if scored else None

recent = _fetch(
    ARTICLES_DB,
    "SELECT article_id, consumer_question, status, eval_score, model_used, generated_at, business_line "
    "FROM articles ORDER BY generated_at DESC LIMIT 5",
)

# ─── Greeting ────────────────────────────────────────────────────────────────
hour = datetime.now().hour
greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")

topbar(
    crumbs=[("Studio", False), ("Home", True)],
    actions_html=(
        f'<div style="font-family:JetBrains Mono,monospace;font-size:11.5px;color:#9aa0b1;">'
        f'{datetime.now().strftime("%a %d %b")}</div>'
    ),
)

st.markdown(
    f'<div style="margin:0 0 6px;">'
    f'<div style="font-family:Inter,sans-serif;font-size:11px;font-weight:600;'
    f'letter-spacing:0.08em;text-transform:uppercase;color:#9aa0b1;">Studio</div>'
    f'<div style="font-family:Inter,sans-serif;font-size:30px;font-weight:700;'
    f'letter-spacing:-0.022em;color:#0a0b13;line-height:1.15;margin-top:4px;">'
    f'{greet}. Two ways to create content — pick where you\'re starting from.</div>'
    f'<div style="font-family:Inter,sans-serif;font-size:13.5px;color:#6b7084;'
    f'margin-top:6px;max-width:640px;line-height:1.55;">'
    f'Path A consolidates legacy acko.com pages into authoritative articles. '
    f'Path B lets you write from a blank page with a guided 3-step brief. '
    f'Both feed the same generation pipeline.</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ─── Dual entry heroes ───────────────────────────────────────────────────────
hero_grid(
    path_a={
        "eyebrow": "PATH A · CRAWL-BASED",
        "title": "Consolidate legacy pages",
        "desc": "Crawler reads acko.com sections, groups pages by consumer question, and generates "
                "one authoritative article per cluster. Old pages get 301-mapped.",
        "meta": f"{pages_crawled:,} pages · {clusters_total} clusters · {clusters_ready} ready",
        "cta_label": "Open Crawl Studio",
        "cta_route": "pages/2_clusters.py",
    },
    path_b={
        "eyebrow": "PATH B · BRIEF-BASED",
        "title": "Write something new",
        "desc": "Fill a 3-step brief — topic, audience, research — and Studio runs the same pipeline. "
                "No crawling. Ideal for Enterprise where no legacy pages exist.",
        "meta": "text · PDF · DOCX · reference URLs",
        "cta_label": "Open Brief Studio",
        "cta_route": "pages/0_content_brief.py",
    },
)

# ─── Stat strip ──────────────────────────────────────────────────────────────
stat_row([
    ("Pages crawled",  f"{pages_crawled:,}",                            "across all sections"),
    ("Clusters",       f"{clusters_total}",                              f"{clusters_ready} ready · {clusters_enriched} enriched"),
    ("Articles",       f"{articles_gen}",                                f"{articles_draft} drafts · {articles_approved} approved"),
    ("Avg quality",    (f"{avg_score}" if avg_score else "—"),           "Northstar · out of 5.0"),
])

# ─── Two-column body: activity | right rail ──────────────────────────────────
st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)

left, right = st.columns([1.7, 1], gap="large")

with left:
    if recent:
        tone_for_status = {"approved": "success", "draft": "warning", "rejected": "danger"}
        rows = []
        for a in recent:
            q = (a.get("consumer_question") or "Untitled").strip()
            if len(q) > 58:
                q = q[:56] + "…"
            status = (a.get("status") or "draft").lower()
            bl = (a.get("business_line") or "retail").lower()
            score = a.get("eval_score")
            date = (a.get("generated_at") or "")[:10]
            # Path A or B heuristic — cluster-based have cluster_id, brief-based don't; we don't
            # have that field here, so default icon to "A"
            icon = "A"
            icon_tone = ""
            right_pill = pill(status, tone_for_status.get(status, "neutral"))
            if score:
                right_pill = (
                    f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;'
                    f'color:#0a0b13;font-weight:600;margin-right:10px;">{score:.1f}</span>'
                    f'{right_pill}'
                )
            sub = f"{bl.title()} · {date or '—'}"
            rows.append((icon, icon_tone, q, sub, right_pill))
        segmented = (
            '<div class="rui-seg">'
            '<span class="s on">All</span>'
            '<span class="s">Path A</span>'
            '<span class="s">Path B</span>'
            '</div>'
        )
        activity_feed("Recent activity", rows, right_html=segmented)
    else:
        empty_state(
            "Nothing published yet",
            "Pick Path A or Path B above to generate your first article.",
        )

with right:
    # Pipeline health
    total_passes_est = max(1, clusters_total)
    ready_pct = int(100 * clusters_ready / total_passes_est) if total_passes_est else 0
    enriched_pct = int(100 * clusters_enriched / total_passes_est) if total_passes_est else 0
    gen_pct = int(100 * articles_gen / max(1, clusters_total)) if clusters_total else 0

    health_body = (
        f'<div class="row"><span>Clusters enriched</span><span class="v">{clusters_enriched}/{clusters_total}</span></div>'
        f'<div class="bar"><span style="width:{enriched_pct}%"></span></div>'
        f'<div class="row"><span>Clusters ready</span><span class="v">{clusters_ready}/{clusters_total}</span></div>'
        f'<div class="bar"><span style="width:{ready_pct}%"></span></div>'
        f'<div class="row"><span>Generated</span><span class="v">{articles_gen}/{clusters_total or 1}</span></div>'
        f'<div class="bar"><span style="width:{min(gen_pct,100)}%"></span></div>'
    )
    side_card("Pipeline health", health_body)

    # Needs you — use st.page_link below each row so routing works
    st.markdown(
        '<div class="rui-side-card"><div class="t">Needs you</div>',
        unsafe_allow_html=True,
    )
    any_need = False
    if clusters_ready:
        st.markdown(
            f'<div class="row"><span>{clusters_ready} clusters ready to generate</span></div>',
            unsafe_allow_html=True,
        )
        st.page_link("pages/3_generate.py", label="Open Generate →")
        any_need = True
    if articles_draft:
        st.markdown(
            f'<div class="row"><span>{articles_draft} drafts awaiting review</span></div>',
            unsafe_allow_html=True,
        )
        st.page_link("pages/7_library.py", label="Open Library →")
        any_need = True
    if pages_crawled == 0:
        st.markdown(
            '<div class="row"><span>No pages crawled yet</span></div>',
            unsafe_allow_html=True,
        )
        st.page_link("pages/2_clusters.py", label="Start crawl →")
        any_need = True
    if not any_need:
        st.markdown(
            '<div class="row" style="color:#9aa0b1;">You\'re all caught up.</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    # Tip
    tip_dark(
        "Jump anywhere",
        "Every page, article and cluster is reachable from the sidebar. Hit the section headers to see the full list.",
        kbd="⌘K",
    )

# ─── Footer note ─────────────────────────────────────────────────────────────
st.markdown('<div style="height:48px;"></div>', unsafe_allow_html=True)
st.markdown(
    '<div style="padding:22px 26px;background:#f5f6f8;border-radius:14px;border:1px solid #f0f1f5;">'
    '<div style="font-family:Inter,sans-serif;font-size:11px;font-weight:600;'
    'letter-spacing:0.08em;text-transform:uppercase;color:#9aa0b1;">How it works</div>'
    '<div style="font-family:Inter,sans-serif;font-size:15px;color:#2b2e3a;'
    'margin-top:6px;line-height:1.55;max-width:820px;">'
    'Studio is a <b>blog-writing agent</b>, not a page rewriter. It reads every '
    'source in a cluster (or brief) and produces <b>one authoritative article</b> '
    'that answers the consumer question better than any single source — then '
    'scores it on the Northstar rubric before you ever see it.</div>'
    '</div>',
    unsafe_allow_html=True,
)
