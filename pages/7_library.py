"""
Article Library — One-click preview + inline editing of generated articles
==========================================================================
Demo-friendly gallery for reviewing, editing, and presenting generated content.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Dict

import streamlit as st
import streamlit.components.v1 as components

# Allow "from ui import ..." when run from Streamlit's pages/ dir
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import apply_theme, sidebar, page_header, section_label, stat_row, pill, empty_state  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DB_PATH = PROJECT_ROOT / "articles.db"
TEMPLATE_DIR = PROJECT_ROOT / "templates"

TEMPLATE_MAP = {
    "transactional": "transactional.html",
    "informational": "informational.html",
    "longtail": "longtail.html",
    "enterprise": "enterprise.html",
}
FALLBACK_TEMPLATE = "informational.html"

SECTION_TYPES = [
    "content_block", "bullet_list", "faq", "steps", "comparison",
    "expert_tip", "cta", "related_articles", "table",
    "callout_info", "callout_tip", "callout_warning",
]


# ---------------------------------------------------------------------------
# Lazy module loader
# ---------------------------------------------------------------------------

def _get_generate_module():
    """Lazy-import the generate page module for render_html / update_article."""
    import importlib.util
    gen_path = PROJECT_ROOT / "pages" / "3_generate.py"
    spec = importlib.util.spec_from_file_location("gen", str(gen_path))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_articles() -> List[Dict]:
    if not ARTICLES_DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM articles ORDER BY generated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Library — Acko Content Studio", page_icon="●", layout="wide")

    apply_theme()
    sidebar(current="library")

    page_header(
        eyebrow="Output",
        title="Library",
        meta="Browse · Preview · Edit · Approve",
    )

    articles = load_articles()

    if not articles:
        empty_state(
            "No articles yet",
            "Go to Generate to create your first article from a cluster or brief.",
        )
        return

    # ---- Summary metrics ----
    total = len(articles)
    approved = sum(1 for a in articles if a.get("status") == "approved")
    scored = [a for a in articles if a.get("eval_score")]
    avg_score = sum(a["eval_score"] for a in scored) / len(scored) if scored else 0
    enterprise_count = sum(1 for a in articles if (a.get("business_line") or "retail") == "enterprise")
    retail_count     = sum(1 for a in articles if (a.get("business_line") or "retail") == "retail")
    longtail_count   = sum(1 for a in articles if (a.get("business_line") or "retail") == "longtail")

    stat_row([
        ("Total",       str(total)),
        ("Approved",    str(approved)),
        ("Avg quality", ("{:.1f}".format(avg_score) if scored else "—"), "out of 5.0"),
        ("Enterprise",  str(enterprise_count)),
        ("Retail",      str(retail_count)),
        ("Long-tail",   str(longtail_count)),
    ])

    st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)

    # ---- Filters ----
    col_filter1, col_filter2, col_filter3, col_filter4 = st.columns([3, 1, 1, 1])

    with col_filter1:
        search = st.text_input("", placeholder="Search by topic, slug, or keyword…", label_visibility="collapsed")

    with col_filter2:
        status_filter = st.selectbox("Status", ["All statuses", "approved", "draft", "rejected"], index=0, label_visibility="collapsed")

    with col_filter3:
        biz_filter = st.selectbox("Biz line", ["All lines", "enterprise", "retail", "longtail"], index=0, label_visibility="collapsed")

    with col_filter4:
        sort_by = st.selectbox("Sort", ["Newest first", "Highest score", "Lowest score"], index=0, label_visibility="collapsed")

    # Apply filters
    filtered = articles
    if search:
        sl = search.lower()
        filtered = [a for a in filtered
                    if sl in (a.get("consumer_question") or "").lower()
                    or sl in (a.get("suggested_slug") or "").lower()
                    or sl in (a.get("page_classification") or "").lower()]

    if status_filter != "All statuses":
        filtered = [a for a in filtered if a.get("status") == status_filter]

    if biz_filter != "All lines":
        filtered = [a for a in filtered if (a.get("business_line") or "retail") == biz_filter]

    if sort_by == "Highest score":
        filtered.sort(key=lambda a: a.get("eval_score") or 0, reverse=True)
    elif sort_by == "Lowest score":
        filtered.sort(key=lambda a: a.get("eval_score") or 0)

    st.divider()

    # ---- Check if viewing a specific article ----
    if "library_view_id" in st.session_state and st.session_state.library_view_id is not None:
        _render_article_view(st.session_state.library_view_id, articles)
        return

    # ---- Article grid ----
    if not filtered:
        empty_state("No articles match your filters", "Try clearing the search or changing the filters above.")
        return

    st.markdown(
        f"<div style='font-family:Inter,sans-serif;font-size:0.78rem;color:#8d969e;margin:8px 0 16px 0;'>"
        f"{len(filtered)} article{'' if len(filtered)==1 else 's'}</div>",
        unsafe_allow_html=True,
    )

    for row_start in range(0, len(filtered), 3):
        cols = st.columns(3, gap="medium")
        for col_idx in range(3):
            art_idx = row_start + col_idx
            if art_idx >= len(filtered):
                break
            art = filtered[art_idx]
            with cols[col_idx]:
                _render_article_card(art)


def _render_article_card(art: Dict) -> None:
    """Render a single article as a minimal card (design.md)."""
    question       = art.get("consumer_question", "Untitled")
    score          = art.get("eval_score")
    status         = (art.get("status") or "draft").lower()
    slug           = art.get("suggested_slug", "")
    classification = art.get("page_classification", "")
    layout         = art.get("layout_type", "")
    generated_at   = (art.get("generated_at") or "")[:10]
    model          = (art.get("model_used") or "").replace("gpt-", "")
    business_line  = (art.get("business_line") or "retail").lower()

    tone_for_status = {"approved": "success", "draft": "warning", "rejected": "danger"}
    score_str = "{:.1f}".format(score) if score else "—"
    bar_w     = int((score / 5) * 100) if score else 0

    meta_tags = []
    if classification:
        meta_tags.append(classification)
    if layout:
        meta_tags.append(layout)
    if model:
        meta_tags.append(model)
    if generated_at:
        meta_tags.append(generated_at)
    meta_html = "".join(
        f'<span style="font-family:Inter,sans-serif;font-size:0.7rem;color:#8d969e;'
        f'border:1px solid #e5e5e5;padding:2px 8px;border-radius:9999px;">{t}</span>'
        for t in meta_tags
    )

    q_short = (question[:78] + "…") if len(question) > 78 else question

    # Path A/B badge — inferred from input_type if present, default to A
    _input_type = (art.get("input_type") or art.get("source_type") or "crawled").lower()
    is_path_b = _input_type in ("brief", "ref_url", "brief_based")
    path_letter = "B" if is_path_b else "A"
    path_bg = "#0a0b13" if is_path_b else "#eeebff"
    path_fg = "#ffffff" if is_path_b else "#2b1d9e"
    path_badge = (
        f'<div style="width:22px;height:22px;border-radius:6px;background:{path_bg};'
        f'color:{path_fg};font-family:JetBrains Mono,monospace;font-size:11px;font-weight:700;'
        f'display:flex;align-items:center;justify-content:center;flex-shrink:0;">{path_letter}</div>'
    )

    card_html = (
        f'<div style="background:#fff;border:1px solid #e5e5e5;border-radius:16px;'
        f'padding:20px;margin-bottom:6px;min-height:210px;display:flex;flex-direction:column;">'
        # Top row
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;">'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">'
        f'{path_badge}'
        f'{pill(status, tone_for_status.get(status, "neutral"))}'
        f'{pill(business_line, "neutral")}'
        f'</div>'
        f'<div style="text-align:right;white-space:nowrap;">'
        f'<span style="font-family:\'Space Grotesk\',sans-serif;font-size:1.5rem;'
        f'font-weight:500;letter-spacing:-0.24px;color:#191c1f;">{score_str}</span>'
        f'<span style="font-family:Inter,sans-serif;font-size:0.75rem;color:#8d969e;"> / 5</span>'
        f'</div></div>'
        # Score bar
        f'<div style="background:#f4f4f4;border-radius:4px;height:3px;margin:14px 0;overflow:hidden;">'
        f'<div style="background:#191c1f;height:3px;width:{bar_w}%;"></div>'
        f'</div>'
        # Title
        f'<div style="font-family:\'Space Grotesk\',sans-serif;font-size:1rem;font-weight:500;'
        f'letter-spacing:-0.16px;color:#191c1f;line-height:1.35;margin-bottom:6px;flex:1;">{q_short}</div>'
        # Slug
        f'<div style="font-family:Inter,sans-serif;font-size:0.78rem;color:#8d969e;'
        f'margin-bottom:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">/{slug}</div>'
        # Meta tags
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;">{meta_html}</div>'
        f'</div>'
    )

    st.markdown(card_html, unsafe_allow_html=True)

    if st.button("Open article →", key="preview_{}".format(art["article_id"]),
                 use_container_width=True, type="primary"):
        st.session_state.library_view_id = art["article_id"]
        st.rerun()


# ---------------------------------------------------------------------------
# Article detail view with preview + edit
# ---------------------------------------------------------------------------

def _render_article_view(article_id: int, articles: List[Dict]) -> None:
    """Full-screen article view with Preview, Edit, JSON, and HTML tabs."""
    art = None
    for a in articles:
        if a["article_id"] == article_id:
            art = a
            break

    if not art:
        st.error("Article not found.")
        st.session_state.library_view_id = None
        return

    # Back button + export
    _bk, _dl_html, _dl_json = st.columns([2, 1, 1])
    with _bk:
        if st.button("← Back to Library", type="secondary"):
            ss_key = "edit_sections_{}".format(article_id)
            if ss_key in st.session_state:
                del st.session_state[ss_key]
            st.session_state.library_view_id = None
            st.rerun()
    _slug = art.get("suggested_slug") or "article-{}".format(article_id)
    _html_for_dl = art.get("html_content") or ""
    if not _html_for_dl:
        try:
            _gen_mod = _get_generate_module()
            _html_for_dl = _gen_mod.render_html(json.loads(art.get("structured_json") or "{}"))
        except Exception:
            _html_for_dl = ""
    with _dl_html:
        st.download_button(
            "⬇️ Download HTML",
            _html_for_dl or "<p>(empty)</p>",
            file_name="{}.html".format(_slug),
            mime="text/html",
            key="dl_html_{}".format(article_id),
            use_container_width=True,
        )
    with _dl_json:
        st.download_button(
            "⬇️ Download JSON",
            art.get("structured_json") or "{}",
            file_name="{}.json".format(_slug),
            mime="application/json",
            key="dl_json_{}".format(article_id),
            use_container_width=True,
        )

    question      = art.get("consumer_question", "Untitled")
    score         = art.get("eval_score")
    status        = art.get("status", "draft")
    business_line = art.get("business_line") or "retail"

    tone_for_status = {"approved": "success", "draft": "warning", "rejected": "danger"}
    layout_pill = pill(art.get("layout_type", "") or "—", "neutral")

    st.markdown(
        f"""
        <div style="background:#fff;border:1px solid #e5e5e5;border-radius:20px;padding:28px 32px;margin-bottom:24px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:24px;">
            <div style="flex:1;">
              <div style="display:flex;gap:6px;margin-bottom:14px;">
                {pill(status, tone_for_status.get(status, "neutral"))}
                {pill(business_line, "neutral")}
                {layout_pill}
              </div>
              <h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.75rem;font-weight:500;
                         letter-spacing:-0.32px;color:#191c1f;margin:0 0 8px 0;line-height:1.2;">{question}</h2>
              <div style="font-family:Inter,sans-serif;font-size:0.82rem;color:#8d969e;">
                /{art.get("suggested_slug","")} · {art.get("model_used","")} · {(art.get("generated_at") or "")[:10]}
              </div>
            </div>
            <div style="text-align:center;background:#f4f4f4;border-radius:16px;padding:18px 28px;flex-shrink:0;">
              <div style="font-family:'Space Grotesk',sans-serif;font-size:2.75rem;font-weight:500;
                          letter-spacing:-0.44px;color:#191c1f;line-height:1;">
                {f"{score:.1f}" if score else "—"}
              </div>
              <div style="font-family:Inter,sans-serif;font-size:0.7rem;letter-spacing:1.2px;
                          text-transform:uppercase;color:#8d969e;margin-top:6px;">Score / 5</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Eval breakdown
    try:
        eval_data = json.loads(art.get("eval_json") or "{}")
        scores_obj = eval_data.get("scores", {})
        dim_labels = {
            "question_clarity": "Question Clarity",
            "content_depth":    "Content Depth",
            "structure":        "Structure",
            "brand_voice":      "Brand Voice",
            "replaceability":   "Replaceability",
            "design":           "Design",
        }
        if scores_obj:
            dim_html = ""
            for dk, dl in dim_labels.items():
                info = scores_obj.get(dk, {})
                s = info.get("score", 0) if isinstance(info, dict) else 0
                bar = int(s / 5 * 100)
                sc = "#059669" if s >= 4 else "#D97706" if s >= 3 else "#DC2626"
                dim_html += f"""
                <div style="margin-bottom:8px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                    <span style="font-size:0.78rem;font-weight:600;color:#334155;">{dl}</span>
                    <span style="font-size:0.78rem;font-weight:800;color:{sc};">{s}/5</span>
                  </div>
                  <div style="background:#F1F5F9;border-radius:4px;height:6px;overflow:hidden;">
                    <div style="background:{sc};height:6px;width:{bar}%;border-radius:4px;"></div>
                  </div>
                </div>"""
            strengths = eval_data.get("top_strengths", [])
            issues    = eval_data.get("top_issues", [])
            with st.expander("📊 Quality breakdown", expanded=False):
                st.markdown(f"<div style='padding:4px 0;'>{dim_html}</div>", unsafe_allow_html=True)
                if strengths:
                    st.markdown("**✅ Strengths:** " + "  ·  ".join(strengths))
                if issues:
                    st.markdown("**⚠️ Issues:** " + "  ·  ".join(issues))
    except (json.JSONDecodeError, TypeError):
        pass

    st.divider()

    # ---- Tabs ----
    tab_preview, tab_edit, tab_quality, tab_json, tab_html = st.tabs(
        ["👁️ Preview", "✏️ Edit", "✅ Quality", "📋 JSON", "🔧 HTML Source"]
    )

    with tab_preview:
        _render_preview_tab(art)

    with tab_edit:
        _render_edit_tab(art)

    with tab_quality:
        _render_quality_tab(art)

    with tab_json:
        try:
            parsed = json.loads(art.get("structured_json") or "{}")
            st.json(parsed)
        except (json.JSONDecodeError, TypeError):
            st.code(art.get("structured_json") or "No JSON available")

    with tab_html:
        html_content = art.get("html_content") or ""
        if html_content:
            st.code(html_content[:10000], language="html")
        else:
            st.info("No HTML stored.")

    # Source URLs
    st.divider()
    try:
        source_urls = json.loads(art.get("source_urls_json") or "[]")
        if source_urls:
            st.markdown("**Source pages ({}):**".format(len(source_urls)))
            for url in source_urls:
                st.markdown("- [{}]({})".format(url, url))
    except (json.JSONDecodeError, TypeError):
        pass


