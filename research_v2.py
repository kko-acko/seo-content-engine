"""
research_v2.py — pre-generation research pass.

Runs once per article, before generation. The LLM acts as a senior editor
scoping the article: it reads the consumer question + sources, picks an intent
shape, and designs the IA this specific article needs.

Without this step the model only knows what crawled sources told it. With it,
the model gets a coverage checklist and adjacent-question list that match the
Plum-grade depth target.

Public API:
    research_for_article(api_key, consumer_question, sources, model="gpt-4.1") -> dict

Returned dict shape:
    {
      "intent_shape":        "definitional" | "comparison" | "how_to" |
                             "troubleshooting" | "decision_guide",
      "coverage_checklist":  [str, ...],   # questions the article must answer
      "adjacent_questions":  [str, ...],   # next-questions the reader will have
      "regulatory_anchors":  [str, ...],   # IRDAI rules / clauses / deadlines
      "suggested_length":    {"min": int, "max": int, "rationale": str},
      "north_star_IA":       [
          {"reader_question": str,
           "suggested_section_type": str,
           "why_this_beat_exists": str},
          ...
      ],
    }
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import openai

from ai_helpers import build_messages, build_api_kwargs, extract_json
from content_rules import INTENT_SCAFFOLDS


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_VALID_SHAPES = list(INTENT_SCAFFOLDS.keys())


def _scaffold_summary() -> str:
    """One-line summary of each intent shape's north-star IA, for the prompt."""
    lines = []
    for name, scaf in INTENT_SCAFFOLDS.items():
        beats = "; ".join(b["reader_question"] for b in scaf["north_star_IA"])
        lines.append("- **{}** — {}\n    Default beats: {}".format(
            name, scaf["when_to_use"], beats,
        ))
    return "\n".join(lines)


RESEARCH_SYSTEM_PROMPT = """You are a senior content editor at Acko (Indian digital insurance) scoping an article before it is written.

Your job is NOT to write the article. Your job is to design what the article should cover, in what order, and against what regulatory anchors — so the writer can produce a Plum-grade piece (https://www.plumhq.com/blog) that leaves no related question unanswered.

You will be given:
- The consumer question (the H1).
- Source material — either crawled pages (Crawl path) or the user's brief (Brief path). Sources may be thin or partial; supplement with what you know about Indian insurance and IRDAI regulations.

You will output a JSON object only — no prose, no markdown fences.

## Intent shapes

Pick the ONE that best fits the consumer question:

{scaffold_summary}

## Output JSON shape

{{
  "intent_shape": "<one of: {valid_shapes}>",
  "coverage_checklist": [
    "<question the article MUST answer>",
    ...
  ],
  "adjacent_questions": [
    "<next-question a reader on this topic will also have, even though they did not ask it>",
    ...
  ],
  "regulatory_anchors": [
    "<specific IRDAI rule, deadline, clause, or industry data point the article should cite by name>",
    ...
  ],
  "suggested_length": {{
    "min": <int word count>,
    "max": <int word count>,
    "rationale": "<one sentence: why this range serves the topic without repetition>"
  }},
  "north_star_IA": [
    {{
      "reader_question": "<the question this beat answers>",
      "suggested_section_type": "<content_block | bullet_list | comparison_table | callout | steps | faq | expert_tip | cta>",
      "why_this_beat_exists": "<one sentence: what this beat earns the reader>"
    }},
    ...
  ]
}}

## Rules for your output

1. **Coverage breadth is your job.** A Plum article never leaves the reader thinking "but what about…". Pad coverage_checklist with the questions the source pages don't cover but a real reader on this topic absolutely will ask.

2. **Adjacent questions matter as much as the asked question.** If the reader is asking "does car insurance cover theft", they will also wonder "how do I file a theft claim", "what's the difference between theft and burglary cover", "does the IDV affect my theft payout". Surface those.

3. **Regulatory anchors must be specific.** Not "IRDAI has rules about claims" — but "IRDAI's 30-day claim settlement deadline (Protection of Policyholders' Interests Regulations, 2017)". If you don't know the specific clause, omit it rather than guess.

4. **Length is content-driven.** Short topics get short articles. Don't pad. The rationale must explain the *content* reason, not a fixed page-classification target.

5. **The north-star IA is your design.** Start from the intent_shape's default beats, then *adapt to this specific article*. Drop beats that don't earn their place. Add beats the topic specifically needs. Reorder if the reader's journey demands it. Each beat must answer one reader-question with the right section type for that moment — never a section type because it was next on a list.

6. **Stage-setter beat is mandatory** as one of the first two beats: a content_block answering "who is this for and why does this matter now". Without it, the article reads as assembled instead of composed.

7. **FAQ beats only earn their place if 4+ residual questions remain after the body has done its work.** Otherwise fold the residuals into the closing.

8. **No callout adjacency.** If your IA has two callouts, separate them with a substantive content beat.

Return ONLY the JSON. No preamble, no markdown fences, no commentary.
""".format(
    scaffold_summary=_scaffold_summary(),
    valid_shapes=" | ".join(_VALID_SHAPES),
)


# ---------------------------------------------------------------------------
# Source serialisation
# ---------------------------------------------------------------------------

