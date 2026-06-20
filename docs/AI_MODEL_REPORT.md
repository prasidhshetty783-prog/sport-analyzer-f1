# Sport Analyzer — AI Models & Design Decisions

A plain-language report on **what** the prediction engine does, **which
algorithms** it uses and **why**, **what data** it learned from, **how accurate**
it is (and how to make it better), and the **status of live mode**. Written so a
curious non-specialist can follow it, with the real numbers included.

> One-line summary: the app predicts tyre life, safety-car risk, fuel, and final
> finishing positions during a race. It does this with a mix of small,
> interpretable models (gradient-boosted trees + a physics estimate) and a
> **Monte-Carlo race simulation**, deliberately chosen over big black-box models
> because the data is structured, modest in size, and the predictions must react
> live to events like safety cars.

---

## 1. What we are predicting

| Output | Type | Shown in UI as | Model |
|---|---|---|---|
| Tyre degradation rate + "laps to the cliff" | number | **AI** | Model A (tyre) |
| Final finishing position + P(win/podium/points) | distribution | **AI** | Model B (Monte-Carlo) |
| Safety-car likelihood | probability | **AI** | Model C (hazard) |
| Fuel remaining (kg + laps) | number | **EST** | Fuel estimator (physics) |

Everything is tagged **LIVE** (measured), **EST** (estimated) or **AI** (model
output) in the interface, so a prediction is never passed off as real telemetry.

---

## 2. The models, and why each algorithm was chosen

### Model A — Tyre degradation (`backend/models/tire.py`)
**Algorithm:** per-compound physical priors (each tyre has a `pace`, `deg` rate,
and a `cliff` lap where it falls off) **plus distilled gradient-boosted-tree
(GBT) coefficients** learned offline from real stint data, with corrections for
fuel load, track/air temperature, rain and dirty air.

**Why this:** tyre wear is non-linear (it's gentle, then there's a "cliff"), and
it depends on interacting factors (compound × temperature × fuel). Gradient-
boosted trees (XGBoost / LightGBM) are excellent at exactly this: non-linear,
interacting, **tabular** data. We train them offline, then "distill" them into a
handful of lightweight coefficients that run in-process — no model server, no
GPU, instant predictions.

### Model B — Finishing position (`backend/models/montecarlo.py`)
**Algorithm:** a **Monte-Carlo simulation** — it plays the rest of the race
forward ~1,000–2,000 times with a bit of random noise each lap, then reads off
how often each driver finishes in each position. Vectorised in NumPy so all
~2,000 simulations run in roughly a quarter of a second.

**Why a simulation and not a single "predict the finish" model:** a normal
regression or classifier outputs one guess and can't react to *events*. But an F1
result is decided by discrete shocks — a safety car bunching the field, a pit
stop, a retirement. Simulating the race lets those events actually happen in the
model (safety cars are drawn from Model C, retirements from a data-driven DNF
rate, pace from Model A). It also gives a **full probability distribution**
(P(win), P(podium), P(points)) instead of a single number — which is the honest
way to talk about an uncertain future.

### Model C — Safety-car hazard (`backend/models/hazard.py`)
**Algorithm:** a per-circuit probability of "at least one safety car"
(`P(≥1 SC)`), smoothed with **empirical-Bayes shrinkage**, converted to a
per-lap risk and multiplied by simple, data-fit factors (lap 1 is ×8 riskier,
rain ×1.25, recent incidents raise it), then mean-calibrated.

**Why this and not a big ML model:** there are only a handful of races per
circuit, so safety cars are **rare events with tiny samples**. A flexible model
would memorise noise (overfit). Empirical-Bayes shrinkage is the textbook
small-data answer: trust a circuit's own history a little, and "shrink" the rest
of the way toward the global average. That gives stable, believable numbers.

### Fuel — deterministic estimate (`backend/models/fuel.py`)
**Algorithm:** physics, not ML. `fuel = start_load − Σ(burn per lap)`, starting
at ≤110 kg with a per-circuit burn rate (~1.2–1.9 kg/lap, reduced ~35% under a
safety car).

**Why not ML:** F1 doesn't broadcast fuel load, but the burn relationship is
well understood. A transparent formula you can audit beats a black box here — and
we label it **EST** so nobody mistakes it for a real reading.

---

## 3. Why gradient-boosted trees (and not "trendier" algorithms)

This was a deliberate choice, not a default. The data is **tabular** (rows of
numbers: tyre age, temperature, gaps, lap times) and **modest in size**
(thousands of stint rows, dozens of races). For that profile:

