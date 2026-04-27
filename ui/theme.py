"""
Acko Content Studio — theme & shared UI components.

Implements design.md. Import once per Streamlit page:

    from ui import apply_theme, sidebar, page_header

    apply_theme()
    sidebar(current="dashboard")
    page_header(eyebrow="Overview", title="Dashboard")

All tokens live here. Pages should not inline CSS.
"""
from __future__ import annotations
from typing import Optional, Literal
import streamlit as st

# ─── Tokens ─────────────────────────────────────────────────────────────────
DARK        = "#191c1f"
WHITE       = "#ffffff"
SURFACE     = "#f4f4f4"
BG          = "#ffffff"           # page background
BORDER      = "#e5e5e5"
BORDER_SOFT = "#efefef"
MUTED       = "#8d969e"
SLATE       = "#505a63"

BLUE        = "#494fdf"
BLUE_LINK   = "#376cd5"
TEAL        = "#00a87e"
WARNING     = "#ec7e00"
DANGER      = "#e23b4a"
DEEP_PINK   = "#e61e49"
YELLOW      = "#b09000"
BROWN       = "#936d62"

# Studio v2 accent — violet (Asana × Stripe direction)
ACCENT       = "#6b5bff"
ACCENT_DARK  = "#4a3bd8"
ACCENT_SOFT  = "#eeebff"
ACCENT_INK   = "#2b1d9e"
INK          = "#0a0b13"          # deep near-black (Studio v2)
BG_SOFT      = "#fbfbfd"          # page bg tint
SURFACE_ALT  = "#f5f6f8"          # hover / recessed
RULE         = "#e8eaf0"
RULE_SOFT    = "#f0f1f5"
TEXT_BODY    = "#2b2e3a"
TEXT_FAINT   = "#9aa0b1"

OK_BG        = "#e6f5ee"
OK_FG        = "#15a06b"
WARN_BG      = "#fbf1dc"
WARN_FG      = "#d08400"
BAD_BG       = "#fbe9e9"
BAD_FG       = "#d54747"

ENT_FG       = "#0f766e"
ENT_BG       = "#e3f1ef"
NICHE_FG     = "#c2410c"
NICHE_BG     = "#fbece0"

# ─── Global CSS ─────────────────────────────────────────────────────────────
_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

:root {{
  --rui-dark: {DARK};
  --rui-white: {WHITE};
  --rui-surface: {SURFACE};
  --rui-border: {BORDER};
  --rui-border-soft: {BORDER_SOFT};
  --rui-muted: {MUTED};
  --rui-slate: {SLATE};
  --rui-blue: {BLUE};
  --rui-blue-link: {BLUE_LINK};
  --rui-teal: {TEAL};
  --rui-warning: {WARNING};
  --rui-danger: {DANGER};
  --rui-deep-pink: {DEEP_PINK};
  --rui-yellow: {YELLOW};
  --rui-brown: {BROWN};
}}

/* ── Base ── */
html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"] {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
  color: {DARK} !important;
  letter-spacing: 0.16px;
}}
.stApp {{ background: {BG} !important; }}
.block-container {{
  padding-top: 2.5rem !important;
  padding-bottom: 4rem !important;
  max-width: 1280px !important;
}}

/* ── Display type (Space Grotesk) ── */
h1, h2, h3, h4, .display {{
  font-family: 'Space Grotesk', 'Inter', sans-serif !important;
  font-weight: 500 !important;
  color: {DARK} !important;
  letter-spacing: -0.02em;
  line-height: 1.15;
}}
h1 {{ font-size: 3rem !important; letter-spacing: -0.48px; margin: 0 0 0.5rem 0 !important; }}
h2 {{ font-size: 2rem !important; letter-spacing: -0.32px; margin: 2rem 0 0.75rem 0 !important; }}
h3 {{ font-size: 1.5rem !important; letter-spacing: -0.24px; margin: 1.5rem 0 0.5rem 0 !important; }}
p, li, div, span {{ letter-spacing: 0.16px; }}

