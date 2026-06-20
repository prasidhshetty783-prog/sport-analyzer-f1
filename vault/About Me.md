---
title: About Me
type: profile
tags: [user, preferences, working-agreement]
updated: 2026-06-18
---

# About Me & How to Work With Me

> Open this first in any new session — it sets tone, environment, and the rules
> for changing things. Back to [[Home]].

## Who
- **SPICY** — owner/developer of [[Home|Sport Analyzer]], building it as a portfolio-grade
  real-time F1 intelligence app.
- Works on a **Windows host**; project root `D:\Claude Code Projects\Sports Analyzer`.
- Uses Claude in **Cowork mode** (file tools + a sandboxed Linux shell). Maintains
  this Obsidian vault as a context store to save tokens.

## Response preferences
- **Be concise and direct.** Cut filler; if a word can be removed without losing
  meaning, remove it. No purple prose, no over-explaining.
- Prefers seeing the **outcome + the honest read**, not a play-by-play.
- Values **honesty over hype** — if a metric didn't move (e.g. MAE stayed flat),
  say so plainly and explain why, rather than dressing it up. (See the candid
  entries in [[Calibration Log]].)

## Working agreement (rules for changing the project)
- **State assumptions and proceed** on small decisions instead of asking.
- **Stop and ask first** before: paid services, new heavy dependencies, or
  **WS protocol schema changes** (`backend/api/schema.py` — see [[Architecture]]).
- Commits scoped per phase.
- **Honest data labelling is a core value:** every UI field is tagged
  **LIVE / EST / AI**; computed/approximate values must never look like telemetry.
  (Details in [[Design System]] and [[Prediction Models]].)
- No F1/team logos, no official fonts, **no betting features**.

## Environment reality (so we don't waste effort)
- The Cowork **sandbox blocks all F1 data domains** and the host mount can serve
  **stale/truncated reads** for just-edited files. This bites repeatedly — the
  full playbook is in [[Environment Gotchas]]. Data fetching/training is
  **host-only**; the assistant verifies via reconstructed copies.

## Current focus
- Phase 5: **live mode is the remaining build** (gated behind `OPENF1_TOKEN`).
  Model calibration + UI polish are done — see [[Phase 5 - Polish UX and Live Mode]]
  and [[Calibration Log]].

Related: [[Home]] · [[Environment Gotchas]] · [[Commands and Run Guide]]