def _serialise_sources(sources: Any, max_chars: int = 12000) -> str:
    """Sources may arrive in several shapes:
       - list[dict] of crawled pages (Crawl path) with keys like h1/title/body_text/url
       - str — a brief from the user (Brief path)
       - list[str] — reference URLs or excerpts
       - None — research must lean on its own knowledge
    """
    if sources is None:
        return "(no sources provided — rely on your knowledge of Indian insurance and IRDAI regulations)"

    if isinstance(sources, str):
        return sources[:max_chars]

    if isinstance(sources, list):
        parts: List[str] = []
        running = 0
        for i, item in enumerate(sources):
            if isinstance(item, dict):
                title = item.get("h1") or item.get("title") or item.get("url") or "Source {}".format(i + 1)
                url = item.get("url", "")
                body = item.get("body_text") or item.get("content") or item.get("summary") or ""
                chunk = "### {}\n{}\n{}".format(title, url, body[:1500])
            elif isinstance(item, str):
                chunk = item
            else:
                chunk = str(item)
            running += len(chunk)
            if running > max_chars:
                parts.append("\n(... {} more sources truncated)".format(len(sources) - i))
                break
            parts.append(chunk)
        return "\n\n".join(parts)

    return str(sources)[:max_chars]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def research_for_article(api_key: str,
                         consumer_question: str,
                         sources: Any = None,
                         model: str = "gpt-4.1") -> Dict[str, Any]:
    """Run the editor scoping pass. Returns a dict (see module docstring).

    On any failure, returns a dict with an "error" key — caller should fall
    back to a minimal default (intent_shape="definitional", empty checklist).
    """
    client = openai.OpenAI(api_key=api_key)

    user_prompt = (
        "CONSUMER QUESTION (H1):\n{q}\n\n"
        "SOURCES:\n{src}\n\n"
        "Design the article. Return JSON only."
    ).format(
        q=consumer_question,
        src=_serialise_sources(sources),
    )

    msgs = build_messages(RESEARCH_SYSTEM_PROMPT, user_prompt, model)
    kwargs = build_api_kwargs(model, 3000, msgs)

    try:
        response = client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content.strip()
        result = extract_json(text)
    except json.JSONDecodeError:
        return {"error": "research JSON parse failed"}
    except Exception as e:
        return {"error": "research call failed: {}".format(e)}

    if not isinstance(result, dict):
        return {"error": "research returned non-dict"}

    # Light validation + defaults
    shape = result.get("intent_shape")
    if shape not in _VALID_SHAPES:
        # Coerce to closest sensible default
        result["intent_shape"] = "definitional"
    result.setdefault("coverage_checklist", [])
    result.setdefault("adjacent_questions", [])
    result.setdefault("regulatory_anchors", [])
    result.setdefault("suggested_length", {"min": 1200, "max": 1800,
                                           "rationale": "default range; no per-topic rationale supplied"})
    if not result.get("north_star_IA"):
        # Fall back to the scaffold default if the model returned nothing
        scaffold = INTENT_SCAFFOLDS.get(result["intent_shape"])
        result["north_star_IA"] = list(scaffold["north_star_IA"]) if scaffold else []

    return result


# ---------------------------------------------------------------------------
# Helpers for the generation prompt
# ---------------------------------------------------------------------------

def render_research_brief(research: Dict[str, Any]) -> str:
    """Convert a research dict into the per-article brief block that gets
    appended to the static canon when building the generation system prompt."""
    if not research or "error" in research:
        return "## Per-article brief\n\n(research pass unavailable — write to the canon defaults)"

    cov = research.get("coverage_checklist", []) or []
    adj = research.get("adjacent_questions", []) or []
    reg = research.get("regulatory_anchors", []) or []
    length = research.get("suggested_length", {}) or {}
    ia = research.get("north_star_IA", []) or []

    lines = ["## Per-article brief\n"]
    lines.append("**Intent shape:** {}".format(research.get("intent_shape", "definitional")))
    lines.append("**Suggested length:** {}–{} words — {}".format(
        length.get("min", "?"), length.get("max", "?"), length.get("rationale", "")))

    if cov:
        lines.append("\n**This article must answer:**")
        for q in cov:
            lines.append("  - {}".format(q))

    if adj:
        lines.append("\n**Anticipate these adjacent questions** (surface them in the article — don't make the reader ask):")
        for q in adj:
            lines.append("  - {}".format(q))

    if reg:
        lines.append("\n**Anchor against these regulations / data points** (cite by name when relevant):")
        for r in reg:
            lines.append("  - {}".format(r))

    if ia:
        lines.append("\n**North-star IA — beats in order:**")
        for i, beat in enumerate(ia, 1):
            lines.append("  {}. {} → *{}* — {}".format(
                i,
                beat.get("reader_question", "?"),
                beat.get("suggested_section_type", "content_block"),
                beat.get("why_this_beat_exists", ""),
            ))
        lines.append("\n_The IA above is your design starting point. Drop a beat if it doesn't earn its place; add one if the topic demands it. Each section must answer its reader-question and bridge to the next._")

    return "\n".join(lines)


__all__ = ["research_for_article", "render_research_brief"]