/* ── Links ── */
a {{ color: {BLUE_LINK} !important; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* ── Sidebar (light) ── */
[data-testid="stSidebar"] {{
  background: {WHITE} !important;
  border-right: 1px solid {BORDER} !important;
  padding-top: 0 !important;
}}
[data-testid="stSidebar"] > div {{ padding-top: 1rem !important; }}
[data-testid="stSidebarNav"] {{ display: none !important; }}
[data-testid="stSidebar"] * {{ color: {DARK} !important; }}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] [data-testid="stCaption"] {{
  color: {MUTED} !important;
}}

/* Side-nav links */
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {{
  font-family: 'Space Grotesk', sans-serif !important;
  font-size: 0.95rem !important;
  font-weight: 500 !important;
  color: {SLATE} !important;
  border-radius: 10px !important;
  padding: 8px 12px !important;
  margin: 2px 0 !important;
  transition: background 0.12s, color 0.12s !important;
}}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {{
  background: {SURFACE} !important;
  color: {DARK} !important;
}}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] p {{
  color: inherit !important;
  margin: 0 !important;
  font-weight: inherit !important;
}}

/* ── Buttons — universal pill ── */
.stButton > button, .stDownloadButton > button, [data-testid="baseButton-secondary"], [data-testid="baseButton-primary"] {{
  font-family: 'Space Grotesk', sans-serif !important;
  font-size: 0.95rem !important;
  font-weight: 500 !important;
  letter-spacing: 0.1px !important;
  border-radius: 9999px !important;
  padding: 10px 26px !important;
  border: 1.5px solid {DARK} !important;
  background: {WHITE} !important;
  color: {DARK} !important;
  box-shadow: none !important;
  transition: opacity 0.12s, transform 0.08s !important;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
  opacity: 0.85 !important;
  transform: none !important;
  box-shadow: none !important;
}}
.stButton > button[kind="primary"] {{
  background: {DARK} !important;
  color: {WHITE} !important;
  border-color: {DARK} !important;
}}
.stButton > button[kind="primary"]:hover {{ opacity: 0.85 !important; }}
.stButton > button[kind="secondary"] {{
  background: {SURFACE} !important;
  border-color: {SURFACE} !important;
  color: {DARK} !important;
}}

/* ── Form controls ── */
input, textarea, select, [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {{
  font-family: 'Inter', sans-serif !important;
  border-radius: 10px !important;
  border: 1px solid {BORDER} !important;
  background: {WHITE} !important;
  color: {DARK} !important;
}}
[data-baseweb="select"] > div {{
  border-radius: 10px !important;
  border: 1px solid {BORDER} !important;
  background: {WHITE} !important;
}}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"]:focus-within > div {{
  border-color: {DARK} !important;
  box-shadow: 0 0 0 3px rgba(25,28,31,0.08) !important;
}}
.stRadio [role="radiogroup"] label, .stCheckbox label {{ color: {DARK} !important; }}

/* ── Metric cards (flat) ── */
[data-testid="stMetric"] {{
  background: {WHITE} !important;
  border: 1px solid {BORDER} !important;
  border-radius: 16px !important;
  padding: 20px 22px !important;
  box-shadow: none !important;
}}
[data-testid="stMetricValue"] {{
  font-family: 'Space Grotesk', sans-serif !important;
  font-size: 2rem !important;
  font-weight: 500 !important;
  color: {DARK} !important;
  letter-spacing: -0.32px !important;
}}
[data-testid="stMetricLabel"] {{
  font-family: 'Inter', sans-serif !important;
  font-size: 0.75rem !important;
  font-weight: 600 !important;
  color: {MUTED} !important;
  text-transform: uppercase !important;
  letter-spacing: 1.5px !important;
}}
[data-testid="stMetricDelta"] {{
  color: {SLATE} !important;
  font-size: 0.8rem !important;
  font-weight: 500 !important;
}}

/* ── Containers ── */
[data-testid="stExpander"] {{
  border: 1px solid {BORDER} !important;
  border-radius: 12px !important;
  background: {WHITE} !important;
  box-shadow: none !important;
}}
[data-testid="stExpander"] summary {{
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 500 !important;
}}

/* ── Tabs ── */
[data-baseweb="tab-list"] {{
  gap: 4px !important;
  border-bottom: 1px solid {BORDER} !important;
}}
[data-baseweb="tab"] {{
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 500 !important;
  font-size: 0.95rem !important;
  color: {MUTED} !important;
  background: transparent !important;
  border-radius: 10px 10px 0 0 !important;
  padding: 10px 18px !important;
}}
[data-baseweb="tab"][aria-selected="true"] {{
  color: {DARK} !important;
  border-bottom: 2px solid {DARK} !important;
}}

/* ── Dividers ── */
hr {{ border: none !important; border-top: 1px solid {BORDER} !important; margin: 2rem 0 !important; }}

/* ── Alerts ── */
[data-testid="stAlert"] {{
  border-radius: 12px !important;
  border: 1px solid {BORDER} !important;
  box-shadow: none !important;
}}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER} !important; border-radius: 12px !important; }}

