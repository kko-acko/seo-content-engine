"""
evaluation_v2.py — EEAT + SEO/GEO scorecard with surgical auto-fix.

Three public entry points:
  - run_evaluation(api_key, article_json, source_urls, consumer_question, model) -> dict
  - apply_fix(api_key, article_json, issue, full_article, model) -> dict
  - render_eval_drawer(eval_result, article_id, on_fix_callback) -> None

The eval JSON shape is documented in /Users/kanika.oberoi/.claude/plans/refactored-mapping-flask.md.
EEAT/SEO-GEO dimensions map onto northstar.md's 6-dim rubric (option B from earlier round).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

import openai
import streamlit as st

from ai_helpers import build_messages, build_api_kwargs, extract_json


# ---------------------------------------------------------------------------
# Forbidden phrases — single source of truth in content_rules.py
# ---------------------------------------------------------------------------

try:
    from content_rules import FORBIDDEN_PHRASES  # canonical list
except Exception:
    # Fallback if content_rules is unavailable at import time
    FORBIDDEN_PHRASES = [
        "in conclusion",
        "it is important to note",
        "in today's fast-paced world",
        "needless to say",
        "as an ai language model",
        "let us delve into",
        "let's delve into",
        "in this comprehensive guide",
        "without further ado",
        "navigating the complexities",
    ]


def _detect_forbidden(article_json_str: str) -> List[str]:
    """Return list of forbidden phrases found in the article content (case-insensitive)."""
    text = article_json_str.lower()
    hits = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            hits.append(phrase)
    return hits


# ---------------------------------------------------------------------------
# Evaluation prompt
# ---------------------------------------------------------------------------

EVAL_SYSTEM_PROMPT = """You are a senior content auditor for Acko, an Indian digital insurance company.
You evaluate published articles against two frameworks:

