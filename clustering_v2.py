"""
Clustering v2 — discover-then-cluster pipeline.

Three passes:
  Pass A — discover_intent_taxonomy()
      LLM reads compact summaries of every page and proposes a deduplicated
      list of consumer-intent buckets. No fixed count cap; the corpus decides.

  Pass B — assign_pages_to_intents()
      Each page is mapped to exactly one intent from the taxonomy. Because the
      taxonomy is shared across batches, no cross-batch duplication.

  Pass C — consolidate_into_clusters()
      Group assignments by intent → drop empty intents → flag singletons
      (don't merge them into a black-hole "Other"; the editor decides).

Editor checkpoint: between Pass A and Pass B, the UI lets the editor rename,
merge, or kill intents. The (possibly edited) taxonomy is what Pass B uses.

This module is import-only — UI lives in pages/2_clusters.py.
"""
from __future__ import annotations
import json
from typing import Dict, List, Optional, Callable

import openai

from ai_helpers import build_messages, build_api_kwargs, extract_json


# ---------------------------------------------------------------------------
# Pass A — discover intent taxonomy from corpus
# ---------------------------------------------------------------------------

DISCOVERY_SYSTEM_PROMPT = """You are a content strategist analysing a corpus of crawled pages from an Indian car-insurance website.

Your job: read compact summaries of every page and emit a DEDUPLICATED taxonomy of consumer intents present in this corpus.

A consumer intent is the specific user goal behind a search — what the person is trying to do or decide. Examples:
  - "Renew an expired policy"
  - "File a theft claim"
  - "Decide whether to add zero depreciation cover"
  - "Compare comprehensive vs third-party"

━━━ RULES ━━━

1. Emit AS MANY distinct intents as you genuinely observe — no upper or lower cap. The corpus decides.
2. Two intents are distinct only if a real user would phrase them as different goals. Paraphrases of the same goal must be ONE intent.
3. Each intent must be specific enough that a single article could satisfy it. Not "car insurance" (too broad). Not "what is IDV in section 4 sub-clause 2" (too narrow).
4. Do NOT create an "Other" or "Miscellaneous" bucket. Every page must map to a named intent.
5. Phrase each intent as a verb-led user goal, not a topic. "Renew expired policy" not "Policy renewal".

━━━ OUTPUT FORMAT ━━━

Return ONLY valid JSON — an array of intent objects:

[
  {
    "intent_id": "renew_expired_policy",
    "name": "Renew an expired policy",
    "description": "User's policy has lapsed; they need to know how to reinstate cover, what changes (inspection, NCB loss), and the cost impact.",
    "example_questions": [
      "Can I renew my car insurance after expiry?",
      "What happens if my policy lapses for more than 90 days?",
      "Do I lose my NCB if I renew late?"
    ],
    "search_stage": "post_purchase"
  }
]

intent_id: snake_case, stable identifier (used downstream).
search_stage: one of awareness | consideration | decision | post_purchase.

No markdown fences. No explanation. Only the JSON array.
"""


def _summarise_page_for_discovery(p: Dict, body_chars: int = 280) -> str:
    """Compact per-page summary for taxonomy discovery.
    Goal: enough signal to identify intent, small enough that 100s of pages fit in one call.
    """
    parts = []
    parts.append("URL: {}".format(p.get("url", "")))
    title = (p.get("title") or "").strip()
    if title:
        parts.append("Title: {}".format(title))
    h1 = (p.get("h1") or "").strip()
    if h1 and h1 != title:
        parts.append("H1: {}".format(h1))
    meta = (p.get("meta_description") or "").strip()
    if meta:
        parts.append("Meta: {}".format(meta[:160]))
    body = (p.get("body_text") or "").strip()
    if body:
        parts.append("Excerpt: {}".format(body[:body_chars]))
    # Just a couple of H2s for intent signal
    try:
        headings = json.loads(p.get("headings_json") or "[]")
        h2s = [h.get("text", "") for h in headings if isinstance(h, dict) and h.get("tag") == "h2"]
        h2s = [h for h in h2s if h][:4]
        if h2s:
            parts.append("H2s: {}".format(" | ".join(h2s)))
    except (json.JSONDecodeError, TypeError):
        pass
    return "\n".join(parts)


def discover_intent_taxonomy(api_key: str, pages: List[Dict], model: str = "gpt-4.1",
                             status_callback: Optional[Callable[[str], None]] = None) -> List[Dict]:
    """Pass A — read all page summaries, return a deduplicated intent taxonomy.

    For ≤ 200 pages, runs as a single call. For more, chunks with running memory:
    each chunk sees the taxonomy discovered so far and is told to extend it,
    not duplicate it.
    """
    if not pages:
        return []

    client = openai.OpenAI(api_key=api_key)
    CHUNK = 150  # pages per discovery call — keeps prompt comfortably within context

    if status_callback:
        status_callback("Discovering intents from {} pages…".format(len(pages)))

    if len(pages) <= CHUNK:
        return _discovery_call(client, model, pages, existing_taxonomy=None)

    # Multi-chunk discovery with running memory
    taxonomy: List[Dict] = []
    total = (len(pages) + CHUNK - 1) // CHUNK
    for i in range(total):
        start = i * CHUNK
        end = min(start + CHUNK, len(pages))
        if status_callback:
            status_callback("Discovery chunk {}/{} ({} pages)…".format(i + 1, total, end - start))
        new_intents = _discovery_call(client, model, pages[start:end], existing_taxonomy=taxonomy)
        taxonomy = _merge_taxonomies(taxonomy, new_intents)

    return taxonomy