- **vs Deep learning / neural networks** — neural nets shine on images, audio and
  text with millions of examples. On tabular data of this size they typically
  **lose to gradient-boosted trees**, need far more data to avoid overfitting,
  and add GPU/serving complexity for no accuracy gain. Wrong tool here.
- **vs plain linear / logistic regression** — too simple. It can't capture the
  tyre "cliff" or temperature interactions without heavy manual feature
  engineering. (We *do* use a simple logistic-style form for the few safety-car
  multipliers, where a straight-line effect is appropriate.)
- **vs a Large Language Model** — an LLM is a language tool; this is numeric,
  structured prediction. An LLM would be slower, costlier, non-deterministic, and
  worse at the actual maths.
- **vs one end-to-end finish classifier** — can't react to live events or give
  calibrated probabilities, which is the whole point. That's why finishing
  position is a **simulation**, not a classifier.

The serving trick worth highlighting: models are **trained offline** with
XGBoost/LightGBM, then **distilled** into compact coefficients/priors
(`models/artifacts/priors.json`). The running app therefore needs no heavy
dependency, no GPU, and starts instantly. If the trained file is absent, it falls
back to principled built-in priors, so the app always works.

---

## 4. What data we trained and tested on, and which years

F1's usable data is split by what each source actually contains:

| Source | Years | Used for |
|---|---|---|
| **OpenF1** (GPS + telemetry) | **2023 → present** | Replay + live. This is the **only** era with car GPS, so it's the only era we can replay or run live. |
| **FastF1** (deep telemetry) | 2018 → | Training data for the tyre model (stint-level features). |
| **Jolpica / Ergast** (results) | 1950 → | Track Detail (winners, lap records). |
| **Kaggle results dump** | 1950 → 2024 | Long-history priors. |

Concretely:

- **Replay/test set:** ~**76 recorded races** from **2023–2024** (the GPS era).
  The finish-prediction scorecard runs on **70 of these fixtures**.
- **Tyre model training:** FastF1 stint data from **2018 onward**.
- **Long-history priors (from Kaggle):** overtaking difficulty per circuit from
  **2014+**, pit-loss times from **2018+**, and a global DNF (did-not-finish)
  rate of **0.171** computed from **2014+** races.
- **Safety-car calibration:** fit in-house from the 76 fixtures' race-control
  messages (4,448 lap-level data points).

Why 2014 as a frequent cut-off for priors: F1 entered the current "hybrid" era in
2014, so racing characteristics (overtaking difficulty, reliability) from before
then are less representative of today's cars.

---

## 5. How accurate is it — and why the error isn't actually "high"

### The headline numbers (finishing-position prediction)
Measured mid-race against the real result, and compared to a **persistence
baseline** ("just assume the current running order holds"):

- **Mean error (MAE) ≈ 1.9 positions** after calibration on stable 2023–24 races
  — i.e. a car's predicted finish is on average within ~2 places of reality.
- The **persistence baseline ≈ 1.8 positions** — so the model is roughly *level*
  with it on calm races.
- **Top-3 hit rate ≈ 0.75** — about three of every four podium calls are right
  mid-race.
- **Safety-car model: +2.3% skill** over a no-skill baseline (Brier 0.0681 vs
  0.0696), and well-calibrated: when it predicts ~12%, ~13% actually occur.

### Why this is a *good* result, not a bad one
The number that surprises people is "the model only ties the baseline." Here's
the honest explanation:

> **In F1, position is sticky.** Overtaking is hard, so "whoever is P3 now will
> probably finish near P3" is already a *very* strong guess. That baseline is the
> high bar. Matching it on a clean race is expected; the model's real value is in
> the **chaotic** races and in giving **calibrated probabilities** (it can say
> "32% chance of a podium"), which a baseline simply cannot do.

On chaotic races (e.g. 2023 Australia/Brazil, full of incidents) the mid-race
error is genuinely larger (MAE 4–5 early on) — because the outcome is genuinely
more uncertain. That's the model being honest, not broken.

### How to reduce the error (in priority order)
1. **Train/test on more chaotic races** — rain, red flags, multi-safety-car
   races. The model's edge is in chaos, so the evaluation set needs more of it.
   (Right now most fixtures are "sticky" races where the baseline is unbeatable.)
2. **Per-team / per-driver reliability** — today there's a single global DNF rate
   (0.171). Splitting it by team and driver would sharpen who is at risk.
3. **Probability calibration** on P(win)/P(podium) — make the headline
   percentages provably match observed frequencies.
