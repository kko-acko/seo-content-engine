"""
content_rules.py — registries + post-gen hard checks for the Acko content canon.

Companion to `content_rules.md` (the prose canon). Every caller — generation,
editor pass, evaluation, surgical fix — imports from here so the rules don't drift.

Public API:
    FORBIDDEN_PHRASES       # canonical 10-item list of banned phrases
    INTENT_SCAFFOLDS        # 5 intent archetypes -> north-star IAs
    HARD_CHECKS             # list of (name, fn) post-gen structural checks
    load_rules() -> str     # full prompt-ready canon (md prose + serialised registries)
    run_hard_checks(article_json) -> list[dict]   # returns issue-shaped dicts
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
_RULES_MD = _HERE / "content_rules.md"


# ---------------------------------------------------------------------------
# Canonical forbidden-phrase list
# ---------------------------------------------------------------------------
# Tight 10-item list. Intent: ban AI-tells and filler-meta. Each phrase below
# is a direct symptom the article was written *at* the reader instead of *for*
# them. If you want to add a phrase, ask: would removing this phrase ever
# damage a useful sentence? If yes, leave it out.

FORBIDDEN_PHRASES: List[str] = [
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

# Banned punctuation (separate from phrases — em dashes and en dashes are
# overused by LLMs as a stylistic tic; we replace with commas, colons, or full
# stops depending on the sentence). Hyphens (-) are fine.
FORBIDDEN_CHARS: List[str] = [
    "\u2014",   # em dash —
    "\u2013",   # en dash –
]

# Box-like section types — any of these count toward the callout/box budget.
# Used by adjacent-callout + box-overuse hard checks.
BOX_SECTION_TYPES = {
    "callout", "callout_info", "callout_tip", "callout_warning",
    "key_takeaway", "key_takeaways",
    "irdai_update", "irdai_note",
    "expert_tip",
    "info_box", "warning_box", "tip_box", "note_box",
    "highlight", "highlight_box",
}

# H2 length cap — TOC entries must be scannable.
MAX_H2_WORDS = 10


# ---------------------------------------------------------------------------
# Intent scaffolds — north-star IAs, not templates
# ---------------------------------------------------------------------------
# Each beat is { reader_question, suggested_section_type, why_this_beat_exists }.
# The research pass (`research_v2.research_for_article`) starts here, then drops
# or adds beats based on what the article actually needs. Beats are aspirations,
# not requirements.

INTENT_SCAFFOLDS: Dict[str, Dict[str, Any]] = {
    "definitional": {
        "when_to_use": "Reader is asking 'what is X?' — early-funnel, low prior knowledge.",
        "north_star_IA": [
            {"reader_question": "What is X, in one sentence?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "60-second answer for the skimmer."},
            {"reader_question": "Who is this for and why does it matter now?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Stage-setter — the missing tonal anchor."},
            {"reader_question": "How does it work, concretely?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "The understand-phase explanation with a worked example."},
            {"reader_question": "What does it look like with real numbers?",
             "suggested_section_type": "comparison_table",
             "why_this_beat_exists": "Concrete anchoring — readers retain examples, not definitions."},
            {"reader_question": "What's the one thing people get wrong about it?",
             "suggested_section_type": "callout",
             "why_this_beat_exists": "Insider value — the reason the reader will share this article."},
            {"reader_question": "What should I do next?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Decide-phase: actionable closer."},
            {"reader_question": "What else am I likely wondering?",
             "suggested_section_type": "faq",
             "why_this_beat_exists": "Only if 4+ residual questions remain after the body."},
        ],
    },
    "comparison": {
        "when_to_use": "Reader is choosing between 2+ options ('X vs Y', 'best Z').",
        "north_star_IA": [
            {"reader_question": "Which one should I pick, in one sentence?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Lede with the recommendation a hurried reader needs."},
            {"reader_question": "Who is each option built for?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Stage-setter — frames the trade-off, not just the features."},
            {"reader_question": "What is each one, defined?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Concise definitions with concrete examples per option."},
            {"reader_question": "How do they compare across the dimensions that matter?",
             "suggested_section_type": "comparison_table",
             "why_this_beat_exists": "The page's centre of gravity. Earn the table."},
            {"reader_question": "When does each one win?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Decision logic — 'pick X if Y' rules."},
            {"reader_question": "What's the cost difference, with real numbers?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Money is the deciding factor for most readers."},
            {"reader_question": "What's the catch most people miss?",
             "suggested_section_type": "callout",
             "why_this_beat_exists": "The non-obvious trade-off — usually a tax, claim-process, or coverage edge case."},
            {"reader_question": "What else am I likely wondering?",
             "suggested_section_type": "faq",
             "why_this_beat_exists": "Only if 4+ residual questions remain."},
        ],
    },
    "how_to": {
        "when_to_use": "Reader has a specific task to execute (file a claim, port a policy, add a nominee).",
        "north_star_IA": [
            {"reader_question": "What's the goal, and how long will this take?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "60-second answer + time expectation."},
            {"reader_question": "What do I need before I start?",
             "suggested_section_type": "bullet_list",
             "why_this_beat_exists": "Pre-flight checklist — documents, accounts, etc."},
            {"reader_question": "What are the steps?",
             "suggested_section_type": "steps",
             "why_this_beat_exists": "Numbered, executable. The page's reason for existing."},
            {"reader_question": "What goes wrong, and how do I fix it?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Common failure modes with the fix inline."},
            {"reader_question": "What's the regulatory deadline I should know?",
             "suggested_section_type": "callout",
             "why_this_beat_exists": "Time-sensitive IRDAI rules a reader will damage themselves by missing."},
            {"reader_question": "What else might trip me up?",
             "suggested_section_type": "faq",
             "why_this_beat_exists": "Only if 4+ residual questions remain."},
        ],
    },
    "troubleshooting": {
        "when_to_use": "Reader has a problem and wants the cause + fix ('claim rejected', 'policy not active').",
        "north_star_IA": [
            {"reader_question": "What's likely going on?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Lead with the most common cause; reassure that this is fixable."},
            {"reader_question": "Why does this happen?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Mechanism — the reader needs to understand to trust the fix."},
            {"reader_question": "What are the possible causes, in order of likelihood?",
             "suggested_section_type": "bullet_list",
             "why_this_beat_exists": "Differential diagnosis — most-likely first."},
            {"reader_question": "How do I fix each one?",
             "suggested_section_type": "steps",
             "why_this_beat_exists": "Per-cause remediation; concrete, executable."},
            {"reader_question": "When should I escalate to Acko / IRDAI?",
             "suggested_section_type": "callout",
             "why_this_beat_exists": "The reader's safety valve when self-help fails."},
            {"reader_question": "How do I prevent it next time?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Closes the loop; turns a one-time fix into prevention."},
        ],
    },
    "decision_guide": {
        "when_to_use": "Reader is deciding *whether* to do something ('should I buy add-on X?', 'is Y worth it?').",
        "north_star_IA": [
            {"reader_question": "Should I do this — short answer?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Lede with the recommendation, hedged appropriately."},
            {"reader_question": "Who should and who shouldn't?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Stage-setter — segments the audience."},
            {"reader_question": "What does this cost — and what does it actually cover?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Real numbers, real coverage limits."},
            {"reader_question": "What's the expected value — when does it pay off?",
             "suggested_section_type": "comparison_table",
             "why_this_beat_exists": "The maths the reader is doing in their head, made explicit."},
            {"reader_question": "What are the alternatives?",
             "suggested_section_type": "content_block",
             "why_this_beat_exists": "Honest framing — not every reader's answer is yes."},
            {"reader_question": "What's the catch most people don't see?",
             "suggested_section_type": "callout",
             "why_this_beat_exists": "Insider value — the exclusion or fine-print that flips the decision."},
            {"reader_question": "What else am I likely wondering?",
             "suggested_section_type": "faq",
             "why_this_beat_exists": "Only if 4+ residual questions remain."},
        ],
    },
}


# ---------------------------------------------------------------------------
# Hard checks — structural integrity, run on every article post-generation
# ---------------------------------------------------------------------------
# Each check returns a list of issue dicts in the same shape evaluation_v2's
# top_issues uses, so the eval drawer renders them with no UI changes:
#   { id, dimension, severity, section_id, what, fix_hint }

_WEAK_H2_OPENERS = re.compile(
    r"^(now\b|another\b|here(?:'s|\s+is)\b|let'?s\b|moving on\b|next\b)",
    re.IGNORECASE,
)


def _walk_text(node: Any) -> str:
    """Flatten any article sub-tree to plain text for regex checks."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return " ".join(_walk_text(v) for v in node.values())
    if isinstance(node, (list, tuple)):
        return " ".join(_walk_text(v) for v in node)
    return str(node)