def _discovery_call(client, model: str, pages: List[Dict],
                    existing_taxonomy: Optional[List[Dict]]) -> List[Dict]:
    page_summaries = [_summarise_page_for_discovery(p) for p in pages]

    if existing_taxonomy:
        existing_block = json.dumps(
            [{"intent_id": t["intent_id"], "name": t["name"], "description": t.get("description", "")}
             for t in existing_taxonomy],
            indent=2,
        )
        user_prompt = (
            "Here are {n} more pages from the same corpus.\n\n"
            "An intent taxonomy has already been discovered from earlier pages — DO NOT duplicate these intents. "
            "Only add NEW intents that aren't covered. If every page fits an existing intent, return an empty array [].\n\n"
            "EXISTING TAXONOMY:\n{tax}\n\n"
            "NEW PAGES:\n\n{pages}\n\n"
            "Return ONLY new intents not already in the existing taxonomy."
        ).format(n=len(pages), tax=existing_block, pages="\n\n---\n\n".join(page_summaries))
    else:
        user_prompt = (
            "Here are {n} crawled pages. Read every summary, then emit the deduplicated intent taxonomy "
            "you observe in this corpus.\n\n{pages}"
        ).format(n=len(pages), pages="\n\n---\n\n".join(page_summaries))

    messages = build_messages(DISCOVERY_SYSTEM_PROMPT, user_prompt, model)
    api_kwargs = build_api_kwargs(model, 8192, messages)
    response = client.chat.completions.create(**api_kwargs)
    text = response.choices[0].message.content.strip()

    try:
        result = extract_json(text)
        if isinstance(result, list):
            return [t for t in result if isinstance(t, dict) and t.get("intent_id") and t.get("name")]
    except json.JSONDecodeError:
        pass
    return []


def _merge_taxonomies(existing: List[Dict], new: List[Dict]) -> List[Dict]:
    """Append new intents whose intent_id isn't already present."""
    seen = {t["intent_id"] for t in existing}
    out = list(existing)
    for t in new:
        if t.get("intent_id") and t["intent_id"] not in seen:
            out.append(t)
            seen.add(t["intent_id"])
    return out


# ---------------------------------------------------------------------------
# Pass B — assign each page to one intent from the taxonomy
# ---------------------------------------------------------------------------

ASSIGNMENT_SYSTEM_PROMPT = """You are mapping car-insurance pages to a fixed taxonomy of consumer intents.

You receive:
  - A taxonomy of consumer intents (each with intent_id, name, description, example questions).
  - A list of pages (URL + title + headings + body excerpt).

Your job: assign EVERY page to EXACTLY ONE intent_id from the taxonomy.

━━━ RULES ━━━

1. Use ONLY intent_ids from the provided taxonomy. Do not invent new ones.
2. Every URL in the input must appear in your output exactly once.
3. If a page genuinely fits two intents, pick the dominant one — the one most aligned with what a user would search to land on this page.
4. If a page fits NO intent in the taxonomy, return its intent_id as "__unassigned__" with confidence 0. Do NOT force a bad match.
5. Confidence is 0.0–1.0. Below 0.5 means "I'm guessing" — flag for editor review.

━━━ OUTPUT FORMAT ━━━

Return ONLY valid JSON — an array of assignment objects:

[
  {
    "url": "https://www.acko.com/car-insurance/zero-depreciation/",
    "intent_id": "decide_zero_dep_addon",
    "confidence": 0.92,
    "reason": "Page directly compares zero-dep premium uplift vs claim payout; classic decision-stage content."
  }
]

No markdown fences. No explanation. Only the JSON array.
"""


def _summarise_page_for_assignment(p: Dict, body_chars: int = 350) -> str:
    """Slightly richer summary than discovery — model needs more signal to disambiguate."""
    return _summarise_page_for_discovery(p, body_chars=body_chars)