def _render_preview_tab(art: Dict) -> None:
    """Render the article preview."""
    html_content = art.get("html_content") or ""
    if not html_content:
        try:
            gen = _get_generate_module()
            result = json.loads(art.get("structured_json") or "{}")
            html_content = gen.render_html(result)
        except Exception as e:
            html_content = "<p>Failed to render: {}</p>".format(e)

    components.html(html_content, height=900, scrolling=True)


# ---------------------------------------------------------------------------
# Quality tab — EEAT + SEO/GEO drawer with per-issue Fix this
# ---------------------------------------------------------------------------

def _api_key_from_env() -> str:
    import os
    # 1. Session-state override (entered by the user on this page)
    k = (st.session_state.get("OPENAI_API_KEY_INPUT") or "").strip()
    if k:
        return k
    # 2. Env var
    k = os.environ.get("OPENAI_API_KEY", "").strip()
    if k:
        return k
    # 3. Streamlit secrets
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


def _api_key_input_widget(key_suffix: str = "lib") -> None:
    """Render a password input for OPENAI_API_KEY when none is found in env/secrets."""
    import os
    has_env = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if not has_env:
        try:
            has_env = bool(str(st.secrets.get("OPENAI_API_KEY", "")).strip())
        except Exception:
            pass
    if has_env:
        return
    with st.expander("🔑 OpenAI API key (required for evaluation + fixes)",
                     expanded=not bool(st.session_state.get("OPENAI_API_KEY_INPUT"))):
        st.text_input(
            "OpenAI API key",
            type="password",
            placeholder="sk-...",
            key="OPENAI_API_KEY_INPUT",
            label_visibility="collapsed",
        )
        st.caption("Stored in this session only — never written to disk.")


