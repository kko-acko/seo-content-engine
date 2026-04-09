"""
Step 4 — Evaluation Tab
========================
Runs a second AI pass on generated articles, scoring them against the
6-dimension Northstar framework. Articles below threshold get flagged.

Dimensions:
1. Consumer question clarity (20%)
2. Content depth & usefulness (20%)
3. Structure & scannability (15%)
4. Brand voice & publishability (15%)
5. Replaceability (15%)
6. Design & visual execution (15%)

Minimum to publish: weighted avg >= 3.5, no dimension below 2.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional

import openai
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DB_PATH = PROJECT_ROOT / "articles.db"
NORTHSTAR_PATH = PROJECT_ROOT / "northstar.md"

DIMENSION_WEIGHTS = {
    "question_clarity": 0.20,
    "content_depth": 0.20,
    "structure": 0.15,
    "brand_voice": 0.15,
    "replaceability": 0.15,
    "design": 0.15,
}


def get_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Evaluation prompt
# ---------------------------------------------------------------------------

EVAL_SYSTEM_PROMPT = """You are a senior content quality auditor for Acko, an Indian digital insurance company.

You evaluate AI-generated insurance articles against a strict 6-dimension quality framework. Be rigorous and honest — your job is to catch problems BEFORE content goes live.

Score each dimension 1-5:
5 = Great (exemplary, publishable as-is)
4 = Good (minor improvements possible)
3 = Good enough (publishable with edits)
2 = Below bar (needs significant revision)
1 = Fails (regenerate from scratch)

━━━ THE 6 DIMENSIONS ━━━

1. CONSUMER QUESTION CLARITY (weight: 20%)
   - Is there ONE clear consumer question this article answers?
   - Is the H1 that question (or very close to it)?
   - Do the first 2 paragraphs answer it directly?
   - Would a reader know within 5 seconds what this page is about?

2. CONTENT DEPTH & USEFULNESS (weight: 20%)
   - Does every section add new information?
   - Are there specific numbers, examples, actionable advice?
   - Does it cover 2-3 adjacent questions beyond the main one?
   - After reading, would someone still need to Google the same question?

3. STRUCTURE & SCANNABILITY (weight: 15%)
   - Are all H2s natural-language questions?
   - Can you understand the key points by reading only H2s and bold text?
   - Are there comparison tables, bullet lists, step sequences where appropriate?
   - No paragraph longer than 3 sentences?

4. BRAND VOICE & PUBLISHABILITY (weight: 15%)
   - Does it sound like a knowledgeable friend, not a textbook or chatbot?
   - Second person throughout? Active voice?
   - Would it need light editing (< 15 min) or heavy rewriting (> 30 min)?
   - Any forbidden phrases? ("In conclusion", "It is important to note", "In today's world", etc.)

5. REPLACEABILITY (weight: 15%)
   - Does this cover everything the source pages covered?
   - Are all internal links from the source pages preserved?
   - Could this credibly replace the old pages via 301 redirect?
   - Would any user be worse off if we redirected?

6. DESIGN & VISUAL EXECUTION (weight: 15%)
   - Does the section structure support visual variety? (not just text blocks)
   - Are there comparison tables, charts, expert callouts, FAQ accordions?
   - Does the layout_type match the content shape?
   - Would this render well in a modern template with proper section alternation?

━━━ OUTPUT FORMAT ━━━

Return ONLY valid JSON:
{
    "scores": {
        "question_clarity": {"score": 1-5, "reasoning": "str"},
        "content_depth": {"score": 1-5, "reasoning": "str"},
        "structure": {"score": 1-5, "reasoning": "str"},
        "brand_voice": {"score": 1-5, "reasoning": "str"},
        "replaceability": {"score": 1-5, "reasoning": "str"},
        "design": {"score": 1-5, "reasoning": "str"}
    },
    "weighted_average": 0.0,
    "verdict": "approve | conditional | reject",
    "top_strengths": ["str", "str"],
    "top_issues": ["str", "str"],
    "suggested_improvements": ["str", "str"]
}

Verdict rules:
- "approve": weighted avg >= 4.0 AND no dimension below 3
- "conditional": weighted avg >= 3.5 AND no dimension below 2
- "reject": weighted avg < 3.5 OR any dimension below 2

No markdown fences. No explanation outside the JSON.
"""


def run_evaluation(api_key: str, article_json: str, source_urls: List[str],
                   consumer_question: str, model: str = "gpt-4o") -> Dict:
    client = openai.OpenAI(api_key=api_key)

    user_prompt = """Evaluate this AI-generated insurance article against the 6-dimension quality framework.

CONSUMER QUESTION THIS ARTICLE SHOULD ANSWER:
{question}

SOURCE PAGES IT WAS BUILT FROM:
{sources}

