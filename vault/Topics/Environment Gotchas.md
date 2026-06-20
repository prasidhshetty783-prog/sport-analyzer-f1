---
title: Environment Gotchas
type: topic
tags: [gotchas, sandbox, mount, verification, debugging]
updated: 2026-06-18
---

# Environment Gotchas ⚠️

> The things that waste hours if forgotten. Read this when tooling "doesn't work".
> Back to [[Home]].

## 1. Sandbox blocks all F1 data domains
The Cowork/Claude sandbox egress-allowlist blocks `api.openf1.org`,
`api.jolpi.ca`, `livetiming.formula1.com`, `kaggle.com` (verified repeatedly).
**All data-fetching / training / model-download scripts run on the HOST.** In the
sandbox, test against the recorded fixtures or mocks. Commands: [[Commands and Run Guide]].

## 2. The synced mount serves STALE / TRUNCATED reads for just-edited files
- A file edited via the assistant's file tools reads **truncated at its old cached
  byte size** in `bash` (grep may find later tokens, but `cat`/`wc`/`cp` stop
  early); `ls -l` shows a pre-session mtime.
- **The Read file-tool is accurate; bash re-reads of edited files are not.**
- A **brand-new path** reads fresh.
- The mount also **lags host-side folder moves** — files the user adds/moves can
  take a while (or several retries) to appear; they may flicker in and out.

### Verification workflow (how we actually test edits)
1. Read the edited file with the Read tool (accurate) — or author fresh.
2. Write fresh copies to a **new path** (`.verify/`, or `/tmp` via heredoc).
3. Reconstruct the project in `/tmp` (unedited files copy fresh from the mount;
   overwrite edited ones with the fresh copies; symlink `node_modules` / `data`).
4. Run `tsc --noEmit` (frontend) or `python -m ml.backtest` / `py_compile` (backend).
- For TS, type-check changed files in isolation against the real store/types when
  the full graph is too heavy.
- `/tmp` can be recycled between calls — do build + run in **one** bash call.
- Sandbox **deletions** need `mcp__cowork__allow_cowork_file_delete`.
- Sandbox background processes **die when the bash call ends**; jobs must fit one
  call (≤45 s) — chunk long backtests or reduce `SA_SIMS`.

## 3. The circuit-key mismatch bug (recurring class)
Three different keyings exist and silently bypass each other if not reconciled:
- **OpenF1 `circuit_short_name`** (runtime key): `"Monte Carlo"`, `"Montreal"`,
  `"Spa-Francorchamps"`, `"Spielberg"` (lowercased at lookup).
- **Shipped `CIRCUITS` dict** in `priors.py`: `"monaco"`, `"monza"`… — many never
  matched the runtime key, so those hand-seeded priors were **bypassed**.
- **Ergast `circuitRef`** (Kaggle): `"monaco"`, `"villeneuve"`, `"spa"`,
  `"red_bull_ring"`, `"marina_bay"`…
**Fix pattern:** always key artifact priors by the **OpenF1 `circuit_short_name`**.
The SC-rate calibration and `ml/build_priors.py` crosswalk both do this now —
details in [[Calibration Log]].

## 4. 3D is not render-verifiable in the sandbox
Three.js can't render here — [[Phase 4 - Track Detail and 3D]] changes are verified
by `tsc` + logic review, not pixels. Visual tuning happens on the host.

Related: [[About Me]] · [[Commands and Run Guide]] · [[Calibration Log]] · [[Data Sources and Constraints]]