def _persist_eval(article_id: int, eval_result: Dict) -> None:
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


def _persist_article(article_id: int, article: Dict) -> None:
    """Save updated structured_json + re-render html via generate module."""
    gen = _get_generate_module()
    try:
        html = gen.render_html(article)
    except Exception:
        html = ""
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.execute(
        """UPDATE articles SET structured_json = ?, html_content = ?
           WHERE article_id = ?""",
        (json.dumps(article, ensure_ascii=False), html, article_id),
    )
    conn.commit()
    conn.close()


def _render_quality_tab(art: Dict) -> None:
    """EEAT + SEO/GEO scorecard with per-issue Fix this buttons."""
    try:
        from evaluation_v2 import render_eval_drawer, run_evaluation, apply_fix
    except Exception as e:
        st.error("evaluation_v2 import failed: {}".format(e))
        return

    article_id = art["article_id"]
    _api_key_input_widget("quality_{}".format(article_id))
    raw_eval = art.get("eval_json")
    eval_payload = None
    if raw_eval:
        try:
            parsed = json.loads(raw_eval)
            if isinstance(parsed, dict) and "overall_score" in parsed:
                eval_payload = parsed
        except Exception:
            eval_payload = None

    col_l, col_r = st.columns([3, 1])
    with col_r:
        if st.button("Re-run evaluation", key="rerun_eval_{}".format(article_id), use_container_width=True):
            ak = _api_key_from_env()
            if not ak:
                st.error("Set OPENAI_API_KEY first.")
            else:
                try:
                    src_urls = json.loads(art.get("source_urls_json") or "[]")
                except Exception:
                    src_urls = []
                with st.spinner("Evaluating..."):
                    res = run_evaluation(
                        ak,
                        art.get("structured_json") or "{}",
                        src_urls,
                        art.get("consumer_question") or "",
                        art.get("model_used") or "gpt-4.1",
                    )
                if res and "error" not in res:
                    _persist_eval(article_id, res)
                    st.success("Evaluation updated.")
                    st.rerun()
                else:
                    st.error((res or {}).get("error", "Evaluation failed."))

    if not eval_payload:
        with col_l:
            st.caption("No evaluation on file. Click 'Re-run evaluation' to score this article.")
        return

    def _on_fix(issue):
        ak = _api_key_from_env()
        if not ak:
            st.error("Set OPENAI_API_KEY to apply fixes.")
            return
        try:
            article = json.loads(art.get("structured_json") or "{}")
        except Exception:
            article = {}
        with st.spinner("Applying fix: {}...".format((issue.get("what") or "")[:60])):
            updated = apply_fix(ak, article, issue, full_article=article,
                                model=art.get("model_used") or "gpt-4.1")
        _persist_article(article_id, updated)
        st.success("Fix applied. Re-run evaluation to see updated score.")
        st.rerun()

    with col_l:
        render_eval_drawer(eval_payload, article_id, on_fix_callback=_on_fix)


