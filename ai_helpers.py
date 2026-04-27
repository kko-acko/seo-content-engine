"""
Shared AI helper — wraps OpenAI API calls to support both standard and
reasoning/thinking models (o1, o3, o3-mini, gpt-5, etc.).

Thinking models differ from standard models:
  - Use "developer" role instead of "system"
  - Use max_completion_tokens instead of max_tokens
  - Don't support temperature parameter
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODELS = [
    # Recommended default — fast, high quality, great at structured JSON
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    # Most capable (slower, more expensive)
    "gpt-5",
    "gpt-4.5-preview",
    # Reasoning / thinking (deep analysis, slowest)
    "o4-mini",
    "o3",
    "o3-pro",
    "o3-mini",
    "o1",
    "o1-pro",
    "o1-mini",
    # Previous gen
    "gpt-4o",
    "gpt-4o-mini",
]

# Older models that still use max_tokens + "system" role
_LEGACY_MODELS = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo"}

# Everything else (gpt-5, gpt-4.1, gpt-4.5, o-series) uses
# max_completion_tokens + "developer" role
REASONING_MODELS = set()  # kept for backward compat


def is_legacy_model(model: str) -> bool:
    """Check if a model uses the old max_tokens + system role API style."""
    return model in _LEGACY_MODELS


def build_messages(system_prompt: str, user_prompt: str, model: str) -> list:
    """Build message list adapted for model type.

    Standard models: system + user messages.
    Reasoning models: developer + user messages.
    """
    if is_legacy_model(model):
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    # All newer models (gpt-5, gpt-4.1, o-series) use "developer" role
    return [
        {"role": "developer", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_api_kwargs(model: str, max_tokens: int, messages: list, **extra) -> dict:
    """Build kwargs dict for client.chat.completions.create().

    Standard models: max_tokens
    Reasoning models: max_completion_tokens (no temperature)
    """
    kwargs = {"model": model, "messages": messages}

    if is_legacy_model(model):
        kwargs["max_tokens"] = max_tokens
        kwargs.update(extra)
    else:
        # All newer models use max_completion_tokens
        kwargs["max_completion_tokens"] = max_tokens
        # Don't pass temperature for o-series reasoning models
        o_series = model.startswith("o")
        if not o_series:
            kwargs.update(extra)

    return kwargs


# ---------------------------------------------------------------------------
# Robust JSON extraction
# ---------------------------------------------------------------------------
import json
import re


def extract_json(text: str) -> dict | list:
    """Extract JSON from an LLM response, handling all common wrapper patterns.

    Handles:
      - Clean JSON
      - ```json ... ``` fenced blocks
      - ``` ... ``` fenced blocks (no language tag)
      - Text before/after JSON (e.g., "Here is the JSON:\n{...}\nLet me know...")
      - Multiple fenced blocks (picks the largest)
      - Thinking tokens / preamble before the actual JSON

    Raises json.JSONDecodeError if no valid JSON found.
    """
    text = text.strip()

    # 1. Try direct parse first (fastest path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code fences (```json ... ``` or ``` ... ```)
    fence_pattern = re.compile(r'```(?:json)?\s*\n?(.*?)```', re.DOTALL)
    fenced_blocks = fence_pattern.findall(text)
    if fenced_blocks:
        # Try the largest block first (most likely the full JSON)
        for block in sorted(fenced_blocks, key=len, reverse=True):
            block = block.strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    # 3. Find the first { ... } or [ ... ] in the text (greedy match)
    #    This handles preamble text like "Here is the JSON output:\n{...}"
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        # Find the matching closing bracket by scanning from the end
        end_idx = text.rfind(end_char)
        if end_idx <= start_idx:
            continue
        candidate = text[start_idx:end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # 4. Nothing worked
    raise json.JSONDecodeError("No valid JSON found in response", text, 0)
