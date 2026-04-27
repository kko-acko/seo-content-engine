"""
Content Brief — Universal entry point for all content types
============================================================
Create blog articles for Enterprise, Retail, or Long-tail topics
starting from a brief, document upload, or reference URLs — no crawling needed.
"""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Dict

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from ai_helpers import MODELS
from ui import apply_theme, sidebar, page_header, section_label, pill, empty_state  # noqa: E402

CLUSTER_DB_PATH = PROJECT_ROOT / "clusters.db"

BUSINESS_LINE_CONFIG = {
    "enterprise": {
        "label": "Enterprise",
        "sub":   "B2B · HR, CFO, procurement",
        "description": "Corporate health, group insurance, fleet, workmen's comp. Consultative tone.",
    },
    "retail": {
        "label": "Retail",
        "sub":   "B2C · individuals & families",
        "description": "Car, health, bike, term insurance. Friendly, clear tone.",
    },
    "longtail": {
        "label": "Long-tail",
        "sub":   "Niche question · any line",
        "description": "Single sharp question. 800–1,200 words, laser-focused.",
    },
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_brief_db() -> None:
    """Ensure clusters.db has brief-related columns."""
    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            consumer_question   TEXT NOT NULL,
            theme               TEXT,
            page_group          TEXT DEFAULT 'informational',
            priority            INTEGER DEFAULT 0,
            urls_json           TEXT NOT NULL,
            status              TEXT DEFAULT 'draft',
            created_at          TEXT DEFAULT (datetime('now'))
        )
    """)
    for col, coltype in [
        ("audience_persona",         "TEXT"),
        ("search_trigger",           "TEXT"),
        ("secondary_questions_json", "TEXT"),
        ("enrichment_json",          "TEXT"),
        ("page_details_json",        "TEXT"),
        ("enriched_at",              "TEXT"),
        ("business_line",            "TEXT DEFAULT 'retail'"),
        ("brief_text",               "TEXT"),
        ("input_type",               "TEXT DEFAULT 'crawled'"),
    ]:
        try:
            conn.execute("ALTER TABLE clusters ADD COLUMN {} {}".format(col, coltype))
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_brief_as_cluster(
    consumer_question: str,
    theme: str,
    audience: str,
    key_angles: str,
    secondary_questions: List[str],
    business_line: str,
    brief_text: str,
    tone: str,
) -> int:
    """Insert a brief-sourced cluster into clusters.db. Returns cluster_id."""
    # Build structured brief header
    header_lines = [
        "[BRIEF]",
        "BUSINESS_LINE: {}".format(business_line.upper()),
        "TONE: {}".format(tone),
        "",
    ]
    if key_angles.strip():
        header_lines.append("KEY ANGLES TO COVER:")
        for line in key_angles.strip().splitlines():
            if line.strip():
                header_lines.append("- {}".format(line.strip()))
        header_lines.append("")

    full_brief = "\n".join(header_lines)
    if brief_text.strip():
        full_brief += "\nRESEARCH NOTES:\n{}".format(brief_text.strip())

    conn = sqlite3.connect(str(CLUSTER_DB_PATH))
    cursor = conn.execute(
        """INSERT INTO clusters
           (consumer_question, theme, page_group, priority, urls_json,
            audience_persona, secondary_questions_json,
            business_line, brief_text, input_type, status)
           VALUES (?, ?, 'informational', 5, '[]', ?, ?, ?, ?, 'brief', 'ready')""",
        (
            consumer_question,
            theme or consumer_question[:60],
            audience,
            json.dumps(secondary_questions, ensure_ascii=False),
            business_line,
            full_brief,
        ),
    )
    cluster_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return cluster_id


# ---------------------------------------------------------------------------
# Document extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(uploaded_file) -> str:
    """Extract text from an uploaded PDF using pdfplumber."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text.strip())
        return "\n\n".join(text_parts)
    except Exception as e:
        return "[PDF extraction failed: {}]".format(e)


