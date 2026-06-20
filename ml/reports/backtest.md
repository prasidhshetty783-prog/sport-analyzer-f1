# Backtest scorecard — F1 finish prediction

Finish-position prediction (Model B Monte-Carlo) vs. the actual
classification, evaluated mid-race on recorded fixtures. The
persistence baseline simply freezes the running order at lap *k*.

## FORMULA 1 ROLEX AUSTRALIAN GRAND PRIX 2023  (2023_australia_race, 59 laps)

| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |
|---:|---:|:--:|---:|---:|---:|:--:|---:|
| 0.30 | 18 | GREEN | 20 | 4.7 | 3.2 | 3/3 | 0.389 |
| 0.50 | 30 | GREEN | 20 | 4.6 | 2.5 | 2/3 | 0.402 |
| 0.70 | 41 | GREEN | 20 | 5.1 | 2.6 | 1/3 | 0.251 |

**Summary:** mean MAE 4.8 (trails persistence 2.767); top-3 hit rate 0.667.

## FORMULA 1 GULF AIR BAHRAIN GRAND PRIX 2023  (2023_bahrain_race, 57 laps)

| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |
|---:|---:|:--:|---:|---:|---:|:--:|---:|
| 0.30 | 17 | GREEN | 20 | 3.7 | 2.2 | 2/3 | 0.633 |
| 0.50 | 28 | GREEN | 20 | 2.9 | 2.5 | 2/3 | 0.675 |
| 0.70 | 40 | GREEN | 20 | 2.3 | 1.7 | 3/3 | 0.762 |

**Summary:** mean MAE 2.967 (trails persistence 2.133); top-3 hit rate 0.778.

## FORMULA 1 ROLEX GRANDE PRÊMIO DE SÃO PAULO 2023  (2023_brazil_race, 71 laps)

| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |
|---:|---:|:--:|---:|---:|---:|:--:|---:|
| 0.30 | 21 | GREEN | 20 | 4.1 | 1.55 | 3/3 | 0.502 |
| 0.50 | 36 | GREEN | 20 | 4.0 | 1.65 | 2/3 | 0.48 |
| 0.70 | 50 | GREEN | 20 | 4.7 | 1.15 | 1/3 | 0.329 |

**Summary:** mean MAE 4.267 (trails persistence 1.45); top-3 hit rate 0.667.

## FORMULA 1 PIRELLI GRAN PREMIO D’ITALIA 2023  (2023_italy_monza_race, 52 laps)

| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |
|---:|---:|:--:|---:|---:|---:|:--:|---:|
| 0.30 | 16 | GREEN | 20 | 2.0 | 1.9 | 2/3 | 0.872 |
| 0.50 | 26 | GREEN | 20 | 1.5 | 1.2 | 2/3 | 0.934 |
| 0.70 | 36 | GREEN | 20 | 1.5 | 1.9 | 3/3 | 0.928 |

**Summary:** mean MAE 1.667 (beats persistence 1.667); top-3 hit rate 0.778.

## FORMULA 1 GRAND PRIX DE MONACO 2023  (2023_monaco_race, 79 laps)

| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |
|---:|---:|:--:|---:|---:|---:|:--:|---:|
| 0.30 | 24 | GREEN | 20 | 2.0 | 2.0 | 3/3 | 0.877 |
| 0.50 | 40 | GREEN | 20 | 2.5 | 2.4 | 1/3 | 0.838 |
| 0.70 | 55 | GREEN | 20 | 1.9 | 2.3 | 2/3 | 0.916 |

**Summary:** mean MAE 2.133 (beats persistence 2.233); top-3 hit rate 0.667.

## FORMULA 1 AWS GRAND PRIX DU CANADA 2024  (2024_canada_race, 70 laps)

| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |
|---:|---:|:--:|---:|---:|---:|:--:|---:|
| 0.30 | 21 | GREEN | 20 | 3.1 | 3.2 | 3/3 | 0.749 |
| 0.50 | 35 | GREEN | 20 | 2.2 | 2.3 | 3/3 | 0.814 |
| 0.70 | 49 | GREEN | 20 | 2.8 | 2.6 | 3/3 | 0.806 |

**Summary:** mean MAE 2.7 (beats persistence 2.7); top-3 hit rate 1.0.

## Overall (all fixtures)

| fixtures | mean MAE model | mean MAE persistence | top-3 hit rate |
|---:|---:|---:|---:|
| 6 | 3.089 | 2.158 | 0.76 |

**Across 6 races the simulator trails the persistence baseline** (3.089 vs 2.158).

> Add more fixtures (especially a clean race and a chaotic one) to
> tighten these estimates and to calibrate the SC hazard (Model C).