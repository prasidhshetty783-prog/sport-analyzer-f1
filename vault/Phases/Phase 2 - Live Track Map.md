---
title: Phase 2 - Live Track Map
type: phase
phase: 2
status: done
tags: [phase, frontend, map, canvas]
updated: 2026-06-18
---

# Phase 2 — Live Track Map ✅

> 2D top-down circuit with cars gliding at 60 fps on a real-GPS outline. Back to [[Home]].

## Goal
Smooth 60 fps car motion during replay; selecting a car syncs map ↔ leaderboard.

## What was built (`frontend/src/features/track-map/`)
- **Track outline** derived from the fastest-lap GPS trace
  (`backend/ingest/track_outline.py` → `GET /api/track/{id}`).
- **Canvas renderer** at 60 fps: team-coloured markers with driver codes,
  **interpolated** between ~3.7 Hz position samples (`buffer.ts`), click-select
  synced to the leaderboard, start/finish line, sector ticks, corner numbers
  (if `scripts/fetch_circuit_info.py` was run on host).
- **Camera** (`engine.ts`): zoom 1–5, follow-cam on the selected driver
  (north-up), free drag-pan when none selected; parent-tile fallback so the map
  never blanks while panning.
- **Real-world tile underlay** (CARTO light/dark rasters, OSM data) when
  `data/circuit_geo/<key>.json` exists — fitted to the telemetry outline by
  `backend/ingest/georef.py` (Procrustes + circular shift; Canada residual ≈ 7 m).
  Fetch geometry per circuit (host): `scripts/fetch_circuit_geo.py --gp <name>`.
- Flag conditions tint the map; render clock is spring-smoothed.

## Interpolation rule
Buffer ~3–5 s of samples and interpolate so markers glide despite sparse input;
pause/scrub must not break interpolation. See `track-map/buffer.ts`.

## Acceptance
Smooth 60 fps during replay; click-to-select stays in sync everywhere.

## Imagery licensing
Google Maps tiles aren't licensable for this overlay; **OSM/CARTO are** (with the
attribution chip shown). Tile style follows the ☀/☾ theme.

Related: [[Architecture]] · [[Design System]] · [[Phase 4 - Track Detail and 3D]] (3D reuses this map's georef math) · [[Commands and Run Guide]]