/* ── Progress ── */
[data-testid="stProgressBar"] > div > div {{ background: {DARK} !important; }}

/* ── Captions ── */
.stCaption, [data-testid="stCaption"] {{ color: {MUTED} !important; font-size: 0.8rem !important; }}

/* ── Acko-specific utility classes used by helpers below ── */
.rui-eyebrow {{
  font-family: 'Inter', sans-serif;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: {MUTED};
  margin-bottom: 8px;
}}
.rui-header {{
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 24px; margin: 0 0 24px 0; padding-bottom: 20px;
  border-bottom: 1px solid {BORDER};
}}
.rui-header h1 {{
  font-family: 'Space Grotesk', sans-serif !important;
  font-size: 3rem !important;
  font-weight: 500 !important;
  letter-spacing: -0.48px !important;
  line-height: 1.0 !important;
  color: {DARK} !important;
  margin: 0 !important;
}}
.rui-header .rui-meta {{
  font-family: 'Inter', sans-serif;
  font-size: 0.85rem;
  color: {MUTED};
  white-space: nowrap;
  padding-bottom: 6px;
}}
.rui-section-label {{
  font-family: 'Inter', sans-serif;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: {MUTED};
  margin: 32px 0 14px 0;
}}
.rui-card {{
  background: {WHITE};
  border: 1px solid {BORDER};
  border-radius: 20px;
  padding: 28px;
}}
.rui-card-compact {{
  background: {WHITE};
  border: 1px solid {BORDER};
  border-radius: 12px;
  padding: 20px;
}}
.rui-stat {{
  background: {WHITE};
  border: 1px solid {BORDER};
  border-radius: 16px;
  padding: 22px 24px;
  min-height: 108px;
  display: flex; flex-direction: column; justify-content: space-between;
}}
.rui-stat .lbl {{
  font-family: 'Inter', sans-serif;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: {MUTED};
}}
.rui-stat .val {{
  font-family: 'Space Grotesk', sans-serif;
  font-size: 2.25rem;
  font-weight: 500;
  letter-spacing: -0.4px;
  color: {DARK};
  line-height: 1;
  margin-top: 4px;
}}
.rui-stat .hint {{
  font-family: 'Inter', sans-serif;
  font-size: 0.8rem;
  color: {SLATE};
  margin-top: 10px;
}}
.rui-pill {{
  display: inline-flex; align-items: center;
  padding: 4px 10px;
  border-radius: 9999px;
  font-family: 'Inter', sans-serif;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  background: {SURFACE};
  color: {SLATE};
}}
.rui-pill.success {{ background: rgba(0,168,126,0.10); color: {TEAL}; }}
.rui-pill.warning {{ background: rgba(236,126,0,0.10); color: {WARNING}; }}
.rui-pill.danger  {{ background: rgba(226,59,74,0.10); color: {DANGER}; }}
.rui-pill.info    {{ background: rgba(73,79,223,0.10); color: {BLUE}; }}
.rui-pill.dark    {{ background: {DARK}; color: {WHITE}; }}

.rui-empty {{
  background: {WHITE};
  border: 1px dashed {BORDER};
  border-radius: 16px;
  padding: 56px 24px;
  text-align: center;
}}
.rui-empty .t {{
  font-family: 'Space Grotesk', sans-serif;
  font-size: 1.1rem;
  font-weight: 500;
  color: {DARK};
  margin-bottom: 6px;
}}
.rui-empty .d {{
  font-family: 'Inter', sans-serif;
  font-size: 0.9rem;
  color: {MUTED};
}}

.rui-brand {{
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 500;
  font-size: 1.35rem;
  letter-spacing: -0.04em;
  color: {DARK};
  padding: 4px 6px 2px;
  line-height: 1;
}}
.rui-brand-dot {{ color: {BLUE}; }}
.rui-brand-sub {{
  font-family: 'Inter', sans-serif;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: {MUTED};
  padding: 2px 6px 14px;
  border-bottom: 1px solid {BORDER};
  margin-bottom: 10px;
}}
.rui-nav-group {{
  font-family: 'Inter', sans-serif;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: {MUTED};
  padding: 14px 12px 4px;
}}

/* ── Studio v2 primitives ── */