def assign_pages_to_intents(api_key: str, pages: List[Dict], taxonomy: List[Dict],
                            model: str = "gpt-4.1",
                            status_callback: Optional[Callable[[str], None]] = None) -> List[Dict]:
    """Pass B — assign each page to one intent_id from the taxonomy.

    Batches at 50 pages per call (taxonomy is repeated each call). Returns a
    flat list of assignment dicts. Pages that come back unassigned are retried
    once before being marked __unassigned__.
    """
    if not pages or not taxonomy:
        return []

    client = openai.OpenAI(api_key=api_key)
    BATCH = 50
    taxonomy_block = json.dumps(
        [{"intent_id": t["intent_id"], "name": t["name"],
          "description": t.get("description", ""),
          "example_questions": t.get("example_questions", [])[:3]}
         for t in taxonomy],
        indent=2,
    )

    all_assignments: List[Dict] = []
    total = (len(pages) + BATCH - 1) // BATCH

    for i in range(total):
        start = i * BATCH
        end = min(start + BATCH, len(pages))
        batch = pages[start:end]
        if status_callback:
            status_callback("Assigning batch {}/{} ({} pages)…".format(i + 1, total, len(batch)))
        all_assignments.extend(_assignment_call(client, model, batch, taxonomy_block))

    # Coverage check — every input URL must have exactly one assignment
    assigned_urls = {a["url"] for a in all_assignments if a.get("url")}
    input_urls = {p.get("url", "") for p in pages}
    missing = input_urls - assigned_urls
    if missing:
        if status_callback:
            status_callback("Retrying {} pages that came back unassigned…".format(len(missing)))
        retry_pages = [p for p in pages if p.get("url") in missing]
        retry_assignments = _assignment_call(client, model, retry_pages, taxonomy_block)
        all_assignments.extend(retry_assignments)
        # Anything still missing → mark __unassigned__
        still_missing = missing - {a["url"] for a in retry_assignments if a.get("url")}
        for url in still_missing:
            all_assignments.append({"url": url, "intent_id": "__unassigned__",
                                    "confidence": 0.0, "reason": "No assignment after retry"})

    return all_assignments


def _assignment_call(client, model: str, pages: List[Dict], taxonomy_block: str) -> List[Dict]:
    page_summaries = [_summarise_page_for_assignment(p) for p in pages]
    user_prompt = (
        "TAXONOMY:\n{tax}\n\n"
        "PAGES TO ASSIGN ({n}):\n\n{pages}\n\n"
        "Assign every URL above to exactly one intent_id from the taxonomy."
    ).format(tax=taxonomy_block, n=len(pages), pages="\n\n---\n\n".join(page_summaries))

    messages = build_messages(ASSIGNMENT_SYSTEM_PROMPT, user_prompt, model)
    api_kwargs = build_api_kwargs(model, 8192, messages)
    response = client.chat.completions.create(**api_kwargs)
    text = response.choices[0].message.content.strip()

    try:
        result = extract_json(text)
        if isinstance(result, list):
            return [a for a in result if isinstance(a, dict) and a.get("url") and a.get("intent_id")]
    except json.JSONDecodeError:
        pass
    return []


# ---------------------------------------------------------------------------
# Pass C — consolidate assignments into cluster rows ready for save_clusters()
# ---------------------------------------------------------------------------

def consolidate_into_clusters(taxonomy: List[Dict], assignments: List[Dict],
                              pages: List[Dict]) -> List[Dict]:
    """Pass C — group assignments by intent_id → produce cluster dicts.

    Output schema matches what save_clusters() in pages/2_clusters.py expects:
      consumer_question, theme, page_group, urls, audience_persona,
      search_trigger, secondary_questions
    Plus extras: intent_id, is_outlier (singleton flag), avg_confidence.

    Singletons are NOT dumped into "Other" — they're returned as their own
    cluster with is_outlier=True so the editor can decide.
    Pages assigned __unassigned__ become one cluster with intent_id=__unassigned__.
    """
    by_intent: Dict[str, List[Dict]] = {}
    for a in assignments:
        by_intent.setdefault(a["intent_id"], []).append(a)

    tax_by_id = {t["intent_id"]: t for t in taxonomy}
    clusters: List[Dict] = []

    for intent_id, assigns in by_intent.items():
        urls = [a["url"] for a in assigns]
        avg_conf = round(sum(a.get("confidence", 0) for a in assigns) / max(len(assigns), 1), 2)

        if intent_id == "__unassigned__":
            clusters.append({
                "consumer_question": "Pages that did not match any discovered intent",
                "theme": "unassigned",
                "page_group": "informational",
                "urls": urls,
                "audience_persona": "",
                "search_trigger": "",
                "secondary_questions": [],
                "intent_id": intent_id,
                "is_outlier": True,
                "avg_confidence": avg_conf,
            })
            continue

        intent = tax_by_id.get(intent_id, {})
        examples = intent.get("example_questions", [])
        primary_q = examples[0] if examples else intent.get("name", intent_id)

        clusters.append({
            "consumer_question": primary_q,
            "theme": intent.get("name", intent_id),
            "page_group": "transactional" if intent.get("search_stage") == "decision" else "informational",
            "urls": urls,
            "audience_persona": intent.get("description", ""),
            "search_trigger": intent.get("name", ""),
            "secondary_questions": examples[1:4] if len(examples) > 1 else [],
            "intent_id": intent_id,
            "is_outlier": len(urls) == 1,
            "avg_confidence": avg_conf,
        })

    # Sort: real clusters by size desc, outliers last, unassigned at the very end
    clusters.sort(key=lambda c: (
        c.get("intent_id") == "__unassigned__",
        c.get("is_outlier", False),
        -len(c.get("urls", [])),
    ))
    return clusters