def extract_docx_text(uploaded_file) -> str:
    """Extract text from an uploaded DOCX using python-docx."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(uploaded_file.read()))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except ImportError:
        return "[python-docx not installed. Run: pip install python-docx]"
    except Exception as e:
        return "[DOCX extraction failed: {}]".format(e)


# ---------------------------------------------------------------------------
# URL fetching (Playwright single-page, no link crawl)
# ---------------------------------------------------------------------------

EXTRACT_JS_BRIEF = """
() => {
    const title = document.title || '';
    const h1 = (document.querySelector('h1') || {}).textContent?.trim() || '';
    const metaEl = document.querySelector('meta[name="description"]');
    const meta = metaEl ? metaEl.getAttribute('content') || '' : '';

    // Extract meaningful paragraphs
    const paragraphs = Array.from(document.querySelectorAll('p, li'))
        .map(el => el.textContent?.trim() || '')
        .filter(t => t.length > 30)
        .join('\\n\\n');

    return { title, h1, meta, body_text: paragraphs };
}
"""


async def _fetch_url_async(url: str) -> Dict:
    result = {"url": url, "title": "", "h1": "", "body_text": "", "error": None}
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (compatible; AckoContentBot/1.0)"
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            data = await page.evaluate(EXTRACT_JS_BRIEF)
            result.update(data)
            await browser.close()
    except Exception as e:
        result["error"] = str(e)[:300]
    return result


def fetch_urls(urls: List[str]) -> List[Dict]:
    """Fetch a list of URLs synchronously (Playwright). Returns list of page dicts."""
    loop = asyncio.new_event_loop()

    async def _run_all():
        return [await _fetch_url_async(u) for u in urls]

    try:
        results = loop.run_until_complete(_run_all())
    finally:
        loop.close()
    return results


def assemble_brief_text(manual_text: str, doc_text: str, url_pages: List[Dict]) -> str:
    """Combine all research sources into one structured brief block."""
    parts = []
    if manual_text.strip():
        parts.append(manual_text.strip())
    if doc_text.strip():
        parts.append("\n--- FROM DOCUMENT ---\n{}".format(doc_text.strip()))
    for pg in url_pages:
        if pg.get("error"):
            continue
        heading = "--- FROM URL: {} ---".format(pg["url"])
        content = ""
        if pg.get("title"):
            content += "Title: {}\n".format(pg["title"])
        if pg.get("h1"):
            content += "H1: {}\n".format(pg["h1"])
        if pg.get("body_text"):
            content += pg["body_text"][:3000]
        if content.strip():
            parts.append("{}\n{}".format(heading, content.strip()))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Content Brief — Acko Content Studio", page_icon="●", layout="wide")

    apply_theme()
    init_brief_db()

    with st.sidebar:
        pass  # placeholder so apply_theme's sidebar CSS is live before page links
    sidebar(current="brief")

    with st.sidebar:
        st.markdown(
            '<div style="padding:18px 12px 8px;font-family:Inter,sans-serif;font-size:0.7rem;'
            'font-weight:600;letter-spacing:1.5px;color:#8d969e;text-transform:uppercase;">Settings</div>',
            unsafe_allow_html=True,
        )
        model = st.selectbox("Model", MODELS, index=0, label_visibility="collapsed")
        generate_now = st.checkbox(
            "Open Generate after saving",
            value=True,
            help="Jump straight to article generation after saving the brief.",
        )

    page_header(
        eyebrow="Path B · Brief-based",
        title="Brief Studio",
        meta="Text · PDF · DOCX · reference URLs",
    )

    from ui import stepper as _stepper
    _stepper(["Business line", "Topic & angles", "Research material"], current=0)

    # ================================================================
    # STEP 1: Business line
    # ================================================================
    section_label("Step 1 — Business line")

    bl_cols = st.columns(3, gap="small")
    bl_options = list(BUSINESS_LINE_CONFIG.keys())

    if "selected_bl" not in st.session_state:
        st.session_state.selected_bl = "retail"

    for i, bl_key in enumerate(bl_options):
        cfg = BUSINESS_LINE_CONFIG[bl_key]
        with bl_cols[i]:
            selected = st.session_state.selected_bl == bl_key
            bg = "#191c1f" if selected else "#ffffff"
            fg = "#ffffff" if selected else "#191c1f"
            sub_fg = "rgba(255,255,255,0.65)" if selected else "#8d969e"
            desc_fg = "rgba(255,255,255,0.85)" if selected else "#505a63"
            border = "#191c1f" if selected else "#e5e5e5"
            st.markdown(
                f"""
                <div style="background:{bg};border:1px solid {border};border-radius:16px;
                            padding:22px 24px;min-height:150px;">
                  <div style="font-family:Inter,sans-serif;font-size:0.7rem;font-weight:600;
                              letter-spacing:1.5px;text-transform:uppercase;color:{sub_fg};">
                    {cfg["sub"]}
                  </div>
                  <div style="font-family:'Space Grotesk',sans-serif;font-size:1.5rem;font-weight:500;
                              letter-spacing:-0.24px;color:{fg};margin-top:6px;">{cfg["label"]}</div>
                  <div style="font-family:Inter,sans-serif;font-size:0.85rem;color:{desc_fg};
                              margin-top:10px;line-height:1.5;">{cfg["description"]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Selected" if selected else "Select",
                key="bl_{}".format(bl_key),
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state.selected_bl = bl_key
                st.rerun()

    business_line = st.session_state.selected_bl
    bl_cfg = BUSINESS_LINE_CONFIG[business_line]

    # ================================================================
    # OPTIONAL: Bulk upload — autofill from a sheet
    # ================================================================
    with st.expander("📥 Have a list of topics? Upload a CSV/Excel to auto-fill", expanded=False):
        st.caption(
            "Upload a sheet with columns like **topic** (or **consumer_question**) and **description**. "
            "Optional columns: audience, theme, tone, business_line, key_angles, secondary_questions. "
            "Pick a row and the form below will be filled for you."
        )
        bulk_file = st.file_uploader(
            "CSV or Excel",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=False,
            key="bulk_topics_file",
        )
        if bulk_file is not None:
            try:
                import pandas as _pd
                if bulk_file.name.lower().endswith((".xlsx", ".xls")):
                    try:
                        df = _pd.read_excel(bulk_file)
                    except ImportError:
                        st.error("Excel support needs `openpyxl`. Save the sheet as CSV and re-upload.")
                        df = None
                else:
                    df = _pd.read_csv(bulk_file)
            except Exception as _e:
                st.error("Could not parse file: {}".format(_e))
                df = None

            if df is not None and not df.empty:
                # Normalise column names (lowercase, underscores)
                df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
                # Resolve the question column
                q_col = next((c for c in ("consumer_question", "topic", "question", "h1", "title")
                              if c in df.columns), None)
                if not q_col:
                    st.error("Sheet needs a column named one of: topic, consumer_question, question, h1, title.")
                else:
                    st.success("Loaded {} row(s). Pick one to fill the form.".format(len(df)))
                    st.dataframe(df, use_container_width=True, height=220)
                    options = ["Row {} — {}".format(i + 1, str(df.iloc[i][q_col])[:80])
                               for i in range(len(df))]
                    pick = st.selectbox("Pick a row", options, key="bulk_pick_row")
                    if st.button("Use this row", key="bulk_apply_row", type="primary"):
                        idx = options.index(pick)
                        row = df.iloc[idx]

                        def _val(col: str, default: str = "") -> str:
                            if col in df.columns:
                                v = row[col]
                                if v is None:
                                    return default
                                try:
                                    import pandas as _pd2
                                    if _pd2.isna(v):
                                        return default
                                except Exception:
                                    pass
                                return str(v).strip()
                            return default

                        st.session_state["brief_consumer_question"] = _val(q_col)
                        st.session_state["brief_audience"] = _val("audience") or _val("target_audience")
                        st.session_state["brief_theme"] = _val("theme")
                        # description maps to manual_text (research notes)
                        desc = _val("description") or _val("notes") or _val("research_notes")
                        if desc:
                            st.session_state["manual_brief_text"] = desc
                        ka = _val("key_angles") or _val("angles")
                        if ka:
                            # accept comma-, semicolon-, or pipe-separated; one per line in target
                            for sep in ("|", ";", "\n"):
                                if sep in ka:
                                    ka = "\n".join(part.strip() for part in ka.split(sep) if part.strip())
                                    break
                            st.session_state["brief_key_angles"] = ka
                        sq = _val("secondary_questions") or _val("secondary")
                        if sq:
                            for sep in ("|", ";", "\n"):
                                if sep in sq:
                                    sq = "\n".join(part.strip() for part in sq.split(sep) if part.strip())
                                    break
                            st.session_state["brief_secondary_questions"] = sq
                        # Optional business_line override
                        bl_in = _val("business_line").lower()
                        if bl_in in BUSINESS_LINE_CONFIG:
                            st.session_state.selected_bl = bl_in
                        # tone is a selectbox — we just stash it; if it doesn't match, the
                        # selectbox will fall back to its default option.
                        tn = _val("tone")
                        if tn:
                            st.session_state["brief_tone"] = tn
                        st.success("Form filled from row {}. Scroll down to review and edit.".format(idx + 1))
                        st.rerun()

    # ================================================================
    # STEP 2: Article definition
    # ================================================================
    section_label("Step 2 — Article definition")

    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        consumer_question = st.text_input(
            "Topic / Consumer question *",
            placeholder={
                "enterprise": "How does group health insurance work for a 200-person company?",
                "retail": "What factors affect car insurance premium in India?",
                "longtail": "Can I add my parents to my company's group health insurance?",
            }.get(business_line, "Enter the main question this article answers..."),
            help="This becomes the article's H1.",
            key="brief_consumer_question",
        )

        audience = st.text_input(
            "Target audience",
            placeholder={
                "enterprise": "HR Manager at a 200-person tech company in Bangalore",
                "retail": "First-time car owner, age 25-35, metro city",
                "longtail": "Employee at a mid-size company with existing group cover",
            }.get(business_line, "Who is this article for?"),
            key="brief_audience",
        )

        col_theme, col_tone = st.columns(2)
        with col_theme:
            theme = st.text_input("Theme / Content label",
                                  placeholder="e.g. group health insurance",
                                  key="brief_theme")
        with col_tone:
            tone_options = {
                "enterprise": ["Consultative (B2B)", "Technical", "Analytical"],
                "retail":     ["Friendly (B2C)", "Explanatory", "Conversational"],
                "longtail":   ["Explanatory", "Friendly (B2C)", "Technical"],
            }
            opts = tone_options.get(business_line, ["Friendly (B2C)"])
            seeded = st.session_state.get("brief_tone")
            tone_idx = opts.index(seeded) if seeded in opts else 0
            tone = st.selectbox("Tone", opts, index=tone_idx, key="brief_tone_select")

        key_angles = st.text_area(
            "Key angles to cover",
            placeholder={
                "enterprise": "- How group policy differs from retail\n- Per-head premium calculations\n- IRDAI compliance requirements\n- Enrollment & HR admin workflow",
                "retail": "- What drives the premium up or down\n- IDV explained simply\n- NCB and how to protect it\n- Add-ons worth buying",
                "longtail": "- The specific rule or policy that applies\n- Step-by-step answer\n- Common mistakes to avoid",
            }.get(business_line, "One angle per line..."),
            height=120,
            help="These become section headings. One per line.",
            key="brief_key_angles",
        )

        secondary_questions_text = st.text_area(
            "Secondary questions to also answer (optional)",
            placeholder="One question per line",
            height=80,
            key="brief_secondary_questions",
        )

    with col_right:
        section_label("Live preview")
        preview_q = consumer_question.strip() or "No question yet"
        preview_audience = audience.strip() or "No audience specified"
        preview_angles = len([l for l in key_angles.splitlines() if l.strip()]) if key_angles else 0

        st.markdown(
            f"""
            <div style="background:#fff;border:1px solid #e5e5e5;border-radius:16px;padding:24px;">
                <div style="margin-bottom:14px;">{pill(bl_cfg["label"].lower(), "dark")}</div>
                <div style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;
                            font-weight:500;letter-spacing:-0.2px;color:#191c1f;line-height:1.4;
                            margin-bottom:16px;">{preview_q[:100]}</div>
                <div style="font-family:Inter,sans-serif;font-size:0.78rem;color:#8d969e;
                            letter-spacing:1.2px;text-transform:uppercase;margin-top:14px;">Audience</div>
                <div style="font-family:Inter,sans-serif;font-size:0.88rem;color:#505a63;margin-top:4px;">{preview_audience[:80]}</div>
                <div style="font-family:Inter,sans-serif;font-size:0.78rem;color:#8d969e;
                            letter-spacing:1.2px;text-transform:uppercase;margin-top:14px;">Angles</div>
                <div style="font-family:'Space Grotesk',sans-serif;font-size:1.35rem;
                            font-weight:500;color:#191c1f;margin-top:4px;">{preview_angles}</div>
                <div style="font-family:Inter,sans-serif;font-size:0.78rem;color:#8d969e;
                            letter-spacing:1.2px;text-transform:uppercase;margin-top:14px;">Tone</div>
                <div style="font-family:Inter,sans-serif;font-size:0.88rem;color:#505a63;margin-top:4px;">{tone}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ================================================================
    # STEP 3: Research material
    # ================================================================
    section_label("Step 3 — Research material")
    st.caption("Add as much or as little as you have. The AI works with whatever you provide.")

    tab_write, tab_upload, tab_urls = st.tabs(
        ["Write a brief", "Upload document", "Reference URLs"]
    )

    manual_text = ""
    doc_text = ""
    url_pages: List[Dict] = []

    with tab_write:
        manual_text = st.text_area(
            "Research notes, product details, policy terms, data points...",
            placeholder={
                "enterprise": "Example:\n\nAcko's Group Health Insurance covers companies with 7+ employees.\nPremium starts at ₹4,500/year per person for ₹3L sum insured.\nIRDAI mandates group health for listed companies under the Factories Act.\nKey benefits: cashless at 10,000+ hospitals, no room rent sub-limit, free annual health check-up.\nHR admin portal at hr.acko.com — add/remove employees instantly.\nClaims TPA: Acko handles internally, 2-hour cashless approval SLA.",
                "retail": "Example:\n\nIDV (Insured Declared Value) = ex-showroom price minus depreciation.\nNCB ranges from 20% to 50% discount after 1-5 claim-free years.\nComprehensive = own damage + third party liability.\nThird-party only = ₹2,000-2,500/year (cheapest, IRDAI-mandated minimum).\nTop add-ons: zero dep, engine protect, roadside assistance, consumables cover.",
                "longtail": "Paste relevant policy details, rules, or FAQs here...",
            }.get(business_line, "Paste your research, talking points, or notes..."),
            height=300,
            key="manual_brief_text",
        )
        if manual_text.strip():
            word_count = len(manual_text.split())
            st.caption("{:,} words entered".format(word_count))

    with tab_upload:
        st.caption("Upload a PDF or Word document — policy brochures, product guides, sales decks, etc.")
        uploaded_file = st.file_uploader(
            "Choose a file",
            type=["pdf", "docx"],
            accept_multiple_files=False,
        )
        if uploaded_file is not None:
            with st.spinner("Extracting text from {}...".format(uploaded_file.name)):
                if uploaded_file.name.lower().endswith(".pdf"):
                    doc_text = extract_pdf_text(uploaded_file)
                elif uploaded_file.name.lower().endswith(".docx"):
                    doc_text = extract_docx_text(uploaded_file)
                else:
                    doc_text = "[Unsupported file type]"

            if doc_text and not doc_text.startswith("["):
                word_count = len(doc_text.split())
                st.success("Extracted {:,} words from {}".format(word_count, uploaded_file.name))
                with st.expander("Preview extracted text (first 1,000 chars)"):
                    st.text(doc_text[:1000])
            else:
                st.error(doc_text or "Failed to extract text.")

    with tab_urls:
        st.caption("Paste URLs (one per line) — Acko pages, competitor articles, regulatory pages. Their text will be extracted as research.")
        url_input = st.text_area(
            "URLs to fetch",
            placeholder="https://acko.com/health-insurance/group/\nhttps://irdai.gov.in/some-circular",
            height=100,
        )
        if st.button("Fetch pages", key="fetch_urls_btn"):
            raw_urls = [u.strip() for u in url_input.splitlines() if u.strip().startswith("http")]
            if not raw_urls:
                st.warning("Enter at least one valid URL starting with http/https.")
            else:
                with st.spinner("Fetching {} page(s)...".format(len(raw_urls))):
                    url_pages = fetch_urls(raw_urls)
                for pg in url_pages:
                    if pg.get("error"):
                        st.error("{} — {}".format(pg["url"], pg["error"]))
                    else:
                        words = len((pg.get("body_text") or "").split())
                        st.success("{} — {:,} words extracted".format(pg["url"], words))
                st.session_state["fetched_url_pages"] = url_pages

        # Persist fetched pages across reruns
        if "fetched_url_pages" in st.session_state:
            url_pages = st.session_state["fetched_url_pages"]

    # ================================================================
    # Research summary
    # ================================================================
    total_words = (
        len(manual_text.split()) if manual_text.strip() else 0
    ) + (
        len(doc_text.split()) if doc_text.strip() else 0
    ) + sum(
        len((pg.get("body_text") or "").split()) for pg in url_pages if not pg.get("error")
    )
    if total_words > 0:
        st.info("Total research: {:,} words across {} source(s)".format(
            total_words,
            sum([bool(manual_text.strip()), bool(doc_text.strip()), bool(url_pages)])
        ))

    # ================================================================
    # SUBMIT
    # ================================================================
    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    if not consumer_question.strip():
        st.warning("Enter a topic/question in Step 2 to continue.")
        return

    secondary_questions = [
        q.strip() for q in secondary_questions_text.splitlines()
        if q.strip()
    ]

    btn_label = "Create brief & open Generate →" if generate_now else "Save brief"

    if st.button(btn_label, type="primary", use_container_width=True):
        brief_text = assemble_brief_text(manual_text, doc_text, url_pages)

        with st.spinner("Saving brief..."):
            cluster_id = save_brief_as_cluster(
                consumer_question=consumer_question.strip(),
                theme=theme.strip() or consumer_question.strip()[:60],
                audience=audience.strip(),
                key_angles=key_angles,
                secondary_questions=secondary_questions,
                business_line=business_line,
                brief_text=brief_text,
                tone=tone,
            )

        st.success("Brief saved as cluster #{} — ready to generate.".format(cluster_id))

        # Clear fetched URL pages
        if "fetched_url_pages" in st.session_state:
            del st.session_state["fetched_url_pages"]

        if generate_now:
            st.info("Open Generate in the sidebar — your brief is tagged with source = 'brief'.")
            st.page_link("pages/3_generate.py", label="Open Generate →")


main()