# ---------------------------------------------------------------------------
# Edit tab
# ---------------------------------------------------------------------------

def _render_edit_tab(art: Dict) -> None:
    """Full article editor with metadata, sections, reorder, delete, add."""
    article_id = art["article_id"]

    try:
        struct = json.loads(art.get("structured_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        st.error("Could not parse article JSON for editing.")
        return

    # --- Session state for sections ---
    ss_key = "edit_sections_{}".format(article_id)
    # Version counter to force widget refresh after reorder/delete/add
    ver_key = "edit_ver_{}".format(article_id)
    if ver_key not in st.session_state:
        st.session_state[ver_key] = 0
    ver = st.session_state[ver_key]

    if ss_key not in st.session_state:
        st.session_state[ss_key] = list(struct.get("sections", []))

    sections = st.session_state[ss_key]

    # ================================================================
    # METADATA
    # ================================================================
    with st.expander("📄 Page Metadata", expanded=True):
        ed_h1 = st.text_input("H1 (Main Heading)", value=struct.get("h1", ""),
                               key="ed_h1_{}_{}".format(article_id, ver))
        ed_page_title = st.text_input("Page Title (SEO)", value=struct.get("page_title", ""),
                                       key="ed_title_{}_{}".format(article_id, ver))
        ed_meta = st.text_area("Meta Description", value=struct.get("meta_description", ""),
                                height=80, key="ed_meta_{}_{}".format(article_id, ver))
        ed_subtitle = st.text_input("Subtitle", value=struct.get("subtitle", ""),
                                     key="ed_sub_{}_{}".format(article_id, ver))
        ed_slug = st.text_input("Suggested Slug", value=struct.get("suggested_slug", ""),
                                 key="ed_slug_{}_{}".format(article_id, ver))

    # ================================================================
    # QUICK ANSWER
    # ================================================================
    with st.expander("💡 Quick Answer"):
        ed_quick_answer = st.text_area("Quick Answer Box",
                                        value=struct.get("quick_answer", ""),
                                        height=100,
                                        key="ed_qa_{}_{}".format(article_id, ver))

    # ================================================================
    # SECTION REORDER / DELETE CONTROLS
    # ================================================================
    st.markdown("### Sections ({})".format(len(sections)))

    # Compact reorder strip
    reorder_happened = False
    for idx, sec in enumerate(sections):
        sec_type = sec.get("type", "content_block")
        sec_heading = sec.get("heading", "") or "(no heading)"
        cols = st.columns([0.5, 4, 1, 1, 1])
        cols[0].markdown("**{}**".format(idx + 1))
        cols[1].markdown("**{}** — {}".format(sec_type, sec_heading[:60]))
        if idx > 0 and cols[2].button("⬆️", key="up_{}_{}_{}".format(article_id, idx, ver)):
            sections[idx], sections[idx - 1] = sections[idx - 1], sections[idx]
            st.session_state[ver_key] = ver + 1
            reorder_happened = True
        if idx < len(sections) - 1 and cols[3].button("⬇️", key="dn_{}_{}_{}".format(article_id, idx, ver)):
            sections[idx], sections[idx + 1] = sections[idx + 1], sections[idx]
            st.session_state[ver_key] = ver + 1
            reorder_happened = True
        if cols[4].button("🗑️", key="del_{}_{}_{}".format(article_id, idx, ver)):
            sections.pop(idx)
            st.session_state[ver_key] = ver + 1
            reorder_happened = True

    if reorder_happened:
        st.rerun()

    st.divider()

    # ================================================================
    # SECTION CONTENT EDITORS
    # ================================================================
    for idx, sec in enumerate(sections):
        sec_type = sec.get("type", "content_block")
        sec_heading = sec.get("heading", "") or "(no heading)"

        with st.expander("Section {}: {} — {}".format(idx + 1, sec_type, sec_heading[:50]),
                         expanded=False):
            _render_section_editor(article_id, idx, sec, ver)

    # ================================================================
    # ADD NEW SECTION
    # ================================================================
    st.divider()
    add_cols = st.columns([2, 1])
    with add_cols[0]:
        new_type = st.selectbox("New section type", SECTION_TYPES,
                                key="new_type_{}_{}".format(article_id, ver))
    with add_cols[1]:
        st.markdown("")  # spacer
        st.markdown("")
        if st.button("➕ Add Section", key="add_sec_{}_{}".format(article_id, ver),
                     use_container_width=True):
            new_sec = _make_empty_section(new_type)
            sections.append(new_sec)
            st.session_state[ver_key] = ver + 1
            st.rerun()

    # ================================================================
    # SAVE & RE-RENDER
    # ================================================================
    st.divider()
    if st.button("💾 Save & Re-render", type="primary", use_container_width=True,
                 key="save_{}_{}".format(article_id, ver)):
        _save_edits(article_id, struct, sections, ed_h1, ed_page_title, ed_meta,
                    ed_subtitle, ed_slug, ed_quick_answer)


def _render_section_editor(article_id: int, idx: int, sec: Dict, ver: int) -> None:
    """Render type-aware editor for a single section."""
    sec_type = sec.get("type", "content_block")
    content = sec.get("content", {})
    if content is None:
        content = {}

    pfx = "sec_{}_{}_{}_".format(article_id, idx, ver)

    # Type selector
    type_idx = SECTION_TYPES.index(sec_type) if sec_type in SECTION_TYPES else 0
    new_type = st.selectbox("Section type", SECTION_TYPES, index=type_idx, key=pfx + "type")
    sec["type"] = new_type

    # Heading
    sec["heading"] = st.text_input("Heading", value=sec.get("heading", ""), key=pfx + "heading")

    # Type-specific content editor
    if new_type == "content_block":
        html_val = ""
        if isinstance(content, dict):
            html_val = content.get("html", "")
        elif isinstance(content, str):
            html_val = content
        new_html = st.text_area("HTML Content", value=html_val, height=250, key=pfx + "html")
        sec["content"] = {"html": new_html}

    elif new_type == "bullet_list":
        items = []
        if isinstance(content, dict):
            items = content.get("items", [])
        elif isinstance(content, list):
            items = content
        items_text = "\n".join(items) if items else ""
        new_items_text = st.text_area("Bullet items (one per line)", value=items_text,
                                       height=200, key=pfx + "bullets")
        new_items = [line for line in new_items_text.split("\n") if line.strip()]
        sec["content"] = {"items": new_items}

    elif new_type == "faq":
        faq_items = []
        if isinstance(content, dict):
            faq_items = content.get("items", [])
        st.markdown("**FAQ items:**")
        updated_faqs = []
        for fi, faq in enumerate(faq_items):
            fq = faq.get("question", "") if isinstance(faq, dict) else ""
            fa = faq.get("answer", "") if isinstance(faq, dict) else ""
            q = st.text_input("Q{}".format(fi + 1), value=fq, key=pfx + "fq_{}".format(fi))
            a = st.text_area("A{}".format(fi + 1), value=fa, height=80, key=pfx + "fa_{}".format(fi))
            updated_faqs.append({"question": q, "answer": a})
            st.markdown("---")
        # Add FAQ button
        if st.button("➕ Add FAQ pair", key=pfx + "add_faq"):
            faq_items.append({"question": "", "answer": ""})
            sec["content"] = {"items": faq_items}
            st.rerun()
        sec["content"] = {"items": updated_faqs}

    elif new_type == "steps":
        step_items = []
        if isinstance(content, list):
            step_items = content
        elif isinstance(content, dict):
            step_items = content.get("steps", content.get("items", []))
        st.markdown("**Steps:**")
        updated_steps = []
        for si, step in enumerate(step_items):
            s_title = step.get("title", "") if isinstance(step, dict) else ""
            s_desc = step.get("description", "") if isinstance(step, dict) else ""
            t = st.text_input("Step {} title".format(si + 1), value=s_title,
                               key=pfx + "st_{}".format(si))
            d = st.text_area("Step {} description".format(si + 1), value=s_desc,
                              height=60, key=pfx + "sd_{}".format(si))
            updated_steps.append({"step": si + 1, "title": t, "description": d})
        if st.button("➕ Add step", key=pfx + "add_step"):
            step_items.append({"step": len(step_items) + 1, "title": "", "description": ""})
            if isinstance(content, list):
                sec["content"] = step_items
            else:
                sec["content"]["steps"] = step_items
            st.rerun()
        sec["content"] = updated_steps

    elif new_type in ("callout_info", "callout_tip", "callout_warning"):
        label = content.get("label", "") if isinstance(content, dict) else ""
        text = content.get("text", "") if isinstance(content, dict) else ""
        new_label = st.text_input("Label", value=label, key=pfx + "clabel")
        new_text = st.text_area("Callout text", value=text, height=100, key=pfx + "ctext")
        sec["content"] = {"label": new_label, "text": new_text}

    elif new_type == "expert_tip":
        quote = content.get("quote", "") if isinstance(content, dict) else ""
        name = content.get("name", "") if isinstance(content, dict) else ""
        title = content.get("title", "") if isinstance(content, dict) else ""
        new_quote = st.text_area("Expert quote", value=quote, height=100, key=pfx + "eq")
        new_name = st.text_input("Expert name", value=name, key=pfx + "en")
        new_title = st.text_input("Expert title/designation", value=title, key=pfx + "et")
        sec["content"] = {"quote": new_quote, "name": new_name, "title": new_title}

    elif new_type == "cta":
        heading = content.get("heading", "") if isinstance(content, dict) else ""
        desc = content.get("description", "") if isinstance(content, dict) else ""
        btn_text = content.get("button_text", "") if isinstance(content, dict) else ""
        btn_url = content.get("button_url", "") if isinstance(content, dict) else ""
        sec["content"] = {
            "heading": st.text_input("CTA heading", value=heading, key=pfx + "ch"),
            "description": st.text_area("CTA description", value=desc, height=60, key=pfx + "cd"),
            "button_text": st.text_input("Button text", value=btn_text, key=pfx + "cb"),
            "button_url": st.text_input("Button URL", value=btn_url, key=pfx + "cu"),
        }

    elif new_type == "comparison":
        rows = []
        if isinstance(content, dict):
            rows = content.get("rows", [])
        st.markdown("**Comparison rows:**")
        updated_rows = []
        for ri, row in enumerate(rows):
            if isinstance(row, dict):
                rc = st.columns(3)
                f = rc[0].text_input("Feature", value=row.get("feature", ""),
                                      key=pfx + "cf_{}".format(ri))
                a_val = rc[1].text_input("Option A", value=row.get("option_a", ""),
                                          key=pfx + "ca_{}".format(ri))
                b_val = rc[2].text_input("Option B", value=row.get("option_b", ""),
                                          key=pfx + "cb_{}".format(ri))
                updated_rows.append({"feature": f, "option_a": a_val, "option_b": b_val})
        if st.button("➕ Add row", key=pfx + "add_row"):
            rows.append({"feature": "", "option_a": "", "option_b": ""})
            sec["content"] = {"rows": rows}
            st.rerun()
        sec["content"] = {"rows": updated_rows}

    else:
        # Fallback: raw JSON editor
        raw = json.dumps(content, indent=2, ensure_ascii=False) if content else "{}"
        new_raw = st.text_area("Content (JSON)", value=raw, height=200, key=pfx + "raw")
        try:
            sec["content"] = json.loads(new_raw)
        except json.JSONDecodeError:
            st.warning("Invalid JSON — will use previous content on save.")

    # Key takeaway (optional, for any section type)
    kt = sec.get("key_takeaway", "") or ""
    new_kt = st.text_input("Key takeaway (optional callout)", value=kt, key=pfx + "kt")
    sec["key_takeaway"] = new_kt if new_kt.strip() else None


def _make_empty_section(sec_type: str) -> Dict:
    """Create an empty section dict for a given type."""
    base = {"type": sec_type, "heading": "", "key_takeaway": None}
    if sec_type == "content_block":
        base["content"] = {"html": ""}
    elif sec_type == "bullet_list":
        base["content"] = {"items": []}
    elif sec_type == "faq":
        base["content"] = {"items": [{"question": "", "answer": ""}]}
    elif sec_type == "steps":
        base["content"] = [{"step": 1, "title": "", "description": ""}]
    elif sec_type in ("callout_info", "callout_tip", "callout_warning"):
        base["content"] = {"text": "", "label": ""}
    elif sec_type == "expert_tip":
        base["content"] = {"quote": "", "name": "", "title": ""}
    elif sec_type == "cta":
        base["content"] = {"heading": "", "description": "", "button_text": "", "button_url": ""}
    elif sec_type == "comparison":
        base["content"] = {"rows": [{"feature": "", "option_a": "", "option_b": ""}]}
    else:
        base["content"] = {}
    return base


def _save_edits(article_id: int, struct: Dict, sections: List[Dict],
                ed_h1: str, ed_page_title: str, ed_meta: str,
                ed_subtitle: str, ed_slug: str, ed_quick_answer: str) -> None:
    """Assemble updated JSON, re-render HTML, and save to DB."""
    updated = dict(struct)
    updated["h1"] = ed_h1
    updated["page_title"] = ed_page_title
    updated["meta_description"] = ed_meta
    updated["subtitle"] = ed_subtitle
    updated["suggested_slug"] = ed_slug
    updated["quick_answer"] = ed_quick_answer
    updated["sections"] = sections

    gen = _get_generate_module()

    try:
        new_html = gen.render_html(updated)
    except Exception as e:
        st.error("Failed to render HTML: {}".format(e))
        return

    try:
        gen.update_article(article_id, updated, new_html)
    except Exception as e:
        st.error("Failed to save: {}".format(e))
        return

    # Clear edit session state so next load reads fresh DB data
    ss_key = "edit_sections_{}".format(article_id)
    ver_key = "edit_ver_{}".format(article_id)
    if ss_key in st.session_state:
        del st.session_state[ss_key]
    if ver_key in st.session_state:
        del st.session_state[ver_key]

    st.success("Article saved and re-rendered!")
    st.rerun()


main()
