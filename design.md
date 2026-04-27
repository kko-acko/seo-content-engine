# Acko Content Studio — Design System (Revolut-inspired)

This is the single source of truth for the Content Studio UI. Every page imports
`ui/theme.py`, which implements this spec. Tweaks to tokens below should be
reflected in `ui/theme.py` and nowhere else.

## 1. Atmosphere
Fintech-grade confidence: massive, tightly-tracked display type on a near-black
+ white palette, pill-shaped buttons, zero shadows, generous whitespace.
Semantic colors live in the product surface (status pills, inline badges), not
in marketing chrome.

## 2. Color Tokens

```
--rui-dark:        #191c1f   (primary text, primary button)
--rui-white:       #ffffff   (surface)
--rui-surface:     #f4f4f4   (secondary surface, secondary button)
--rui-border:      #e5e5e5   (dividers, card borders)
--rui-muted:       #8d969e   (tertiary text)
--rui-slate:       #505a63   (secondary text)

--rui-blue:        #494fdf   (brand accent — use sparingly)
--rui-blue-link:   #376cd5   (links)
--rui-teal:        #00a87e   (success)
--rui-warning:     #ec7e00   (warning)
--rui-danger:      #e23b4a   (error)
--rui-deep-pink:   #e61e49   (critical accent)
--rui-yellow:      #b09000   (attention)
--rui-brown:       #936d62   (warm neutral)
```

## 3. Typography

- **Display:** Space Grotesk (weight 500). Free Aeonik-Pro stand-in from Google Fonts.
- **Body/UI:** Inter.
- **Fallback:** system-ui, -apple-system, sans-serif.

| Role          | Font           | Size         | Weight | Line-height | Tracking |
|---------------|----------------|--------------|--------|-------------|----------|
| Display Mega  | Space Grotesk  | 136px/8.5rem | 500    | 1.00        | -2.72px  |
| Display Hero  | Space Grotesk  | 80px/5rem    | 500    | 1.00        | -0.8px   |
| Section Head  | Space Grotesk  | 48px/3rem    | 500    | 1.21        | -0.48px  |
| Sub-heading   | Space Grotesk  | 40px/2.5rem  | 500    | 1.20        | -0.4px   |
| Card Title    | Space Grotesk  | 32px/2rem    | 500    | 1.19        | -0.32px  |
| Feature Title | Space Grotesk  | 24px/1.5rem  | 400    | 1.33        | normal   |
| Nav / UI      | Space Grotesk  | 20px/1.25rem | 500    | 1.40        | normal   |
| Body Large    | Inter          | 18px         | 400    | 1.56        | -0.09px  |
| Body          | Inter          | 16px         | 400    | 1.50        | 0.24px   |
| Body Emphasis | Inter          | 16px         | 600    | 1.50        | 0.16px   |
| Eyebrow       | Inter          | 12px         | 600    | 1.30        | 1.5px UPPER |
| Caption       | Inter          | 13px         | 400    | 1.50        | 0.1px    |

Principles:
- Weight 500 is the display default. Never bold display text.
- Authority through **size + negative tracking**, not weight/color.
- Body text gets **positive** tracking (+0.16 to +0.24px) for readability.

## 4. Components

**Buttons — always pill (radius: 9999px), padding 14px 32px, 20px Space Grotesk 500**
- Primary Dark: bg `#191c1f`, text `#fff`, hover opacity 0.85
- Secondary Light: bg `#f4f4f4`, text `#000`, hover opacity 0.85
- Outlined: transparent, 2px solid `#191c1f`, text `#191c1f`
- Ghost-on-dark: `rgba(244,244,244,0.1)`, 2px solid `#f4f4f4`, text `#f4f4f4`

**Cards**
- Surface `#fff`, border `1px solid #e5e5e5`, radius `20px`, no shadow.
- Compact variant: radius `12px`, padding `20px`.

**Nav**
- Radius `12px` on hover/active; no pills for side-nav links.

**Status pills** (product surface only)
- `4px 10px`, radius `9999px`, 12px Inter 600, tracking 0.4px UPPER.
- Neutral: bg `#f4f4f4`, text `#505a63`.
- Success/Warning/Danger: tinted bg at 10% opacity, text at full color.

## 5. Layout

- Base unit **8px**. Scale: 4, 6, 8, 14, 16, 20, 24, 32, 40, 48, 80, 88, 120.
- Section spacing: **80–120px**.
- Max content width: **1280px**.
- Card radius: **20px** (hero cards), **12px** (compact), **9999px** (pills).

## 6. Depth

- **Zero shadows.** Depth comes from dark/light section contrast + whitespace.
- Only exception: focus ring `0 0 0 0.125rem rgba(25,28,31,0.15)`.

## 7. Do / Don't

**Do**
- Use Space Grotesk 500 (not bold) for all display type.
- Pill every button, generous padding (14/32).
- Near-black + white dominate; semantic tokens only for status.
- Positive letter-spacing on Inter body.

**Don't**
- No shadows, no gradients, no emojis in chrome.
- No bold (700) headings.
- No small/cramped buttons.
- No multicolored dashboards — save semantic color for meaning.

## 8. Implementation notes

- Global theme is applied via `ui/theme.apply_theme()` once at the top of every
  Streamlit page. It injects CSS variables + component overrides.
- Sidebar is rendered via `ui/theme.sidebar()`. It reads the current page from
  the caller and highlights the active link.
- Helpers: `page_header(eyebrow, title, meta)`, `section_label(text)`,
  `stat_card(label, value, hint)`, `pill(text, tone)`, `empty_state(title, body)`.
- Any new chrome lives in `ui/theme.py`. Page files stay focused on data.
