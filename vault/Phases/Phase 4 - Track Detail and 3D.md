---
title: Phase 4 - Track Detail and 3D
type: phase
phase: 4
status: done
tags: [phase, 3d, threejs, track-detail]
updated: 2026-06-18
---

# Phase 4 — Track Detail & 3D ✅

> Three.js circuit with elevation, terrain, water, tunnels, and a drone flyover. Back to [[Home]].

## Goal
A 3D circuit that recognizably matches the real track incl. elevation, plus a
Track Detail panel (live conditions, stats, past winners).

## What was built (`frontend/src/features/track-3d/`)
- `scene.ts` (`Scene3D`) + `Track3D.tsx` overlay; opened from the map's **Track info** button.
- **Elevation-aware track ribbon** from `asset.points` + `asset.elevation`
  (VEXAG 1.8 vertical exaggeration).
- **Heightfielded terrain** that follows the relief; **georeferenced CARTO ground
  texture** (reuses the 2D `assetToMerc` math from [[Phase 2 - Live Track Map]]).
- Instanced **trees/buildings** (buildings are **HEURISTIC** from tile colour, not
  real footprints), procedural F1 cars (optional `frontend/public/models/f1.glb`),
  3D corner sprites, elevation-profile strip.
- Backend: `track_outline.py` adds `elevation[]`; `GET /api/circuit/{id}` (computed
  laps/length/distance + records from `data/circuit_facts/<key>.json`);
  `scripts/fetch_circuit_facts.py` (host).

## Refinement pass (June 2026) — surroundings, tunnels, flyover
- **Terrain carve:** `heightField` carves a corridor so land never overlaps the
  ribbon and follows the **lower** deck at crossings.
- **Smooth water:** rebuilt as a blurred-alpha sheet over a carved basin
  (`buildWater`/`buildWaterPlane`, WGRID 200² + dilate + box-blur) — no more
  blocky shorelines; thin rivers become continuous ribbons. The **track corridor
  is zeroed out of the water field** so the road is never submerged
  (Monaco harbour-front + tunnel).
- **Tunnels:** `buildTunnels` detects self-crossings (XZ intersection + vertical
  gap, e.g. Suzuka) and builds an arched tunnel + portals over the lower road.
- **Flyover = free-fly drone:** WASD translate, **mouse ←→ yaw (right = right,
  after a sign fix)**, mouse ↑↓ altitude, via pointer lock (replaced an auto-glide).

## Still HEURISTIC / host-tunable (visual, can't verify in sandbox)
Building+desert classification from tile colour (e.g. Bahrain reads poorly),
water depth, tunnel arch height, drone speed, vertical exaggeration.

## Dependency
`three` + `@types/three` added to `frontend/package.json` (heavy dep — flagged &
approved). Run `npm install` in `frontend/`.

Related: [[Phase 2 - Live Track Map]] · [[Design System]] · [[Architecture]] · [[Environment Gotchas]] (3D isn't render-verifiable in sandbox)
