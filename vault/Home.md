---
title: Home
type: index
tags: [moc, index, sport-analyzer]
updated: 2026-06-19
---

# 🏎️ Sport Analyzer — Project Vault

**Map of Content.** This vault is the project's "second brain". It's organized so
an assistant (or a returning human) can open **one relevant note** instead of
re-reading every source file — saving context and tokens. Everything is linked
with `[[wikilinks]]`; follow them.

> One-liner: a real-time **F1 race dashboard** — replays recorded races through an
> event bus with a live 2D track map, per-car telemetry, ML predictions (tyre
> life, fuel, pit window, finish), and a 3D Track Detail view. Python/FastAPI +
> React/TS/Three.js. No DB; in-memory state + Parquet/JSON caches.
> Working dir: `D:\Claude Code Projects\Sports Analyzer`.

---

## 🧭 How to use this vault (read me first)

Open the note that matches your task — don't load everything:

| If you need… | Open |
|---|---|
| Who the user is, how to work with them, the working agreement | [[About Me]] |
| What was built in a given phase | the matching `[[Phase N …]]` note below |
| The system layout, modules, WS protocol | [[Architecture]] |
| Where F1 data comes from + the hard rules | [[Data Sources and Constraints]] |
| **Why a script "works on host but not here", stale reads, etc.** | [[Environment Gotchas]] ⚠️ start here when debugging tooling |
| How the tyre / Monte-Carlo / hazard / fuel models work | [[Prediction Models]] |
| The exact model-tuning history + backtest numbers | [[Calibration Log]] |
| Colours, fonts, responsive rules, the F1 restyle | [[Design System]] |
| How to run, test, and (host-only) fetch/train | [[Commands and Run Guide]] |
| What a term means (LIVE/EST/AI, fixture, cliff, …) | [[Glossary]] |

**Conventions for editing this vault:** primary structure is **Phases**; each
phase note holds its own content under headers/subheaders and links out to the
relevant `[[Topic]]`. Keep notes focused and link rather than duplicate.

---

## 📦 Phases (primary structure)

| Phase | Note | Status |
|---|---|---|
| 0 | [[Phase 0 - Data Access Spike]] | ✅ done |
| 1 | [[Phase 1 - Replay and Leaderboard]] | ✅ done |
| 2 | [[Phase 2 - Live Track Map]] | ✅ done |
| 3 | [[Phase 3 - Prediction Engine and Car Panel]] | ✅ done |
| 4 | [[Phase 4 - Track Detail and 3D]] | ✅ done |
| 5 | [[Phase 5 - Polish UX and Live Mode]] | ✅ done (incl. live mode) |

---

## 🧩 Topics (cross-cutting)

- [[Architecture]] — modules, event bus, WS protocol, repo layout
- [[Data Sources and Constraints]] — OpenF1 / FastF1 / Jolpica / Kaggle + the 6 hard rules
- [[Environment Gotchas]] — sandbox egress block, stale mount, circuit-key mismatch ⚠️
- [[Prediction Models]] — Model A (tyre), B (Monte-Carlo finish), C (SC hazard), fuel
- [[Calibration Log]] — every tuning pass + backtest numbers (Model B, C, Kaggle priors)
- [[Design System]] — F1-red + carbon tokens, Archivo, responsive, LIVE/EST/AI tags
- [[Commands and Run Guide]] — dev/test commands; host-only data/training steps
- [[Glossary]]

---

## ⛔ Hard constraints (never silently violate) — full text in [[Data Sources and Constraints]]

1. No official F1 API; sources are community (OpenF1 2023→, FastF1, Jolpica).
2. Live needs a **paid `OPENF1_TOKEN`**; app must degrade to replay-only without it.
3. Every UI field tagged **LIVE / EST / AI** — never present a model output as telemetry.
4. **Replay is first-class** — recorded fixtures re-emit through the same event bus as live.
5. No F1/team logos or official fonts; team colours come from data. **No betting.**

## 📄 Source docs (originals this vault was distilled from)
`BUILD_PROMPT.md` (full spec) · `CLAUDE.md` (working summary) ·
`CONVERSATION_SUMMARY.md` (session handoff) · `RUN_GUIDE.md` · `README.md`