4. **A richer pace model** — add driver skill and car-at-this-circuit
   performance, so the simulation's per-lap pace is more realistic.
5. **A smarter pit-strategy model** — the current pit logic is simple; real
   strategy (undercut/overcut) moves finishing order a lot.
6. **More telemetry features** for the tyre model (brake/throttle stress, track
   evolution) where available.

Note: the answer is **not** "just feed it more data volume." The levers above are
about modelling the *right* things, not adding more of the same calm races.

---

## 6. Have we implemented live races? (Yes — with one real catch)

**Yes.** Live mode is built (Phase 5). An authenticated OpenF1 poller reads the
real-time feed, converts it into the same internal events the replay system uses,
and drives the exact same track map, leaderboard and predictions. It shows an
honest **"broadcast +N seconds"** delay (live timing is always a few seconds
behind the TV feed) and handles reconnects and "no race is live right now"
gracefully.

**The catch — API cost.** OpenF1's *historical* data is free, but its
**real-time feed requires a paid token/subscription**. So:

- Live mode is **gated behind an `OPENF1_TOKEN`**. With no token the app stays
  fully usable in **Replay** mode — nothing breaks, you just don't get live.
- Running live during race weekends therefore has an **ongoing subscription
  cost**, which is why it's opt-in rather than always-on.
- A lower-latency transport (MQTT/WebSocket streaming, also paid) is scaffolded
  as a documented next step; today's live path uses REST polling.
- Practical note: live can only be truly exercised during an actual session with
  a valid token, so in development it's verified with mocked feeds and by
  **replaying a recorded race as if it were live** (which reproduces the correct
  podium).

---

## 7. FAQ — other questions people are likely to ask

**Is it "real time"?**
Broadcast-real-time, not instant. Live timing data lands a few seconds behind the
world feed; the UI shows the exact delay. We never claim millisecond accuracy.

**Is the fuel reading real?**
No — F1 doesn't broadcast fuel. It's a physics **estimate**, labelled **EST**.

**Does it use official F1 data or APIs?**
No. There is no official public F1 API. Everything comes from community sources
(OpenF1, FastF1, Jolpica/Ergast, a public Kaggle dataset). It's an unofficial,
fan/educational project — no F1/team logos, fonts, or betting features.

**Can it predict the winner *before* the race starts?**
It's designed for **in-race** prediction (it uses the live order, tyres and
gaps). A pure pre-race grid-only forecast is a different, harder problem and
isn't the goal here.

**Why not just use a neural network / deep learning?**
Because the data is tabular and modest in size, where gradient-boosted trees
generally beat neural nets, train in seconds on a CPU, and don't overfit as
easily. See Section 3.

**Why does the finish model "only tie" the baseline?**
Because in F1 the current running order is already a great predictor (overtaking
is hard). The model's value is in chaotic races and in calibrated probabilities,
not in beating a strong baseline on calm races. See Section 5.

**Does it need a GPU or a big server?**
No. Models are distilled to lightweight coefficients and served in-process; the
Monte-Carlo simulation is plain NumPy. A normal laptop runs everything.

**Does it handle rain, red flags and safety cars?**
Yes — those are first-class inputs. Safety cars are modelled explicitly (Model C)
and feed the finish simulation; rain affects tyre and safety-car risk.

**What years / circuits work?**
Replay and live need GPS, so **2023 onward** (OpenF1). Training/priors reach
further back (2018 for telemetry, 1950/2014 for results-level history). Pre-2023
races can't be replayed.

**How do you avoid overfitting / cheating the score?**
Predictions are made from the race state **as it was at lap _k_**, then compared
to the *actual* final result — no peeking ahead. Safety-car rates are shrunk
toward the global average so small per-circuit samples don't dominate. The
honest read in the calibration notes deliberately resists "tuning to the test
set."

**Is this gambling/betting?**
No. There are no odds-for-money or betting features, by design.

**Can I trust the probabilities?**
The safety-car probabilities are calibrated (predicted ≈ observed). The finish
probabilities are reasonable but not yet formally calibrated — that's an
explicit next step (Section 5, item 3).

---

## 8. Where to read more in the repo
- `backend/models/` — the served models (tyre, montecarlo, hazard, fuel, predictor).
- `ml/` — offline training + the backtest that produces the scorecards.
- `ml/reports/backtest.md` and `ml/reports/hazard_calibration.md` — the raw,
  per-race numbers.
- `vault/Topics/Prediction Models.md` and `vault/Topics/Calibration Log.md` — the
  full mechanics and the complete tuning history with honest numbers.
