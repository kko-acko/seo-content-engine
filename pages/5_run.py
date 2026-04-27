"""
Run detail — most recent generation run
Pipeline tracker + terminal-style log + article preview drawer.
Reads the latest article from articles.db and reconstructs the run view.
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui import (
    apply_theme, sidebar, page_header, section_label,
    pipeline_tracker, log_panel, pill, empty_state, stat_row,
)

st.set_page_config(page_title="Run — Acko Content Studio", page_icon="●", layout="wide")
apply_theme()
sidebar(current="run")

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DB = ROOT / "articles.db"


def _latest_article():
    if not ARTICLES_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(ARTICLES_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM articles ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _article_by_id(article_id: int):
    if not ARTICLES_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(ARTICLES_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM articles WHERE article_id = ?", (article_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


# Resolve which run to show — either from URL-less session or the latest
selected_id = st.session_state.get("run_view_id")
art = _article_by_id(selected_id) if selected_id else _latest_article()

page_header(
    eyebrow="Step 5",
    title="Run",
    meta="Live 3-pass pipeline" if art else "No runs yet",
)

if not art:
    empty_state(
        "No runs yet",
        "Generate your first article from Path A (Crawl Studio) or Path B (Brief Studio). "
        "The most recent run will show here.",
    )
    st.stop()

# ─── Header info ────────────────────────────────────────────────────────────
question = art.get("consumer_question") or "Untitled"
status = (art.get("status") or "draft").lower()
business_line = (art.get("business_line") or "retail").lower()
score = art.get("eval_score")
model = (art.get("model_used") or "").replace("gpt-", "")
generated_at = (art.get("generated_at") or "")[:16].replace("T", " · ")
word_count = art.get("word_count") or 0
input_type = (art.get("input_type") or art.get("source_type") or "crawled").lower()
is_path_b = input_type in ("brief", "ref_url", "brief_based")
path_letter = "B" if is_path_b else "A"

st.markdown(
    f'<div style="display:flex;align-items:center;gap:14px;margin:4px 0 24px;">'
    f'<div style="width:40px;height:40px;border-radius:10px;'
    f'background:{"#0a0b13" if is_path_b else "#eeebff"};'
    f'color:{"#ffffff" if is_path_b else "#2b1d9e"};'
    f'font-family:JetBrains Mono,monospace;font-size:16px;font-weight:700;'
    f'display:flex;align-items:center;justify-content:center;">{path_letter}</div>'
    f'<div style="flex:1;">'
    f'<div style="font-family:Inter,sans-serif;font-size:18px;font-weight:600;'
    f'letter-spacing:-0.01em;color:#0a0b13;">{question}</div>'
    f'<div style="font-family:Inter,sans-serif;font-size:12.5px;color:#6b7084;margin-top:3px;">'
    f'Path {path_letter} · {business_line.title()} · {word_count} words · {model or "gpt-4.1"} · {generated_at}'
    f'</div></div>'
    f'<div>{pill(status, {"approved":"success","draft":"warning","rejected":"danger"}.get(status,"neutral"))}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ─── Pipeline tracker ───────────────────────────────────────────────────────
# For a completed run: all 4 steps done. For in-progress we'd animate.
section_label("Pipeline")
# current = 4 means all steps done (disc shows ✓ for i<current)
pipeline_tracker(
    ["Extract sources", "Generate draft", "Editor pass", "Evaluate (Northstar)"],
    current=4,
)

st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)

# ─── Two-col body: log + article drawer ─────────────────────────────────────
left, right = st.columns([1.4, 1], gap="large")

with left:
    section_label("Run log")
    # Synthesize a log from what we know
    lines = []
    if input_type == "brief":
        lines.append(("brief", "ok", "loaded brief as cluster source"))
    elif input_type == "ref_url":
        lines.append(("refurl", "ok", "fetched content from reference URLs"))
    else:
        lines.append(("crawl", "ok", f"loaded crawled pages for cluster"))
    lines.append(("extract", "ok", "summarized source pages for grounding"))
    lines.append(("gen", "", f"draft generated · {word_count} words · {model or 'gpt-4.1'}"))
    lines.append(("editor", "ok", "editor pass applied · enforced section variety"))
    if score:
        tone = "ok" if score >= 4.0 else ("warn" if score >= 3.0 else "")
        lines.append(("eval", tone, f"Northstar score {score:.1f}/5 · status = {status}"))
    else:
        lines.append(("eval", "warn", "no evaluation run"))
    lines.append(("done", "ok", f"article saved · /library?view={art.get('article_id')}"))
    log_panel(lines, cursor=False)

with right:
    section_label("Article preview")
    # Minimal preview drawer
    score_display = f"{score:.1f}" if score else "—"
    score_color = "#15a06b" if (score or 0) >= 4.0 else ("#d08400" if (score or 0) >= 3.0 else "#d54747")
    st.markdown(
        f'<div style="background:#fff;border:1px solid #e8eaf0;border-radius:12px;padding:20px;">'
        f'<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:14px;">'
        f'<span style="font-family:Inter,sans-serif;font-size:36px;font-weight:700;'
        f'letter-spacing:-0.022em;color:{score_color};">{score_display}</span>'
        f'<span style="font-family:Inter,sans-serif;font-size:13px;color:#6b7084;">/ 5 Northstar</span>'
        f'</div>'
        f'<div style="height:1px;background:#f0f1f5;margin:14px 0;"></div>'
        f'<div style="font-family:Inter,sans-serif;font-size:11px;font-weight:600;'
        f'letter-spacing:0.08em;color:#9aa0b1;text-transform:uppercase;">Slug</div>'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:12px;color:#2b2e3a;'
        f'margin:4px 0 14px;">/{art.get("suggested_slug","")}</div>'
        f'<div style="font-family:Inter,sans-serif;font-size:11px;font-weight:600;'
        f'letter-spacing:0.08em;color:#9aa0b1;text-transform:uppercase;">Template</div>'
        f'<div style="font-family:Inter,sans-serif;font-size:13px;color:#2b2e3a;margin:4px 0 14px;">'
        f'{art.get("layout_type") or art.get("page_classification") or "—"}</div>'
        f'<div style="font-family:Inter,sans-serif;font-size:11px;font-weight:600;'
        f'letter-spacing:0.08em;color:#9aa0b1;text-transform:uppercase;">Status</div>'
        f'<div style="margin:6px 0 14px;">'
        f'{pill(status, {"approved":"success","draft":"warning","rejected":"danger"}.get(status,"neutral"))}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.page_link("pages/7_library.py", label="Open in Library  →")

# ─── Evaluation drawer ──────────────────────────────────────────────────────
st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
section_label("Evaluation · EEAT + SEO/GEO")

import json as _json
import os as _os


def _api_key():
    k = (st.session_state.get("OPENAI_API_KEY_INPUT") or "").strip()
    if k:
        return k
    k = _os.environ.get("OPENAI_API_KEY", "").strip()
    if k:
        return k
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


def _has_env_key() -> bool:
    if _os.environ.get("OPENAI_API_KEY", "").strip():
        return True
    try:
        return bool(str(st.secrets.get("OPENAI_API_KEY", "")).strip())
    except Exception:
        return False


if not _has_env_key():
    with st.expander("🔑 OpenAI API key (required for evaluation + fixes)",
                     expanded=not bool(st.session_state.get("OPENAI_API_KEY_INPUT"))):
        st.text_input(
            "OpenAI API key", type="password", placeholder="sk-...",
            key="OPENAI_API_KEY_INPUT", label_visibility="collapsed",
        )
        st.caption("Stored in this session only — never written to disk.")

_eval_payload = None
_raw_eval = art.get("eval_json")
if _raw_eval:
    try:
        parsed = _json.loads(_raw_eval)
        if isinstance(parsed, dict) and "overall_score" in parsed:
            _eval_payload = parsed
    except Exception:
        _eval_payload = None

if _eval_payload:
    try:
        from evaluation_v2 import render_eval_drawer, apply_fix, run_evaluation

        def _on_fix(issue):
            ak = _api_key()
            if not ak:
                st.error("Set OPENAI_API_KEY to apply fixes.")
                return
            try:
                article = _json.loads(art.get("structured_json") or "{}")
            except Exception:
                article = {}
            updated = apply_fix(ak, article, issue, full_article=article,
                                model=art.get("model_used") or "gpt-4.1")
            # Persist via direct sqlite update (avoid importing generate page)
            conn = sqlite3.connect(str(ARTICLES_DB))
            conn.execute(
                "UPDATE articles SET structured_json = ? WHERE article_id = ?",
                (_json.dumps(updated, ensure_ascii=False), art["article_id"]),
            )
            conn.commit()
            conn.close()
            st.success("Fix applied. Re-run evaluation to see updated score.")
            st.rerun()

        render_eval_drawer(_eval_payload, art["article_id"], on_fix_callback=_on_fix)
    except Exception as _e:
        st.warning("Eval drawer error: {}".format(_e))
else:
    st.caption("No evaluation on file for this article.")
    if st.button("Run evaluation now", key="run_eval_now"):
        try:
            from evaluation_v2 import run_evaluation
            ak = _api_key()
            if not ak:
                st.error("Set OPENAI_API_KEY first.")
            else:
                with st.spinner("Evaluating..."):
                    res = run_evaluation(
                        ak,
                        art.get("structured_json") or "{}",
                        _json.loads(art.get("source_urls_json") or "[]"),
                        art.get("consumer_question") or "",
                        art.get("model_used") or "gpt-4.1",
                    )
                if res and "error" not in res:
                    conn = sqlite3.connect(str(ARTICLES_DB))
                    conn.execute(
                        """UPDATE articles SET eval_json = ?, eval_score = ?,
                           eeat_json = ?, seo_geo_json = ? WHERE article_id = ?""",
                        (
                            _json.dumps(res, ensure_ascii=False),
                            float(res.get("overall_score", 0) or 0),
                            _json.dumps(res.get("eeat", {}), ensure_ascii=False),
                            _json.dumps(res.get("seo_geo", {}), ensure_ascii=False),
                            art["article_id"],
                        ),
                    )
                    conn.commit()
                    conn.close()
                    st.rerun()
                else:
                    st.error(res.get("error", "Evaluation failed."))
        except Exception as _e:
            st.error("Eval failed: {}".format(_e))

# ─── Footer nav ─────────────────────────────────────────────────────────────
st.markdown('<div style="height:36px;"></div>', unsafe_allow_html=True)
c1, c2, _ = st.columns([1, 1, 3])
with c1:
    st.page_link("pages/3_generate.py", label="← Back to Generate")
with c2:
    st.page_link("pages/7_library.py", label="Library →")
