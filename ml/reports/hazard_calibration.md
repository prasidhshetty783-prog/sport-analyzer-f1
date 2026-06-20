# Safety-car hazard calibration (Model C)

Fit from 76 recorded fixtures' `race_control` (in-sandbox, no external data).

- Global P(>=1 SC) **0.487**; per-lap multipliers lap-1 **x8.0**, rain **x1.25**, mean-scale **x0.711**

## SC-within-10-laps calibration

- observed **0.075** vs mean predicted **0.077** (mean-calibrated)
- Brier **0.0681** vs no-skill baseline **0.0696**  →  skill **+2.3%**

| pred bin | n | mean pred | observed |
|---|---:|---:|---:|
| 0.0–0.1 | 3519 | 0.066 | 0.061 |
| 0.1–0.2 | 929 | 0.117 | 0.129 |

## Shrunk per-circuit P(>=1 SC) — empirical-Bayes (K=6)

| circuit | P(>=1 SC) | raw |
|---|---:|---:|
| interlagos | 0.658 | 3/3 |
| lusail | 0.658 | 3/3 |
| jeddah | 0.658 | 3/3 |
| montreal | 0.592 | 3/4 |
| spielberg | 0.547 | 2/3 |
| baku | 0.547 | 2/3 |
| mexico city | 0.547 | 2/3 |
| zandvoort | 0.547 | 2/3 |
| silverstone | 0.547 | 2/3 |
| shanghai | 0.547 | 2/3 |
| melbourne | 0.492 | 2/4 |
| suzuka | 0.492 | 2/4 |
| miami | 0.492 | 2/4 |
| imola | 0.490 | 1/2 |
| sakhir | 0.436 | 1/3 |
| singapore | 0.436 | 1/3 |
| catalunya | 0.436 | 1/3 |
| austin | 0.436 | 1/3 |
| las vegas | 0.436 | 1/3 |
| monte carlo | 0.392 | 1/4 |
| spa-francorchamps | 0.325 | 0/3 |
| hungaroring | 0.325 | 0/3 |
| monza | 0.325 | 0/3 |
| yas marina circuit | 0.325 | 0/3 |