def _check_forbidden_phrases(article: Dict) -> List[Dict]:
    text = _walk_text(article).lower()
    issues = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            issues.append({
                "id": "forbidden_" + re.sub(r"[^a-z0-9]+", "_", phrase),
                "dimension": "trust",
                "severity": "high",
                "section_id": "global",
                "what": 'Forbidden phrase: "{}"'.format(phrase),
                "fix_hint": 'Remove "{}" and rewrite the sentence in plain editorial voice.'.format(phrase),
            })
    return issues


def _is_box_section(s: Dict) -> bool:
    stype = (s.get("type") or s.get("section_type") or "").lower()
    return stype in BOX_SECTION_TYPES or stype.startswith("callout")


def _check_adjacent_callouts(article: Dict) -> List[Dict]:
    """Two box-like sections cannot sit next to each other. Boxes are
    punctuation; adjacency dilutes both and reads as 'random box dump'."""
    sections = article.get("sections") or article.get("body") or []
    if not isinstance(sections, list):
        return []
    issues = []
    prev_was_box = False
    prev_id = None
    for s in sections:
        if not isinstance(s, dict):
            prev_was_box = False
            continue
        is_box = _is_box_section(s)
        if is_box and prev_was_box:
            issues.append({
                "id": "adjacent_callouts_" + str(s.get("section_id", "?")),
                "dimension": "structure",
                "severity": "high",
                "section_id": s.get("section_id", "global"),
                "what": "Two box-style sections back-to-back ({} after {}). Boxes are punctuation, not paragraphs.".format(
                    s.get("section_id", "?"), prev_id),
                "fix_hint": "Merge into one box, drop one, or insert a substantive content_block between them.",
            })
        prev_was_box = is_box
        prev_id = s.get("section_id")
    return issues