/* Dual entry hero cards (Path A / Path B) */
.rui-hero-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
  margin: 8px 0 28px 0;
}}
.rui-hero {{
  position: relative; overflow: hidden;
  border-radius: 14px;
  padding: 28px 28px 24px;
  border: 1px solid {RULE};
  background: {WHITE};
  min-height: 210px;
  display: flex; flex-direction: column; justify-content: space-between;
}}
.rui-hero.path-a {{
  background:
    radial-gradient(circle at 85% 0%, {ACCENT_SOFT} 0%, transparent 55%),
    {WHITE};
}}
.rui-hero.path-b {{
  background: {INK}; border-color: {INK}; color: {WHITE};
}}
.rui-hero .eyebrow {{
  font-family: 'Inter',sans-serif; font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: {ACCENT_INK}; margin-bottom: 10px;
}}
.rui-hero.path-b .eyebrow {{ color: {TEXT_FAINT}; }}
.rui-hero .h {{
  font-family: 'Inter',sans-serif; font-weight: 700;
  font-size: 22px; letter-spacing: -0.018em; color: {INK}; line-height: 1.2;
}}
.rui-hero.path-b .h {{ color: {WHITE}; }}
.rui-hero .d {{
  font-size: 13.5px; line-height: 1.55; color: {TEXT_BODY};
  margin-top: 8px; max-width: 380px;
}}
.rui-hero.path-b .d {{ color: rgba(255,255,255,0.72); }}
.rui-hero .meta {{
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11.5px; color: {TEXT_FAINT};
  margin-top: 16px; letter-spacing: 0;
}}
.rui-hero.path-b .meta {{ color: rgba(255,255,255,0.55); }}

/* Right-rail side cards */
.rui-side-card {{
  background: {WHITE}; border: 1px solid {RULE};
  border-radius: 12px; padding: 16px 18px; margin-bottom: 12px;
}}
.rui-side-card .t {{
  font-family:'Inter',sans-serif; font-weight: 600; font-size: 13px;
  color: {INK}; margin-bottom: 10px; letter-spacing: -0.005em;
}}
.rui-side-card .row {{
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12.5px; color: {TEXT_BODY}; padding: 5px 0;
}}
.rui-side-card .row .v {{ color: {TEXT_FAINT}; font-family:'JetBrains Mono',monospace; font-size: 11.5px; }}
.rui-side-card .bar {{
  height: 4px; background: {RULE_SOFT}; border-radius: 99px; overflow: hidden; margin: 4px 0 10px;
}}
.rui-side-card .bar > span {{ display:block; height: 100%; background: {ACCENT}; border-radius: 99px; }}

/* Dark tip card */
.rui-tip-dark {{
  background: {INK}; color: {WHITE}; border-radius: 12px; padding: 18px 20px;
  border: 1px solid {INK};
}}
.rui-tip-dark .t {{
  font-family:'Inter',sans-serif; font-weight:600; font-size: 13px;
  color: {WHITE}; letter-spacing: -0.005em;
}}
.rui-tip-dark .d {{ font-size: 12.5px; color: rgba(255,255,255,0.7); margin-top: 6px; line-height: 1.55; }}
.rui-kbd {{
  display: inline-flex; align-items:center; justify-content:center;
  min-width: 22px; padding: 2px 6px; border-radius: 4px;
  background: rgba(255,255,255,0.08); color: {WHITE};
  font-family: 'JetBrains Mono',monospace; font-size: 11px;
  border: 1px solid rgba(255,255,255,0.12);
}}

/* Activity feed rows */
.rui-activity {{
  background: {WHITE}; border: 1px solid {RULE}; border-radius: 12px;
  overflow: hidden;
}}
.rui-activity .head {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid {RULE_SOFT};
}}
.rui-activity .head .t {{ font-family:'Inter',sans-serif; font-weight:600; font-size: 13px; color:{INK}; }}
.rui-row {{
  display: grid; grid-template-columns: 36px 1fr auto; gap: 12px;
  align-items: center; padding: 12px 18px; border-bottom: 1px solid {RULE_SOFT};
}}
.rui-row:last-child {{ border-bottom: none; }}
.rui-row .icon {{
  width: 32px; height: 32px; border-radius: 8px;
  background: {ACCENT_SOFT}; color: {ACCENT_INK};
  display: flex; align-items: center; justify-content: center;
  font-family:'JetBrains Mono',monospace; font-size: 12px; font-weight: 600;
}}
.rui-row .icon.dark {{ background: {INK}; color: {WHITE}; }}
.rui-row .icon.ok {{ background: {OK_BG}; color: {OK_FG}; }}
.rui-row .icon.warn {{ background: {WARN_BG}; color: {WARN_FG}; }}
.rui-row .body {{ display: flex; flex-direction: column; gap: 2px; min-width:0; }}
.rui-row .body .t {{ font-size: 13px; color: {INK}; font-weight: 500; letter-spacing: -0.005em; }}
.rui-row .body .s {{ font-size: 12px; color: {TEXT_FAINT}; }}

