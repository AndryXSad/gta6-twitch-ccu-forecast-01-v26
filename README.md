# GTA VI launch-day Twitch CCU forecaster — v26

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/AndryXSad/gta6-twitch-ccu-forecast-01-v26/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/AndryXSad/gta6-twitch-ccu-forecast-01-v26/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A make.fun `gta6-twitch-ccu-forecast-01` entry. It forecasts, for each of
hours 2–24 of Grand Theft Auto VI's release day (2026-11-19 UTC), five
quantiles (5%, 25%, 50%, 75%, 95%) of the concurrent Twitch viewers in the
"Grand Theft Auto VI" category, from the first hour's print and the
launch-day curves of past big game launches shipped inside each case.

## How it works

`main.py` (Python 3.13, standard library only, no network) builds four
member predictors in log space from the 37 comparable past launches:

1. **Y5** — tier-filtered per-hour OLS on `[lnV1, g12]` blended
   (0.5/0.2/0.3) with console-only and all-launch one-factor shape views.
   `g12` is the "unlock momentum" feature: lnV1 minus log viewers 12 hours
   before release day.
2. **Z0** — the same construction with the naive early-access filter
   (launches whose notes contain "early access" are excluded).
3. **Y1** — the same construction, naive filter, features `[lnV1, lnPREM]`.
4. **Clone** — whole-library shape views, sample-sd spreads, and a
   weighted-mean blend (0.6 OLS / 0.2 console-shape / 0.2 all-shape) whose
   spread is 0.81× the weighted mean of the view spreads.

The **log-median is chosen per hour band** — the median is the bottleneck
(best median-only practice ever before this round was 0.192606):

| band | hours | median source | shift |
| ---- | ----- | ------------- | ----- |
| early | 2–6 | Y1 log-median | +0.00 |
| mid | 7–14 | half-blend 0.5·Y5 + 0.5·clone | ramp 0.00 → −0.07 |
| late | 15–24 | median of Y5 / Z0 / Y1 log-medians | ramp 0.00 → +0.05 |

On top of that, a **size-dependent shift**: the median runs high on big
launches, so above lnV1 11.5 the median is pulled down by 0.015 per log
unit of size, in every band. The final case (lnV1 ~ 14+) is the furthest
extrapolation in the file, so this is where the shift bites hardest.

The **log-spread** is 0.975× the 3-way weighted mean of the member spreads
(45% Y5 + 35% Z0 + 20% clone), widened by a **disagreement factor**
`1 + 0.5 * sd(member medians)` — when the four members disagree the truth
is further away — shaped per band with separate lower/upper scales:
early (0.90, 1.10), mid (1.10, 0.80), late (0.95, 0.85), and narrowed
across the late band (spread scale 0.975 → 0.90 from hour 15 to hour 24).
Quantiles are lognormal.

## Results

Direct-graded with the exact RULES scorer on the four practice cases
("Average viewers" answers): **practice pinball loss 0.122315**
(p00 0.1186 / p01 0.1372 / p02 0.0799 / p03 0.1535),
LOO-large **0.210202**, LOO-mega **0.212219**. That beats v25
(0.123530 / 0.210336 / 0.212309) on practice by −0.001215, with
LOO-large −0.000134 and LOO-mega −0.000090. Median-only practice is
**0.190202** (LOO-large 0.319157) — the median moved again, the
third round in a row (v25: 0.192606). See `DESIGN.md` for the full
reasoning record and the honest caveats. Not submitted: the owner's
rule is to submit only a candidate at practice ≤ 0.100.

## Run it

```sh
MAKEFUN_INPUT_DIR=<dir with *.in> MAKEFUN_OUTPUT_DIR=<dir> python3 main.py
```

Each `*.in` case produces a matching `*.out`:
`{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}]}` for h = 2..24.