ARTICLE JSON (the structured content):
{article}

Score all 6 dimensions. Be rigorous. Return ONLY valid JSON.""".format(
        question=consumer_question,
        sources="\n".join("- " + u for u in source_urls),
        article=article_json[:12000],  # Truncate if huge
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse evaluation", "raw": text}


def save_evaluation(article_id: int, eval_result: Dict) -> None:
    weighted_avg = eval_result.get("weighted_average", 0)
    verdict = eval_result.get("verdict", "reject")

    status = "draft"
    if verdict == "approve":
        status = "approved"
    elif verdict == "conditional":
        status = "draft"  # needs review
    else:
        status = "rejected"

    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.execute(
        "UPDATE articles SET eval_score = ?, eval_json = ?, status = ? WHERE article_id = ?",
        (weighted_avg, json.dumps(eval_result, ensure_ascii=False), status, article_id),
    )
    conn.commit()
    conn.close()


def load_articles() -> List[Dict]:
    if not ARTICLES_DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(ARTICLES_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM articles ORDER BY generated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Evaluate — Acko SEO", page_icon="📊", layout="wide")
    st.title("📊 Content Evaluator")
    st.caption(
        "Score generated articles against the Northstar quality framework. "
        "Nothing gets published unless it meets the bar."
    )

    # Sidebar
    deployment_key = get_openai_key()
    with st.sidebar:
        st.markdown("**acko** Content Studio")
        st.page_link("app.py", label="Home", icon="🏠")
        st.page_link("pages/1_crawler.py", label="Crawl", icon="🕷️")
        st.page_link("pages/2_content_architecture.py", label="Architecture", icon="🏗️")
        st.page_link("pages/3_generate.py", label="Generate", icon="✍️")
        st.page_link("pages/4_evaluate.py", label="Evaluate", icon="📊")
        st.divider()

        if deployment_key:
            api_key = deployment_key
            st.success("API key active", icon="🔑")
        else:
            api_key = st.text_input("OpenAI API key", type="password", placeholder="sk-...")

        model = st.selectbox(
            "Evaluation model",
            ["gpt-4o", "gpt-4o-mini"],
            index=0,
        )

        st.divider()

        # Northstar reference
        if NORTHSTAR_PATH.exists():
            with st.expander("📖 Northstar Reference"):
                st.markdown(NORTHSTAR_PATH.read_text(encoding="utf-8")[:3000] + "\n\n...")

    # Load articles
    articles = load_articles()

    if not articles:
        st.info("No articles generated yet. Go to the Generate tab first.")
        return

    # Summary metrics
    evaluated = [a for a in articles if a.get("eval_score")]
    unevaluated = [a for a in articles if not a.get("eval_score")]
    approved = [a for a in articles if a.get("status") == "approved"]
    rejected = [a for a in articles if a.get("status") == "rejected"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total articles", len(articles))
    c2.metric("Evaluated", len(evaluated))
    c3.metric("Approved ✅", len(approved))
    c4.metric("Rejected ❌", len(rejected))

    st.divider()

    tab_eval, tab_results = st.tabs(["🔍 Evaluate", "📋 Results"])

    # ---- TAB: Evaluate ----
    with tab_eval:
        if not unevaluated:
            st.success("All articles have been evaluated!")
            st.markdown("Check the **Results** tab to see scores and verdicts.")
        else:
            st.markdown("### {} articles awaiting evaluation".format(len(unevaluated)))

            for art in unevaluated:
                with st.container(border=True):
                    st.markdown("**{}**".format(art["consumer_question"]))
                    st.caption("Article #{} · Cluster #{} · Generated {}".format(
                        art["article_id"],
                        art.get("cluster_id", "?"),
                        art.get("generated_at", ""),
                    ))

                    source_urls = json.loads(art.get("source_urls_json") or "[]")
                    st.caption("{} source pages · Model: {}".format(len(source_urls), art.get("model_used", "")))

                    if st.button(
                        "🔍 Run Evaluation",
                        key="eval_{}".format(art["article_id"]),
                        type="primary",
                    ):
                        if not api_key:
                            st.error("No API key.")
                        else:
                            with st.spinner("Evaluating article #{}...".format(art["article_id"])):
                                try:
                                    eval_result = run_evaluation(
                                        api_key,
                                        art.get("structured_json") or "{}",
                                        source_urls,
                                        art["consumer_question"],
                                        model,
                                    )
                                except Exception as e:
                                    st.error("Evaluation failed: {}".format(e))
                                    eval_result = None

                            if eval_result and "error" not in eval_result:
                                save_evaluation(art["article_id"], eval_result)
                                st.success("Evaluation complete!")
                                st.rerun()
                            elif eval_result and "error" in eval_result:
                                st.error(eval_result["error"])
                                if "raw" in eval_result:
                                    with st.expander("Raw response"):
                                        st.code(eval_result["raw"])

            # Batch evaluate
            st.markdown("---")
            if st.button(
                "🚀 Evaluate ALL ({} articles)".format(len(unevaluated)),
                use_container_width=True,
            ):
                if not api_key:
                    st.error("No API key.")
                else:
                    progress = st.progress(0.0)
                    status = st.empty()

                    for i, art in enumerate(unevaluated):
                        status.info("Evaluating {}/{}...".format(i + 1, len(unevaluated)))
                        progress.progress((i + 1) / len(unevaluated))

                        source_urls = json.loads(art.get("source_urls_json") or "[]")
                        try:
                            eval_result = run_evaluation(
                                api_key,
                                art.get("structured_json") or "{}",
                                source_urls,
                                art["consumer_question"],
                                model,
                            )
                            if eval_result and "error" not in eval_result:
                                save_evaluation(art["article_id"], eval_result)
                        except Exception as e:
                            status.warning("Failed on article #{}: {}".format(art["article_id"], e))

                    status.success("Batch evaluation complete!")
                    st.rerun()

    # ---- TAB: Results ----
    with tab_results:
        if not evaluated:
            st.info("No evaluations yet. Run evaluations in the Evaluate tab.")
        else:
            # Filter
            filter_status = st.selectbox(
                "Filter by status",
                ["All", "approved", "draft", "rejected"],
                index=0,
            )

            display = evaluated
            if filter_status != "All":
                display = [a for a in evaluated if a.get("status") == filter_status]

            for art in display:
                eval_data = json.loads(art.get("eval_json") or "{}")
                scores = eval_data.get("scores", {})
                weighted_avg = eval_data.get("weighted_average", 0)
                verdict = eval_data.get("verdict", "unknown")

                verdict_icon = {"approve": "✅", "conditional": "🟡", "reject": "❌"}.get(verdict, "❓")
                score_color = "green" if weighted_avg >= 4.0 else "orange" if weighted_avg >= 3.5 else "red"

                with st.expander(
                    "{} **{}** — Score: {:.1f}/5.0 [{}]".format(
                        verdict_icon,
                        art["consumer_question"][:70],
                        weighted_avg,
                        verdict.upper(),
                    )
                ):
                    # Score breakdown
                    st.markdown("#### Dimension Scores")

                    for dim_key, dim_info in scores.items():
                        if not isinstance(dim_info, dict):
                            continue
                        score = dim_info.get("score", 0)
                        reasoning = dim_info.get("reasoning", "")
                        weight = DIMENSION_WEIGHTS.get(dim_key, 0)
                        dim_label = dim_key.replace("_", " ").title()

                        bar_color = "🟢" if score >= 4 else "🟡" if score >= 3 else "🔴"
                        st.markdown(
                            "{} **{}** — {}/5 (weight: {}%)".format(
                                bar_color, dim_label, score, int(weight * 100)
                            )
                        )
                        st.caption(reasoning)

                    st.markdown("---")

                    # Strengths & issues
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**✅ Strengths**")
                        for s in eval_data.get("top_strengths", []):
                            st.markdown("- {}".format(s))
                    with col_b:
                        st.markdown("**⚠️ Issues**")
                        for issue in eval_data.get("top_issues", []):
                            st.markdown("- {}".format(issue))

                    # Improvements
                    improvements = eval_data.get("suggested_improvements", [])
                    if improvements:
                        st.markdown("**💡 Suggested improvements**")
                        for imp in improvements:
                            st.markdown("- {}".format(imp))

                    # Manual override
                    st.markdown("---")
                    st.markdown("**Manual override**")
                    col_1, col_2, col_3 = st.columns(3)
                    with col_1:
                        if st.button("✅ Approve", key="approve_{}".format(art["article_id"])):
                            conn = sqlite3.connect(str(ARTICLES_DB_PATH))
                            conn.execute(
                                "UPDATE articles SET status = 'approved' WHERE article_id = ?",
                                (art["article_id"],),
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()
                    with col_2:
                        if st.button("🔄 Regenerate", key="regen_{}".format(art["article_id"])):
                            conn = sqlite3.connect(str(ARTICLES_DB_PATH))
                            conn.execute(
                                "UPDATE articles SET status = 'draft', eval_score = NULL, eval_json = NULL WHERE article_id = ?",
                                (art["article_id"],),
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()
                    with col_3:
                        if st.button("❌ Reject", key="reject_{}".format(art["article_id"])):
                            conn = sqlite3.connect(str(ARTICLES_DB_PATH))
                            conn.execute(
                                "UPDATE articles SET status = 'rejected' WHERE article_id = ?",
                                (art["article_id"],),
                            )
                            conn.commit()
                            conn.close()
                            st.rerun()


main()