/* Segmented control */
.rui-seg {{
  display:inline-flex; background: {SURFACE_ALT}; border-radius: 99px; padding: 3px;
  border: 1px solid {RULE_SOFT}; gap: 2px;
}}
.rui-seg .s {{
  font-size: 12px; font-weight: 500; color: {TEXT_BODY};
  padding: 5px 12px; border-radius: 99px; cursor: pointer;
}}
.rui-seg .s.on {{ background: {WHITE}; color: {INK}; box-shadow: 0 1px 2px rgba(15,17,35,0.04); }}

/* Horizontal stepper (Path B) */
.rui-stepper {{
  display: flex; align-items: center; gap: 12px; margin: 16px 0 28px;
}}
.rui-step {{
  display: flex; align-items: center; gap: 10px;
}}
.rui-step .disc {{
  width: 26px; height: 26px; border-radius: 99px;
  display:flex; align-items:center; justify-content:center;
  font-family:'JetBrains Mono',monospace; font-size: 12px; font-weight: 600;
  background: {WHITE}; border: 1.5px solid {RULE}; color: {TEXT_FAINT};
}}
.rui-step.done .disc {{ background: {ACCENT}; border-color: {ACCENT}; color: {WHITE}; }}
.rui-step.active .disc {{ background: {WHITE}; border-color: {ACCENT}; color: {ACCENT_INK}; box-shadow: 0 0 0 4px {ACCENT_SOFT}; }}
.rui-step .lbl {{ font-size: 13px; font-weight: 500; color: {TEXT_BODY}; }}
.rui-step.active .lbl {{ color: {INK}; }}
.rui-step-line {{
  flex: 1; height: 2px; background: {RULE_SOFT}; border-radius: 99px;
}}
.rui-step-line.done {{ background: {ACCENT}; }}

/* Pipeline tracker (Run detail) */
.rui-pipeline {{
  position: relative; display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 0; padding: 20px 0 8px;
}}
.rui-pipeline::before {{
  content: ''; position: absolute; left: 12%; right: 12%; top: 32px;
  height: 2px; background: {RULE_SOFT}; border-radius: 99px;
}}
.rui-pipeline .cell {{ position: relative; text-align: center; }}
.rui-pipeline .cell .disc {{
  width: 26px; height: 26px; border-radius: 99px; margin: 0 auto 8px;
  background: {WHITE}; border: 1.5px solid {RULE}; color: {TEXT_FAINT};
  display:flex; align-items:center; justify-content:center;
  font-family:'JetBrains Mono',monospace; font-size: 12px; font-weight: 600;
  position: relative; z-index: 1;
}}
.rui-pipeline .cell.done .disc {{ background: {ACCENT}; border-color: {ACCENT}; color: {WHITE}; }}
.rui-pipeline .cell.active .disc {{
  background: {WHITE}; border-color: {ACCENT}; color: {ACCENT_INK};
  box-shadow: 0 0 0 5px {ACCENT_SOFT};
}}
.rui-pipeline .cell .lbl {{ font-size: 12px; color: {TEXT_BODY}; font-weight: 500; }}
.rui-pipeline .cell.active .lbl {{ color: {INK}; }}

/* Dark launch bar (Generate) */
.rui-launch {{
  background: {INK}; color: {WHITE}; border-radius: 14px;
  padding: 22px 24px;
  display: flex; align-items: center; justify-content: space-between; gap: 18px;
}}
.rui-launch .meta {{ font-size: 12.5px; color: rgba(255,255,255,0.64); margin-top: 4px; font-family:'JetBrains Mono',monospace; }}
.rui-launch .h {{ font-family:'Inter',sans-serif; font-weight:600; font-size: 15px; letter-spacing:-0.005em; }}
.rui-launch .btn-primary {{
  background: {WHITE}; color: {INK}; border: none; padding: 10px 22px;
  border-radius: 10px; font-family:'Inter',sans-serif; font-weight: 600; font-size: 13.5px; cursor: pointer;
}}