def _check_box_overuse(article: Dict) -> List[Dict]:
    """Cap box density: max 1 box per ~400 words, never more than 3 per article.
    Random box additions are the #1 visual-noise complaint."""
    sections = article.get("sections") or article.get("body") or []
    if not isinstance(sections, list):
        return []
    box_sections = [s for s in sections if isinstance(s, dict) and _is_box_section(s)]
    box_count = len(box_sections)
    if box_count == 0:
        return []
    word_count = len(_walk_text(article).split())
    budget = max(1, word_count // 400)
    issues: List[Dict] = []
    if box_count > 3:
        issues.append({
            "id": "box_overuse_count",
            "dimension": "structure",
            "severity": "high",
            "section_id": "global",
            "what": "{} box-style sections in one article. Max 3.".format(box_count),
            "fix_hint": "Drop the boxes whose content is not 'reader will damage themselves by missing this'. Fold the rest inline.",
        })
    elif box_count > budget:
        issues.append({
            "id": "box_overuse_density",
            "dimension": "structure",
            "severity": "med",
            "section_id": "global",
            "what": "{} boxes in {} words (budget: {}). Boxes should be sparse.".format(
                box_count, word_count, budget),
            "fix_hint": "Keep only the boxes that punctuate a fact the reader will damage themselves by missing. Fold the rest into prose.",
        })
    return issues


def _check_em_dashes(article: Dict) -> List[Dict]:
    """Em dashes (—) and en dashes (–) are an LLM tic. Replace with commas,
    colons, or full stops. Hyphens (-) are fine."""
    text = _walk_text(article)
    hits = sum(text.count(c) for c in FORBIDDEN_CHARS)
    if hits == 0:
        return []
    return [{
        "id": "em_dashes_present",
        "dimension": "voice",
        "severity": "med",
        "section_id": "global",
        "what": "Article contains {} em/en dash character(s). Banned — replace with commas, colons, or full stops.".replace(
            "—", ",").format(hits),
        "fix_hint": "Replace every — and – with a comma, colon, or full stop. Hyphens (-) are fine.",
    }]


def _check_h2_word_count(article: Dict) -> List[Dict]:
    """TOC entries must be scannable: H2 ≤ 10 words."""
    sections = article.get("sections") or article.get("body") or []
    if not isinstance(sections, list):
        return []
    issues = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if not heading:
            continue
        wc = len(heading.split())
        if wc > MAX_H2_WORDS:
            issues.append({
                "id": "h2_too_long_" + str(s.get("section_id", "?")),
                "dimension": "structure",
                "severity": "med",
                "section_id": s.get("section_id", "global"),
                "what": 'H2 "{}" is {} words. Cap is {} for TOC scannability.'.format(
                    heading, wc, MAX_H2_WORDS),
                "fix_hint": "Tighten the heading to {} words or fewer; keep it self-explanatory in the TOC.".format(
                    MAX_H2_WORDS),
            })
    return issues


def _check_h2_self_explanatory(article: Dict) -> List[Dict]:
    sections = article.get("sections") or article.get("body") or []
    if not isinstance(sections, list):
        return []
    issues = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if not heading:
            continue
        if _WEAK_H2_OPENERS.match(heading) or len(heading.split()) < 3:
            issues.append({
                "id": "weak_h2_" + str(s.get("section_id", "?")),
                "dimension": "structure",
                "severity": "med",
                "section_id": s.get("section_id", "global"),
                "what": 'H2 "{}" does not work as a standalone TOC entry.'.format(heading),
                "fix_hint": "Rewrite the heading as a self-explanatory phrase or question; no 'Now…', 'Another…', 'Let's…' openers.",
            })
    return issues


def _check_h1_is_question(article: Dict) -> List[Dict]:
    h1 = (article.get("h1") or article.get("title") or "").strip()
    if not h1:
        return [{
            "id": "h1_missing",
            "dimension": "h1_question",
            "severity": "high",
            "section_id": "h1",
            "what": "Article has no H1.",
            "fix_hint": "Set the H1 to the consumer question, near-verbatim.",
        }]
    # Soft signal: H1 should look question-like or include a marker
    looks_like_question = "?" in h1 or re.match(
        r"^(what|how|why|when|where|which|should|can|do|does|is|are)\b", h1.lower()
    )
    if not looks_like_question:
        return [{
            "id": "h1_not_question",
            "dimension": "h1_question",
            "severity": "med",
            "section_id": "h1",
            "what": 'H1 "{}" is not phrased as the consumer\'s question.'.format(h1),
            "fix_hint": "Rewrite the H1 as the consumer's question, near-verbatim (e.g. 'Does car insurance cover theft?').",
        }]
    return []


def _check_irdai_footer(article: Dict) -> List[Dict]:
    text = _walk_text(article).lower()
    if "irdai" not in text:
        return [{
            "id": "irdai_footer_missing",
            "dimension": "trust",
            "severity": "med",
            "section_id": "global",
            "what": "Article does not mention IRDAI registration or regulatory anchor.",
            "fix_hint": "Add the IRDAI registration footer and cite IRDAI by name on any regulatory claim.",
        }]
    return []


def _check_stage_setter(article: Dict) -> List[Dict]:
    """Stage-setter = a content_block paragraph between the lede and the first H2.
    We check: after the intro/lede block, is there at least one paragraph-style
    block before the first heading-bearing section?"""
    sections = article.get("sections") or article.get("body") or []
    if not isinstance(sections, list) or len(sections) < 2:
        return []
    # Heuristic: walk first 3 sections; if first heading appears before any
    # second content_block, the stage-setter is missing.
    content_blocks_before_first_heading = 0
    for s in sections[:4]:
        if not isinstance(s, dict):
            continue
        stype = (s.get("type") or s.get("section_type") or "").lower()
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if heading and content_blocks_before_first_heading < 2:
            return [{
                "id": "stage_setter_missing",
                "dimension": "structure",
                "severity": "med",
                "section_id": "intro",
                "what": "No stage-setter paragraph between the lede and the first H2.",
                "fix_hint": "Add an 80–150 word paragraph after the lede framing who this is for, what's at stake, and why it matters now — before the first H2.",
            }]
        if stype == "content_block" or stype == "":
            content_blocks_before_first_heading += 1
    return []


# ---------------------------------------------------------------------------
# Programmatic normaliser — deterministic post-processing
# ---------------------------------------------------------------------------
# We don't trust the LLM to obey "no adjacent boxes / max 3 boxes / no IRDAI
# registration as a section" rules — it keeps drifting. So we enforce them
# by editing the article tree before save. Cheap, fast, no LLM round-trip.

_FOOTER_HEADING_RE = re.compile(
    r"^\s*(irdai (registration|disclaimer|reg\b)|pricing note|"
    r"about (the )?(author|reviewer)|disclaimer|as of [a-z]+ \d{4})",
    re.IGNORECASE,
)
_BOX_LABEL_HEADERS = re.compile(
    r"^\s*(caveat|pro tip|irdai update|key takeaway|note|warning|"
    r"info|tip|expert tip|important|heads up)\s*:?\s*$",
    re.IGNORECASE,
)
_COMPLIANCE_HEADERS = re.compile(
    r"^\s*(irdai update|irdai note|caveat|disclaimer)\s*$",
    re.IGNORECASE,
)
_MAX_BOXES_PER_ARTICLE = 2
_MAX_BODY_SECTIONS = 7   # Hard cap on H2 sections post-normalise.
_MIN_PROSE_WORDS_FOR_SECTION = 40   # Sections under this are merged or dropped.

# H2 suffixes that add no information and are LLM filler.
_HEADING_SUFFIX_NOISE = re.compile(
    r"\s*(:|—|-)\s*("
    r"direct,?\s*specific\s*answers?|"
    r"at\s*a\s*glance|"
    r"specifics?\s*by\s*situation|"
    r"a\s*step[- ]by[- ]step\s*guide|"
    r"a\s*quick\s*comparison|"
    r"explained|"
    r"and\s*why\s*it\s*matters\s*now|"
    r"the\s*practical\s*differences"
    r")\s*$",
    re.IGNORECASE,
)

# Cute / meta H2s that are not standalone TOC entries. We strip these
# headings entirely (the prose stays under whichever H2 came before, or
# under the article H1 if it's the first section).
_CUTE_HEADING = re.compile(
    r"^\s*("
    r"picture\s+this|"
    r"imagine[\s\.,!:].{0,80}|"
    r"here'?s?\s+the\s+(quick|short)\s+answer|"
    r"the\s+quick\s+answer|"
    r"here'?s?\s+(what|how|why)|"
    r"let'?s\s+(dive|delve|explore|talk).*|"
    r"a\s+story[: ].*|"
    r"first[,]?\s+the\s+basics|"
    r"the\s+basics"
    r")\s*\.?\s*$",
    re.IGNORECASE,
)

# Box-rendered bullet_list sections often carry repeating "Quick Summary"
# or "At a glance" labels. We allow the first one and demote the rest by
# clearing their summary-style heading.
_SUMMARY_BOX_HEADING = re.compile(
    r"^\s*(quick\s*summary|at\s*a\s*glance|key\s*(takeaways?|points?)|"
    r"summary|recap|in\s*short|the\s*essentials?)\s*$",
    re.IGNORECASE,
)


def _convert_box_to_block(box: Dict) -> Dict:
    """Demote a box-style section to a content_block, preserving its prose."""
    out = dict(box)
    out["type"] = "content_block"
    out["section_type"] = "content_block"
    # Strip box label headers that are now meaningless ("CAVEAT", "PRO TIP", ...).
    heading = (out.get("heading") or out.get("h2") or "").strip()
    if heading and (_COMPLIANCE_HEADERS.match(heading) or _BOX_LABEL_HEADERS.match(heading)):
        out["heading"] = ""
        out["h2"] = ""
    # Some templates store the box text in content.text, others in content directly.
    return out


def _looks_like_footer_section(s: Dict) -> bool:
    heading = (s.get("heading") or s.get("h2") or "").strip()
    if heading and _FOOTER_HEADING_RE.match(heading):
        return True
    text = _walk_text(s).lower()
    if "irdai registration no" in text or "irdai reg. no" in text:
        return True
    if text.startswith("as of ") and len(text) < 240:
        return True
    return False


def normalize_article(article: Dict) -> Dict:
    """Deterministic clean-up. Runs after generation/editor, before save.

    What it does:
      1. Pulls compliance/footer-like sections (IRDAI registration, pricing note,
         "as of …") out of the body and into article['footer_blocks'].
      2. Merges or demotes adjacent box-style sections so two boxes never sit
         next to each other.
      3. Caps boxes at MAX_BOXES_PER_ARTICLE; demotes the rest to content_blocks.
      4. Strips meaningless box-label headings ("CAVEAT", "PRO TIP", ...).
      5. Caps body sections at MAX_BODY_SECTIONS by folding the least-substantive
         boxes/short blocks into their neighbours.
    """
    if not isinstance(article, dict):
        return article
    sections = article.get("sections") or article.get("body")
    if not isinstance(sections, list):
        return article

    # ---- 1. Footer extraction ------------------------------------------------
    footer_blocks = list(article.get("footer_blocks") or [])
    body: List[Dict] = []
    for s in sections:
        if isinstance(s, dict) and _looks_like_footer_section(s):
            footer_blocks.append(s)
        else:
            body.append(s)

    # ---- 2. Strip meaningless box-label headings -----------------------------
    for s in body:
        if not isinstance(s, dict):
            continue
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if heading and _BOX_LABEL_HEADERS.match(heading):
            s["heading"] = ""
            s["h2"] = ""

    # ---- 2b. Bare-callout sections: no H2 over a lone box -------------------
    # If a section's *type* is itself a box (callout_*, key_takeaway, etc.) and
    # it carries a long-form H2 heading, the LLM has used the H2 as a wrapper
    # for what should just be punctuation. Strip the H2 so the box renders
    # inline under whichever real content section came before. The box stays;
    # the spurious H2 (and its TOC entry) goes.
    for s in body:
        if not isinstance(s, dict):
            continue
        if not _is_box_section(s):
            continue
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if heading:
            s["heading"] = ""
            s["h2"] = ""

    # ---- 2c. Heading cleanup: trim filler suffixes, drop cute openers -------
    for i, s in enumerate(body):
        if not isinstance(s, dict):
            continue
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if not heading:
            continue
        # Strip noise suffixes ("…: at a glance", "…: a step-by-step guide", etc.)
        new_heading = _HEADING_SUFFIX_NOISE.sub("", heading).strip()
        # Drop cute / meta openers entirely.
        if _CUTE_HEADING.match(new_heading):
            new_heading = ""
        if new_heading != heading:
            s["heading"] = new_heading
            s["h2"] = new_heading

    # ---- 2d. Summary-box dedupe: only the first "Quick Summary" survives ----
    # Multiple bullet_list sections with the same summary-style heading read as
    # filler. Keep the first; strip the heading on subsequent ones so they
    # render as plain bullet lists (no big "Quick Summary" label).
    seen_summary = False
    for s in body:
        if not isinstance(s, dict):
            continue
        stype = (s.get("type") or "").lower()
        if stype != "bullet_list":
            continue
        heading = (s.get("heading") or s.get("h2") or "").strip()
        if heading and _SUMMARY_BOX_HEADING.match(heading):
            if seen_summary:
                s["heading"] = ""
                s["h2"] = ""
            else:
                seen_summary = True

    # ---- 3. Resolve adjacency: never two boxes in a row ---------------------
    fixed: List[Dict] = []
    for s in body:
        if not isinstance(s, dict):
            fixed.append(s)
            continue
        if fixed and _is_box_section(fixed[-1]) and _is_box_section(s):
            # Demote the second box to a content_block so the prose stays.
            s = _convert_box_to_block(s)
        fixed.append(s)
    body = fixed

    # ---- 4. Cap total boxes -------------------------------------------------
    box_indices = [i for i, s in enumerate(body) if isinstance(s, dict) and _is_box_section(s)]
    if len(box_indices) > _MAX_BOXES_PER_ARTICLE:
        # Keep the first MAX_BOXES_PER_ARTICLE boxes, demote the rest.
        for idx in box_indices[_MAX_BOXES_PER_ARTICLE:]:
            body[idx] = _convert_box_to_block(body[idx])

    # ---- 5. Cap section count ----------------------------------------------
    # Drop in priority order, preserving FAQ + comparison + table + the first
    # content_block (orientation) at all costs.
    if len(body) > _MAX_BODY_SECTIONS:
        excess = len(body) - _MAX_BODY_SECTIONS

        def _is_protected(idx: int) -> bool:
            if idx == 0:
                return True   # first content section is the orientation beat
            s = body[idx]
            if not isinstance(s, dict):
                return True
            t = (s.get("type") or s.get("section_type") or "").lower()
            return t in {"faq", "comparison", "table", "steps"}

        def _drop_matching(predicate):
            nonlocal excess
            i = len(body) - 1
            while excess > 0 and i >= 0:
                if not _is_protected(i) and isinstance(body[i], dict) and predicate(body[i]):
                    body.pop(i)
                    excess -= 1
                i -= 1

        # Pass 1: box-style sections (callouts, key_takeaways, expert_tips).
        _drop_matching(lambda s: _is_box_section(s))
        # Pass 2: sections with empty heading (orphan blocks, summary boxes).
        _drop_matching(lambda s: not (s.get("heading") or s.get("h2") or "").strip())
        # Pass 3: bullet_list sections with very short total text (recap boxes).
        _drop_matching(lambda s: (s.get("type") or "").lower() == "bullet_list"
                       and len(_walk_text(s).split()) < 80)
        # Pass 4: content_blocks under 60 words.
        _drop_matching(lambda s: (s.get("type") or "").lower() == "content_block"
                       and len(_walk_text(s).split()) < 60)
        # Pass 5 (last resort): drop unprotected sections from the back.
        i = len(body) - 1
        while excess > 0 and i >= 0:
            if not _is_protected(i):
                body.pop(i)
                excess -= 1
            i -= 1

    # ---- Write back ---------------------------------------------------------
    if "sections" in article:
        article["sections"] = body
    else:
        article["body"] = body
    if footer_blocks:
        article["footer_blocks"] = footer_blocks
    return article


HARD_CHECKS: List[Tuple[str, Callable[[Dict], List[Dict]]]] = [
    ("forbidden_phrases", _check_forbidden_phrases),
    ("em_dashes", _check_em_dashes),
    ("adjacent_callouts", _check_adjacent_callouts),
    ("box_overuse", _check_box_overuse),
    ("h2_self_explanatory", _check_h2_self_explanatory),
    ("h2_word_count", _check_h2_word_count),
    ("h1_is_question", _check_h1_is_question),
    ("irdai_footer", _check_irdai_footer),
    ("stage_setter", _check_stage_setter),
]


def run_hard_checks(article: Dict) -> List[Dict]:
    """Run every hard check. Returns a flat list of issue dicts (top_issues shape).
    Safe to call on any article JSON; missing fields produce no issues except
    where a missing field is itself a violation (e.g. h1_is_question)."""
    if not isinstance(article, dict):
        return []
    issues: List[Dict] = []
    for _name, fn in HARD_CHECKS:
        try:
            issues.extend(fn(article) or [])
        except Exception:
            # Hard checks must never raise — they run unconditionally before save.
            continue
    return issues


# ---------------------------------------------------------------------------
# load_rules() — combined prompt-ready canon
# ---------------------------------------------------------------------------

def _serialise_intent_scaffolds() -> str:
    parts = ["## Intent scaffolds (machine-readable)\n"]
    for name, scaf in INTENT_SCAFFOLDS.items():
        parts.append("### {}\n".format(name))
        parts.append("_When to use:_ {}\n".format(scaf["when_to_use"]))
        parts.append("_North-star IA (beats):_\n")
        for i, beat in enumerate(scaf["north_star_IA"], 1):
            parts.append('  {}. {} — *{}* ({})'.format(
                i, beat["reader_question"],
                beat["suggested_section_type"],
                beat["why_this_beat_exists"],
            ))
        parts.append("")
    return "\n".join(parts)


_RULES_CACHE: Dict[str, str] = {}


def load_rules(refresh: bool = False) -> str:
    """Returns the full prompt-ready canon: prose .md + serialised registries.

    Cached on first call. Pass refresh=True to re-read disk (useful in dev)."""
    if not refresh and "_full" in _RULES_CACHE:
        return _RULES_CACHE["_full"]

    try:
        prose = _RULES_MD.read_text(encoding="utf-8")
    except FileNotFoundError:
        prose = "# Acko Content Rules\n\n(content_rules.md is missing — using registries only.)\n"

    forbidden = "## Forbidden phrases (canonical, all callers)\n\n" + "\n".join(
        '- "{}"'.format(p) for p in FORBIDDEN_PHRASES
    )

    full = "\n\n---\n\n".join([prose, forbidden, _serialise_intent_scaffolds()])
    _RULES_CACHE["_full"] = full
    return full


__all__ = [
    "FORBIDDEN_PHRASES",
    "INTENT_SCAFFOLDS",
    "HARD_CHECKS",
    "run_hard_checks",
    "load_rules",
]
