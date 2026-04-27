"""renormalise_articles.py — apply the latest content_rules.normalize_article
to every article already saved in articles.db, and re-render their HTML.

Use this BEFORE a demo to clean up articles generated when the normaliser was
weaker (or not yet wired in). Idempotent: safe to run repeatedly.

Usage:
    python3 renormalise_articles.py            # dry run, prints what would change
    python3 renormalise_articles.py --apply    # actually writes back to DB
    python3 renormalise_articles.py --apply --id 42   # only article 42
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "articles.db"

sys.path.insert(0, str(ROOT))

from content_rules import normalize_article  # noqa: E402


def _load_render_html():
    """Import render_html from pages/3_generate.py without running streamlit code paths."""
    spec = importlib.util.spec_from_file_location(
        "gen3", str(ROOT / "pages" / "3_generate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render_html


def _section_summary(sections):
    if not isinstance(sections, list):
        return []
    out = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        t = s.get("type", "?")
        h = (s.get("heading") or s.get("h2") or "").strip()
        out.append("{}|{}".format(t, h[:60]))
    return out


def _diff(label, before, after):
    if before == after:
        return False
    print("  {}:".format(label))
    print("    BEFORE ({}):".format(len(before)))
    for x in before:
        print("      -", x)
    print("    AFTER  ({}):".format(len(after)))
    for x in after:
        print("      -", x)
    return True


def renormalise_one(conn, render_html, article_id: int, apply_changes: bool) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT structured_json FROM articles WHERE article_id = ?", (article_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        print("  [skip] article {}: no structured_json".format(article_id))
        return False

    try:
        article = json.loads(row[0])
    except json.JSONDecodeError as e:
        print("  [skip] article {}: bad JSON ({})".format(article_id, e))
        return False

    before_sections = _section_summary(article.get("sections", []))
    before_footer   = _section_summary(article.get("footer_blocks", []))

    normalised = normalize_article(article)

    after_sections = _section_summary(normalised.get("sections", []))
    after_footer   = _section_summary(normalised.get("footer_blocks", []))

    changed = (before_sections != after_sections) or (before_footer != after_footer)
    if not changed:
        print("  [ok]   article {}: already normalised".format(article_id))
        return False

    print("  [diff] article {}".format(article_id))
    _diff("body", before_sections, after_sections)
    _diff("footer", before_footer, after_footer)

    if not apply_changes:
        return True

    html = ""
    try:
        html = render_html(normalised)
    except Exception as e:
        print("    !! render failed ({}); writing JSON only".format(e))

    cur.execute(
        "UPDATE articles SET structured_json = ?, html_content = ? WHERE article_id = ?",
        (json.dumps(normalised, ensure_ascii=False), html, article_id),
    )
    conn.commit()
    print("    [written]")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually write changes")
    ap.add_argument("--id", type=int, default=None, help="Single article_id")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print("articles.db not found at {}".format(DB_PATH))
        sys.exit(1)

    render_html = None
    if args.apply:
        try:
            render_html = _load_render_html()
        except Exception as e:
            print("Could not load render_html ({}). Will write JSON only.".format(e))

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    if args.id is not None:
        ids = [args.id]
    else:
        cur.execute("SELECT article_id FROM articles ORDER BY article_id")
        ids = [r[0] for r in cur.fetchall()]

    print("Renormalising {} article(s){}".format(
        len(ids), " (DRY RUN)" if not args.apply else " (APPLYING)"))
    changed = 0
    for aid in ids:
        if renormalise_one(conn, render_html or (lambda x: ""), aid, args.apply):
            changed += 1
    print("\n{} article(s) {}.".format(
        changed, "updated" if args.apply else "would change"))
    conn.close()


if __name__ == "__main__":
    main()
