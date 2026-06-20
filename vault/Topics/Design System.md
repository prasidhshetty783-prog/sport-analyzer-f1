---
title: Design System
type: topic
tags: [design, css, tokens, responsive, theme, branding]
updated: 2026-06-19
---

# Design System

> Tokens, themes, type, responsive rules, provenance tags. Back to [[Home]].

## Language (June 2026 restyle): premium motorsport
F1 racing-**red** accent on a **carbon** canvas (dark = the hero theme) + a crisp
**paddock-white** light theme. Rounded cards (radius 14–20px) with hairline-lit
edges + refined shadows, red CTA/play/active states, a red "timing-tower" tick on
the status bar, faint carbon-weave backdrop on dark.

## Shell layout — two pages (Phase 5)
Top-level **persistent tabs** (`features/shell/PageTabs.tsx`): **▦ Replay** and
**● Live**. `App.tsx` wraps the existing `.shell` grid in `.app-root`
(flex column) + `.app-body`; the tab strip sits above. `page` lives in
`raceStore`. On **Live** with nothing streaming, `LiveStandby.tsx` fills the body
(no-token vs waiting-for-a-race). `StatusBar` is page-aware: Replay shows the
Year→GP picker + scrub/speed; Live shows the circuit label + `● LIVE` / `+Ns`
delay + freeze-only. Live pulse reuses `@keyframes sb-live-pulse`. See
[[Phase 5 - Polish UX and Live Mode]].

## Tokens (`frontend/src/styles/tokens.css`) — **semantic vars only, no inline hex**
(team colours from data are the one exception.)
- Accent: `--color-accent` `#e10600` (light) / `#ff2630` (dark); `--color-cta`,
  `--color-accent-soft`, `--speed-line`.
- Surfaces/text per theme; `--shadow-card`, `--shadow-pop`, `--hairline-top`,
  `--ring-focus`; 8-pt spacing scale; radii.
- **Flag colours kept distinct from the brand red** (`--color-flag-red` ≠ accent)
  so a real red flag never reads as "just an accent".
- Dark theme under `[data-theme="dark"]` (status-bar toggle, persisted to
  localStorage); the canvas map + 3D scene re-read CSS vars on theme change.

## Type
**Archivo** (sans) + **JetBrains Mono** (timing), via Google Fonts `<link>` in
`index.html` (no font npm dep — the old `@fontsource/titillium-web` imports were
removed from `main.tsx`).

## Provenance tags (a core value — see [[About Me]])
Every data point is tagged **LIVE** (green) / **EST** (amber) / **AI** (violet).
Fuel = EST, tyre life / finish = AI. Show prediction freshness ("updated 12s ago").

## Responsive (`shell.css` + `App.tsx`/`StatusBar.tsx`/`Leaderboard.tsx`)
- Shell grid adapts; rail trims ≤1100px.
- **≤1100px:** leaderboard drops to a **compact 6-col grid** (hides LAST + PIT).
- **≤860px:** leaderboard becomes a **slide-in drawer** — `☰` (`.sb-nav`) toggles
  `shell[data-nav]`, tap-out `.shell-backdrop`, auto-closes on driver select.
- **≤540px:** Car Detail docks as a **bottom sheet**.
- **≤480px:** status bar wraps to two rows.
- 3D overlay panel/controls shrink to icon-only.

## Track Detail card
Follows the user's Singapore track-card reference: outline + sector/DRS highlights,
corner numbers, stat tiles (first GP, laps, length, distance, lap record + holder),
collapsible sections, elevation-profile strip. See [[Phase 4 - Track Detail and 3D]].

Related: [[Phase 5 - Polish UX and Live Mode]] · [[Phase 2 - Live Track Map]] · [[Architecture]]