1. EEAT (Google's quality signals) — Experience, Expertise, Authoritativeness, Trust
2. SEO/GEO — search-engine and generative-engine readiness

Your scoring maps directly onto Acko's northstar rubric (6 dimensions reframed under EEAT/SEO-GEO):

EEAT dimensions:
  - experience: first-hand voice, concrete scenarios, "we've seen", real numbers — NOT generic.
    (Maps to northstar Voice + Replaceability.)
  - expertise: technical accuracy, depth on edge cases, accurate insurance-specific claims.
    (Maps to northstar Depth.)
  - authoritativeness: clear sourcing for every claim, citation density, IRDAI/regulator references where relevant.
    (Maps to northstar Replaceability + Depth.)
  - trust: no hallucinated facts, no forbidden phrases, no AI-tells, hedges where appropriate, factually safe for an insurer.
    (Maps to northstar Voice + Question Clarity.)

SEO/GEO dimensions:
  - h1_question: H1 is a clear consumer question, matches search intent, no marketing fluff.
    (Maps to northstar Question Clarity.)
  - structure: scannable hierarchy, H2/H3 labels are specific, sections aren't paragraph-walls.
    (Maps to northstar Structure + Design.)
  - schema_markup: FAQ schema present where FAQs exist, HowTo where steps exist, Article schema fields.
    (Maps to northstar Design.)
  - internal_links: contextual links to related Acko content, not generic "click here" filler.
  - citation_density: claims that need a source actually cite one; numbers are attributed.
    (Maps to northstar Replaceability.)
  - geo_answerable: a generative engine (Perplexity/Gemini) could quote a self-contained paragraph as the answer.

Score every dimension 0–5 (5 = excellent, 3 = passable, 1 = broken).

Return ONLY a JSON object with this exact shape, no markdown fences, no preamble:

{
  "eeat": {
    "experience":      {"score": <0-5>, "reasoning": "<1-2 sentences>", "issues": ["<short issue>", ...]},
    "expertise":       {"score": <0-5>, "reasoning": "...", "issues": [...]},
    "authoritativeness":{"score": <0-5>, "reasoning": "...", "issues": [...]},
    "trust":           {"score": <0-5>, "reasoning": "...", "issues": [...]}
  },
  "seo_geo": {
    "h1_question":      {"score": <0-5>, "reasoning": "...", "issues": [...]},
    "structure":        {"score": <0-5>, "reasoning": "...", "issues": [...]},
    "schema_markup":    {"score": <0-5>, "reasoning": "...", "issues": [...]},
    "internal_links":   {"score": <0-5>, "reasoning": "...", "issues": [...]},
    "citation_density": {"score": <0-5>, "reasoning": "...", "issues": [...]},
    "geo_answerable":   {"score": <0-5>, "reasoning": "...", "issues": [...]}
  },
  "overall_score": <0-5 weighted avg>,
  "verdict": "approve" | "conditional" | "reject",
  "top_issues": [
    {
      "id": "<stable-slug-id>",
      "dimension": "<one of the 10 dimensions above>",
      "severity": "high" | "med" | "low",
      "section_id": "<section_id from article OR 'h1'|'intro'|'faq'|'cta'|'global'>",
      "what": "<1-line problem>",
      "fix_hint": "<specific change to make>"
    }
  ]
}

Rules:
- top_issues should list the 3-7 highest-leverage problems, sorted by severity then impact.
- For each issue, set section_id to the actual section_id in the article JSON when the fix is local;
  use 'global' when the fix is article-wide (h1 phrasing, schema injection, voice across sections).
- verdict = "approve" if overall_score >= 4.0, "conditional" if 3.0–3.99, "reject" if <3.0.
- Be specific. "Add more depth" is useless; "Section 'claim_process' lacks the 30-day IRDAI deadline citation" is useful.
"""


def run_evaluation(api_key: str,
                   article_json: str,
                   source_urls: List[str],
                   consumer_question: str,
                   model: str = "gpt-4.1") -> Dict[str, Any]:
    """Single LLM call returning EEAT + SEO/GEO scorecard.

    Hard regex enforcement of forbidden phrases auto-deducts from trust.score.
    """
    client = openai.OpenAI(api_key=api_key)

    user_prompt = (
        "CONSUMER QUESTION: {q}\n\n"
        "SOURCE URLS ({n}): {urls}\n\n"
        "ARTICLE JSON:\n{a}"
    ).format(
        q=consumer_question,
        n=len(source_urls),
        urls=", ".join(source_urls[:8]) if source_urls else "(none)",
        a=article_json[:18000],
    )

    msgs = build_messages(EVAL_SYSTEM_PROMPT, user_prompt, model)
    kwargs = build_api_kwargs(model, 4096, msgs)

    try:
        response = client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content.strip()
        result = extract_json(text)
        if not isinstance(result, dict):
            return {"error": "eval returned non-dict", "raw": str(result)[:500]}
    except json.JSONDecodeError:
        return {"error": "eval JSON parse failed"}
    except Exception as e:
        return {"error": "eval call failed: {}".format(e)}

    # Hard enforcement: forbidden phrases
    forbidden_hits = _detect_forbidden(article_json)
    if forbidden_hits:
        trust = result.get("eeat", {}).get("trust", {})
        old_score = float(trust.get("score", 3) or 3)
        # Deduct 1 point per unique forbidden phrase, floor at 0
        new_score = max(0, old_score - len(forbidden_hits))
        trust["score"] = new_score
        existing_issues = list(trust.get("issues", []))
        for phrase in forbidden_hits:
            existing_issues.append('Forbidden phrase detected: "{}"'.format(phrase))
        trust["issues"] = existing_issues
        result.setdefault("eeat", {})["trust"] = trust

        # Also push to top_issues
        top = list(result.get("top_issues", []))
        for phrase in forbidden_hits:
            top.append({
                "id": "forbidden_{}".format(re.sub(r"[^a-z0-9]+", "_", phrase)),
                "dimension": "trust",
                "severity": "high",
                "section_id": "global",
                "what": 'Forbidden phrase: "{}"'.format(phrase),
                "fix_hint": 'Remove the phrase "{}" and rewrite in plain editorial voice.'.format(phrase),
            })
        result["top_issues"] = top

        # Recompute overall (light touch — average of all 10 dim scores)
        result["overall_score"] = _compute_overall(result)
        result["verdict"] = _verdict(result["overall_score"])

    return result


def _compute_overall(eval_result: Dict) -> float:
    scores = []
    for group in ("eeat", "seo_geo"):
        for dim, payload in (eval_result.get(group, {}) or {}).items():
            if isinstance(payload, dict):
                try:
                    scores.append(float(payload.get("score", 0) or 0))
                except (TypeError, ValueError):
                    pass
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def _verdict(overall: float) -> str:
    if overall >= 4.0:
        return "approve"
    if overall >= 3.0:
        return "conditional"
    return "reject"


# ---------------------------------------------------------------------------
# Surgical fix
# ---------------------------------------------------------------------------

FIX_SYSTEM_PROMPT = """You are an Acko content editor performing a surgical fix on a generated article.

You will be given:
- The full article JSON (read-only context).
- ONE specific issue to fix (dimension, what, fix_hint, target section_id).

Return ONLY the replacement object as JSON, no markdown fences, no commentary.

If the issue's section_id matches a section in the article's `sections` list,
return the FULL replacement section object with the same shape (section_id, heading, type, content, ...).

If section_id is 'global', 'h1', 'faq', or 'cta', return a partial article patch:
  - 'h1'    -> {"h1": "<new H1>"}
  - 'faq'   -> {"faqs": [<full new FAQ list>]}
  - 'cta'   -> {"cta": {<full new cta object>}}
  - 'global' (any other article-level field) -> {"<field>": <new value>}

Do not add fields the original didn't have. Keep voice, length, and structure of neighbouring sections.
Apply the fix_hint precisely; do not freelance other improvements.
Forbidden phrases (must not appear in output):
  "in conclusion", "it is important to note", "in today's fast-paced world",
  "needless to say", "as an ai language model", "let us delve into",
  "in this comprehensive guide".
"""


def _find_section(article: Dict, section_id: str) -> Optional[Dict]:
    sections = article.get("sections") or article.get("body") or []
    if not isinstance(sections, list):
        return None
    for s in sections:
        if isinstance(s, dict) and s.get("section_id") == section_id:
            return s
    return None


def apply_fix(api_key: str,
              article_json: Dict,
              issue: Dict,
              full_article: Optional[Dict] = None,
              model: str = "gpt-4.1") -> Dict[str, Any]:
    """Regenerate just the section/field targeted by `issue` and return updated article."""
    client = openai.OpenAI(api_key=api_key)
    article = full_article if full_article is not None else article_json
    if not isinstance(article, dict):
        return article  # nothing safe to do

    section_id = (issue or {}).get("section_id", "global")
    target_section = _find_section(article, section_id) if section_id not in {"global", "h1", "faq", "cta"} else None

    user_payload = {
        "issue": issue,
        "target_section_id": section_id,
        "target_section": target_section,
        "article": article,
    }
    user_prompt = "Fix the following issue surgically.\n\n" + json.dumps(user_payload, ensure_ascii=False)[:18000]

    msgs = build_messages(FIX_SYSTEM_PROMPT, user_prompt, model)
    kwargs = build_api_kwargs(model, 4096, msgs)

    try:
        response = client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content.strip()
        patch = extract_json(text)
    except Exception:
        return article  # fail-safe: return original on parse failure

    if not isinstance(patch, dict):
        return article

    # Apply patch
    updated = dict(article)
    if target_section is not None and patch.get("section_id") == section_id:
        # Section replacement
        new_sections = []
        for s in updated.get("sections", []):
            if isinstance(s, dict) and s.get("section_id") == section_id:
                new_sections.append(patch)
            else:
                new_sections.append(s)
        updated["sections"] = new_sections
    else:
        # Field-level patch (h1, faqs, cta, or any global field returned)
        for k, v in patch.items():
            updated[k] = v

    return updated


# ---------------------------------------------------------------------------
# Streamlit drawer
# ---------------------------------------------------------------------------

_DIM_LABELS = {
    "experience": "Experience",
    "expertise": "Expertise",
    "authoritativeness": "Authoritativeness",
    "trust": "Trust",
    "h1_question": "H1 / Question",
    "structure": "Structure",
    "schema_markup": "Schema markup",
    "internal_links": "Internal links",
    "citation_density": "Citation density",
    "geo_answerable": "GEO-answerable",
}


def _bar(score: float) -> str:
    pct = max(0, min(100, int((float(score) / 5.0) * 100)))
    color = "#15a06b" if score >= 4 else ("#d08400" if score >= 3 else "#d54747")
    return (
        '<div style="height:6px;background:#f0f1f5;border-radius:99px;overflow:hidden;margin:4px 0 8px;">'
        '<div style="width:{}%;height:100%;background:{};border-radius:99px;"></div>'
        '</div>'
    ).format(pct, color)


def _render_dim_block(dim_key: str, payload: Dict) -> None:
    if not isinstance(payload, dict):
        return
    label = _DIM_LABELS.get(dim_key, dim_key)
    score = payload.get("score", 0)
    reasoning = payload.get("reasoning", "")
    issues = payload.get("issues", []) or []

    head = (
        '<div style="display:flex;justify-content:space-between;align-items:baseline;">'
        '<div style="font-weight:600;font-size:13.5px;color:#0a0b13;">{lbl}</div>'
        '<div style="font-family:JetBrains Mono,monospace;font-size:12.5px;color:#2b2e3a;">{s}/5</div>'
        '</div>'
    ).format(lbl=label, s=score)
    st.markdown(head + _bar(score), unsafe_allow_html=True)
    if reasoning:
        st.markdown(
            '<div style="font-size:12.5px;color:#505a63;margin-bottom:6px;">{}</div>'.format(reasoning),
            unsafe_allow_html=True,
        )
    if issues:
        for it in issues[:3]:
            st.markdown(
                '<div style="font-size:12px;color:#8d969e;margin-left:6px;">• {}</div>'.format(it),
                unsafe_allow_html=True,
            )


def render_eval_drawer(eval_result: Dict,
                       article_id: Any,
                       on_fix_callback: Optional[Callable[[Dict], None]] = None) -> None:
    """Render the EEAT + SEO/GEO scorecard with per-issue Fix this buttons.

    `on_fix_callback(issue_dict)` is invoked when the user clicks Fix this. Caller
    is responsible for calling apply_fix + persisting the article.
    """
    if not eval_result or "error" in eval_result:
        msg = (eval_result or {}).get("error", "No evaluation available.")
        st.info("Evaluation: {}".format(msg))
        return

    overall = eval_result.get("overall_score", 0)
    verdict = eval_result.get("verdict", "—")
    verdict_color = {"approve": "#15a06b", "conditional": "#d08400", "reject": "#d54747"}.get(verdict, "#8d969e")

    st.markdown(
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'border:1px solid #e8eaf0;border-radius:12px;padding:14px 18px;margin-bottom:14px;">'
        '<div><div style="font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:#8d969e;">'
        'Overall</div><div style="font-family:Space Grotesk,sans-serif;font-size:1.75rem;font-weight:500;'
        'color:#0a0b13;letter-spacing:-0.02em;">{ov}/5</div></div>'
        '<div style="text-align:right;"><div style="font-size:11px;font-weight:600;letter-spacing:1.5px;'
        'text-transform:uppercase;color:#8d969e;">Verdict</div>'
        '<div style="font-family:Space Grotesk,sans-serif;font-size:1.25rem;font-weight:500;color:{vc};">'
        '{vd}</div></div></div>'.format(ov=overall, vc=verdict_color, vd=verdict),
        unsafe_allow_html=True,
    )

    col_e, col_s = st.columns(2, gap="medium")
    with col_e:
        st.markdown(
            '<div style="font-family:Inter,sans-serif;font-size:0.72rem;font-weight:600;'
            'letter-spacing:1.5px;text-transform:uppercase;color:#8d969e;margin-bottom:10px;">EEAT</div>',
            unsafe_allow_html=True,
        )
        for k in ("experience", "expertise", "authoritativeness", "trust"):
            _render_dim_block(k, eval_result.get("eeat", {}).get(k, {}))

    with col_s:
        st.markdown(
            '<div style="font-family:Inter,sans-serif;font-size:0.72rem;font-weight:600;'
            'letter-spacing:1.5px;text-transform:uppercase;color:#8d969e;margin-bottom:10px;">SEO / GEO</div>',
            unsafe_allow_html=True,
        )
        for k in ("h1_question", "structure", "schema_markup", "internal_links", "citation_density", "geo_answerable"):
            _render_dim_block(k, eval_result.get("seo_geo", {}).get(k, {}))

    issues = eval_result.get("top_issues", []) or []
    if issues:
        st.markdown(
            '<div style="font-family:Inter,sans-serif;font-size:0.72rem;font-weight:600;'
            'letter-spacing:1.5px;text-transform:uppercase;color:#8d969e;margin:24px 0 10px;">Top issues</div>',
            unsafe_allow_html=True,
        )
        for idx, issue in enumerate(issues):
            sev = issue.get("severity", "med")
            sev_color = {"high": "#d54747", "med": "#d08400", "low": "#8d969e"}.get(sev, "#8d969e")
            iid = issue.get("id") or "issue_{}".format(idx)

            with st.container():
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(
                        '<div style="border:1px solid #e8eaf0;border-radius:10px;padding:12px 14px;margin-bottom:8px;">'
                        '<div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;">'
                        '<span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;'
                        'color:{sc};">{sv}</span>'
                        '<span style="font-size:11px;color:#8d969e;font-family:JetBrains Mono,monospace;">{dim} · {sec}</span>'
                        '</div>'
                        '<div style="font-size:13px;color:#0a0b13;font-weight:500;">{what}</div>'
                        '<div style="font-size:12px;color:#505a63;margin-top:4px;">→ {fh}</div>'
                        '</div>'.format(
                            sc=sev_color, sv=sev.upper(),
                            dim=issue.get("dimension", "?"),
                            sec=issue.get("section_id", "global"),
                            what=issue.get("what", ""),
                            fh=issue.get("fix_hint", ""),
                        ),
                        unsafe_allow_html=True,
                    )
                with c2:
                    if on_fix_callback is not None:
                        btn_key = "fix_{}_{}".format(article_id, iid)
                        if st.button("Fix this", key=btn_key):
                            on_fix_callback(issue)