/* Terminal log (Run detail) */
.rui-log {{
  background: #0e1019; color: #d4d7e0; border-radius: 12px;
  padding: 14px 16px; font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11.5px; line-height: 1.7; max-height: 360px; overflow-y: auto;
}}
.rui-log .line {{ display: grid; grid-template-columns: 72px 1fr; gap: 12px; }}
.rui-log .line .tag {{ color: {ACCENT}; font-weight: 500; }}
.rui-log .line .tag.ok {{ color: #4ade80; }}
.rui-log .line .tag.warn {{ color: #fbbf24; }}
.rui-log .cur {{ display:inline-block; width: 7px; height: 14px; background:{ACCENT}; vertical-align: middle; animation: blink 1s step-end infinite; }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}

/* Business-line pills — Studio v2 palette */
.rui-pill.retail    {{ background: {ACCENT_SOFT}; color: {ACCENT_INK}; }}
.rui-pill.enterprise{{ background: {ENT_BG}; color: {ENT_FG}; }}
.rui-pill.niche     {{ background: {NICHE_BG}; color: {NICHE_FG}; }}
.rui-pill.accent    {{ background: {ACCENT_SOFT}; color: {ACCENT_INK}; }}

/* Top bar (breadcrumb + actions) */
.rui-topbar {{
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 6px 0 18px; border-bottom: 1px solid {RULE_SOFT};
  margin: -8px 0 20px;
}}
.rui-topbar .crumb {{
  font-family: 'Inter',sans-serif; font-size: 12.5px; color: {TEXT_FAINT};
}}
.rui-topbar .crumb b {{ color: {INK}; font-weight: 600; }}
.rui-topbar .search {{
  flex: 1; max-width: 380px; background: {SURFACE_ALT}; border: 1px solid {RULE_SOFT};
  border-radius: 8px; padding: 7px 12px; font-size: 12.5px; color: {TEXT_FAINT};
  display: flex; align-items:center; gap: 8px;
}}
.rui-topbar .kbd {{ margin-left: auto; font-family:'JetBrains Mono',monospace; font-size: 11px;
  background: {WHITE}; border: 1px solid {RULE}; color: {TEXT_FAINT};
  padding: 1px 6px; border-radius: 4px; }}

/* Hide only the deploy + actions, leave the toolbar wrapper alone so the
   sidebar collapse arrow stays reachable on current Streamlit. */
[data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stAppDeployButton"],
[data-testid="stToolbarActions"] {{ display: none !important; }}
/* Force the collapse/expand control visible (different testids across versions). */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"],
[aria-label="Open sidebar"], [aria-label="Close sidebar"] {{
    display: flex !important; visibility: visible !important; opacity: 1 !important;
    z-index: 999999 !important; pointer-events: auto !important;
}}
/* When the sidebar is collapsed/narrow, hide our nav body so it doesn't
   render as a vertically-stacked single-character column. */
[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"],
[data-testid="stSidebar"][aria-expanded="false"] .rui-brand,
[data-testid="stSidebar"][aria-expanded="false"] .rui-brand-sub,
[data-testid="stSidebar"][aria-expanded="false"] .rui-nav-group {{
    display: none !important;
}}
/* Same protection if Streamlit transforms the sidebar off-screen. */
[data-testid="stSidebar"][aria-collapsed="true"] > div,
[data-testid="stSidebar"][data-collapsed="true"] > div {{
    display: none !important;
}}
#MainMenu, footer {{ visibility: hidden !important; }}
</style>
"""


# ─── Public API ─────────────────────────────────────────────────────────────

def apply_theme() -> None:
    """Inject global CSS. Call once, at the top of every Streamlit page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def _flat(s: str) -> str:
    """Collapse multi-line HTML to a single line.
    Streamlit's markdown parser treats lines with 4+ leading spaces as a <pre>
    code block. Every HTML string that goes through st.markdown must be flat.
    """
    return "".join(line.strip() for line in s.splitlines())


# Nav schema — two parallel paths (A: Crawl / B: Brief) converge at Generate
_NAV_MAIN = [
    ("home",        "Home",             "app.py"),
]
_NAV_PATH_A = [
    ("crawler",     "Crawl",            "pages/1_crawler.py"),
    ("patha",       "Cluster",          "pages/2_clusters.py"),
]
_NAV_PATH_B = [
    ("pathb",       "Brief",            "pages/0_content_brief.py"),
]
_NAV_CONVERGE = [
    ("generate",    "Generate",         "pages/3_generate.py"),
    ("library",     "Library",          "pages/7_library.py"),
]


def sidebar(current: str = "") -> None:
    """Render the shared sidebar. `current` is a key from the nav schema."""
    with st.sidebar:
        st.markdown(
            '<div class="rui-brand">acko<span class="rui-brand-dot">.</span></div>'
            '<div class="rui-brand-sub">Content Studio</div>',
            unsafe_allow_html=True,
        )
        for key, label, route in _NAV_MAIN:
            st.page_link(route, label=label)
        st.markdown('<div class="rui-nav-group">Path A · Crawl</div>', unsafe_allow_html=True)
        for key, label, route in _NAV_PATH_A:
            st.page_link(route, label=label)
        st.markdown('<div class="rui-nav-group">Path B · Brief</div>', unsafe_allow_html=True)
        for key, label, route in _NAV_PATH_B:
            st.page_link(route, label=label)
        st.markdown('<div class="rui-nav-group">Output</div>', unsafe_allow_html=True)
        for key, label, route in _NAV_CONVERGE:
            st.page_link(route, label=label)
        # Footer in normal flow (not position:absolute) so it never overlaps
        # the last nav link's hit area.
        st.markdown(
            f'<div style="margin-top:32px;padding-top:14px;border-top:1px solid {BORDER};'
            f'font-family:Inter,sans-serif;font-size:0.72rem;color:{MUTED};">'
            f'Acko Content Studio · v2.0</div>',
            unsafe_allow_html=True,
        )


def page_header(eyebrow: Optional[str] = None, title: str = "", meta: Optional[str] = None) -> None:
    """Consistent page header with eyebrow + title + right-side meta."""
    eyebrow_html = f'<div class="rui-eyebrow">{eyebrow}</div>' if eyebrow else ""
    meta_html = f'<div class="rui-meta">{meta}</div>' if meta else ""
    st.markdown(
        f'<div class="rui-header"><div>{eyebrow_html}<h1>{title}</h1></div>{meta_html}</div>',
        unsafe_allow_html=True,
    )


def section_label(text: str) -> None:
    st.markdown(f'<div class="rui-section-label">{text}</div>', unsafe_allow_html=True)


def stat_card(label: str, value: str, hint: Optional[str] = None) -> str:
    hint_html = f'<div class="hint">{hint}</div>' if hint else ""
    return f'<div class="rui-stat"><div class="lbl">{label}</div><div class="val">{value}</div>{hint_html}</div>'


def stat_row(stats: list) -> None:
    """Render a responsive row of stat cards. stats = [(label, value, hint?), ...]."""
    cols = max(1, len(stats))
    pieces = []
    for s in stats:
        lbl = s[0]
        val = s[1]
        hint = s[2] if len(s) > 2 else None
        pieces.append(stat_card(lbl, val, hint))
    inner = "".join(pieces)
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat({cols},minmax(0,1fr));gap:14px;">{inner}</div>',
        unsafe_allow_html=True,
    )


Tone = Literal["neutral", "success", "warning", "danger", "info", "dark"]


def pill(text: str, tone: Tone = "neutral") -> str:
    cls = "" if tone == "neutral" else f" {tone}"
    return f'<span class="rui-pill{cls}">{text}</span>'


def empty_state(title: str, body: str = "") -> None:
    st.markdown(
        f'<div class="rui-empty"><div class="t">{title}</div><div class="d">{body}</div></div>',
        unsafe_allow_html=True,
    )


def card_open(compact: bool = False) -> None:
    cls = "rui-card-compact" if compact else "rui-card"
    st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def divider() -> None:
    st.markdown("<hr/>", unsafe_allow_html=True)


# ─── Studio v2 primitives ───────────────────────────────────────────────────

def topbar(crumbs: list, actions_html: str = "") -> None:
    """Top bar with breadcrumb + optional right-side actions HTML.
    crumbs = [("Studio", False), ("Home", True)]  # (label, is_current)
    """
    parts = []
    for i, (lbl, cur) in enumerate(crumbs):
        if i > 0:
            parts.append('<span style="margin:0 8px;color:#c9cdd8;">/</span>')
        parts.append(f'<b>{lbl}</b>' if cur else f'<span>{lbl}</span>')
    crumb_html = "".join(parts)
    st.markdown(
        f'<div class="rui-topbar">'
        f'<div class="crumb">{crumb_html}</div>'
        f'<div style="display:flex;align-items:center;gap:10px;">{actions_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def hero_grid(path_a: dict, path_b: dict) -> None:
    """Two-up hero entry cards. Each dict: eyebrow, title, desc, meta, cta_label, cta_route.
    CTA is rendered as an st.page_link below each card so routing works reliably.
    """
    def _card(d: dict, kind: str) -> str:
        return (
            f'<div class="rui-hero {kind}">'
            f'<div>'
            f'<div class="eyebrow">{d.get("eyebrow","")}</div>'
            f'<div class="h">{d.get("title","")}</div>'
            f'<div class="d">{d.get("desc","")}</div>'
            f'</div>'
            f'<div class="meta">{d.get("meta","")}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="rui-hero-grid">{_card(path_a,"path-a")}{_card(path_b,"path-b")}</div>',
        unsafe_allow_html=True,
    )
    # Working CTA buttons — Streamlit page_link handles routing reliably
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if path_a.get("cta_label") and path_a.get("cta_route"):
            st.page_link(path_a["cta_route"], label=f'{path_a["cta_label"]}  →')
    with c2:
        if path_b.get("cta_label") and path_b.get("cta_route"):
            st.page_link(path_b["cta_route"], label=f'{path_b["cta_label"]}  →')


def side_card(title: str, body_html: str) -> None:
    st.markdown(
        f'<div class="rui-side-card"><div class="t">{title}</div>{body_html}</div>',
        unsafe_allow_html=True,
    )


def tip_dark(title: str, body: str, kbd: Optional[str] = None) -> None:
    kbd_html = f' <span class="rui-kbd">{kbd}</span>' if kbd else ""
    st.markdown(
        f'<div class="rui-tip-dark"><div class="t">{title}{kbd_html}</div><div class="d">{body}</div></div>',
        unsafe_allow_html=True,
    )


def activity_feed(title: str, rows: list, right_html: str = "") -> None:
    """rows = [(icon_text, icon_tone, title, subtitle, right_pill_html), ...]"""
    row_html = []
    for ic, tone, t, s, rp in rows:
        tone_cls = f" {tone}" if tone else ""
        row_html.append(
            f'<div class="rui-row">'
            f'<div class="icon{tone_cls}">{ic}</div>'
            f'<div class="body"><div class="t">{t}</div><div class="s">{s}</div></div>'
            f'<div>{rp}</div></div>'
        )
    inner = "".join(row_html) if row_html else (
        f'<div style="padding:28px;text-align:center;color:{TEXT_FAINT};font-size:13px;">Nothing yet.</div>'
    )
    st.markdown(
        f'<div class="rui-activity">'
        f'<div class="head"><div class="t">{title}</div><div>{right_html}</div></div>'
        f'{inner}'
        f'</div>',
        unsafe_allow_html=True,
    )


def stepper(steps: list, current: int) -> None:
    """Horizontal stepper. steps = ["Basics","Tone","Review"], current is 0-indexed."""
    parts = []
    for i, lbl in enumerate(steps):
        state = "done" if i < current else ("active" if i == current else "")
        disc = "✓" if i < current else str(i + 1)
        parts.append(f'<div class="rui-step {state}"><div class="disc">{disc}</div><div class="lbl">{lbl}</div></div>')
        if i < len(steps) - 1:
            line_cls = "done" if i < current else ""
            parts.append(f'<div class="rui-step-line {line_cls}"></div>')
    st.markdown(f'<div class="rui-stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def pipeline_tracker(steps: list, current: int) -> None:
    """4-up horizontal pipeline tracker. current 0-indexed; < current = done."""
    cells = []
    for i, lbl in enumerate(steps):
        state = "done" if i < current else ("active" if i == current else "")
        disc = "✓" if i < current else str(i + 1)
        cells.append(f'<div class="cell {state}"><div class="disc">{disc}</div><div class="lbl">{lbl}</div></div>')
    st.markdown(f'<div class="rui-pipeline">{"".join(cells)}</div>', unsafe_allow_html=True)


def launch_bar(title: str, meta: str, cta_label: str, cta_href: str = "#") -> None:
    st.markdown(
        f'<div class="rui-launch">'
        f'<div><div class="h">{title}</div><div class="meta">{meta}</div></div>'
        f'<a href="{cta_href}" target="_self" style="text-decoration:none;">'
        f'<span class="btn-primary">{cta_label} →</span></a>'
        f'</div>',
        unsafe_allow_html=True,
    )


def log_panel(lines: list, cursor: bool = True) -> None:
    """Terminal-style log. lines = [(tag, tone, message), ...]  tone in ('', 'ok', 'warn')."""
    html = []
    for tag, tone, msg in lines:
        tc = f"tag {tone}" if tone else "tag"
        html.append(f'<div class="line"><span class="{tc}">{tag}</span><span>{msg}</span></div>')
    if cursor:
        html.append('<div class="line"><span class="tag">▸</span><span><span class="cur"></span></span></div>')
    st.markdown(f'<div class="rui-log">{"".join(html)}</div>', unsafe_allow_html=True)
