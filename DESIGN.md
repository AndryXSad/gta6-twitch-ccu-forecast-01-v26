# DESIGN.md — gta6-twitch-ccu-forecast-01 v26

## Verdict

READY-BETTER: practice **0.122315** (p00 0.1186 / p01 0.1372 /
p02 0.0799 / p03 0.1535), LOO-large **0.210202**, LOO-mega
**0.212219** — beats v25 (0.123530 / 0.210336 / 0.212309) on all
three numbers. Median-only practice **0.190202** (LOO-large
0.319157) — the median moved for the third round in a row
(v25: 0.192606, v24: 0.194455). Packaged as the new verified
fallback; NOT submitted (owner's rule: only a candidate at
practice ≤ 0.100 gets submitted).

## The packaged cell

Median source per band: early = Y1, mid = 0.5·Y5 + 0.5·clone,
late = median(Y5, Z0, Y1); mid ramp (0.00 → −0.07), late ramp
(0.00 → +0.05); size shift −0.015 · max(0, lnV1 − 11.5), all
bands; spread 0.975 · (0.45·sig(Y5) + 0.35·sig(Z0) +
0.20·sig(clone)), disagreement factor 1 + 0.5·sd(member
medians), per-band asymmetric scales early (0.90, 1.10),
mid (1.10, 0.80), late (0.95, 0.85), late spread ramp
0.975 → 0.90 across hours 15–24.

Robust alternate (same construction, k = 0.6, mid ramp −0.06):
0.122574 / 0.210007 / 0.211979 — LOO-large margin −0.000329
and mega margin −0.000330, for +0.000259 of practice. If the
LOO margin matters more than 0.000259 of practice, package
that one instead.

## What changed vs v25

Two genuinely new levers, both found this round:

1. **Disagreement-indexed spread.** The spread is widened by
   `1 + 0.5 * sd` of the four member log-medians, in every band.
   When the members disagree the truth is further away. On its
   own (k = 0.5, v25 base) it buys LOO-large −0.00087 at a
   practice cost of +0.00035 — a LOO-buyer, not a practice
   lever. Its value is as the counterweight to lever 2.
2. **Late-band spread ramp.** The spread scale interpolates
   0.975 → 0.90 across hours 15–24. The launch-day curve
   flattens late, so the late spread should narrow with the
   hour. On its own it buys practice −0.0006 at a LOO cost of
   +0.00075. Combined with lever 1 the two cancel on LOO and
   net −0.00037 of practice (round 4: 0.123020).
3. **The mid ramp keeps paying.** Steepening the mid ramp from
   −0.025 (v25) to −0.07 bought ~−0.0001 of practice per −0.005
   of ramp for seven consecutive steps, with LOO-large flat
   (~0.21016–0.21020) the whole way. The half-blend median runs
   high late in the mid band — the ramp corrects a within-band
   slope, not a level. The trend had NOT flattened at −0.07;
   it was stopped deliberately (see caveat).

## What died this round

- **Quantile tilt** (per-band additive log-shift on the lower
  quantiles only / upper only): tilt (+0.02, −0.02) all bands
  gives practice 0.122206 — the best practice seen in any
  round — but LOO-large 0.212789. It is spread-shrink in
  disguise, not an independent lever; the practice/LOO trade
  slope is the same as base-scale tuning.
- **Median source changes** (med4 in any band, per-hour median
  source in the early/mid band, band-0 source z0, band-2
  source y1): all fail LOO badly (0.2109–0.2136). The v25
  median sources are a local optimum.
- **Per-band lnv1 slopes** and **per-band base scales**: no
  overlap beyond what the global versions already give.
- **Size-indexed spread** (`sig *= 1 + s·max(0, lnv1−11.5)`):
  buys LOO, costs practice — same trade as everything else.

## The practice/LOO trade, restated

Every lever tried in 26 rounds trades practice for LOO or
vice versa at roughly the same exchange rate (~0.0002 practice
per ~0.0004 LOO). The only way to move both at once is a
combination whose two halves cancel on one gate and add on
the other — this round's ramp + disagreement pairing. The
corner keeps moving in ~0.001 steps per round, not leaps.

## Honest caveat (read before trusting the number)

The band parameters (ramps, slope, pivot, base scale, k, ramp
endpoint) were chosen on LOO-large AND on practice across
seven rounds of selection, so NEITHER gate is a clean holdout
for the packaged cell. The LOO-large margin (−0.000134) and
mega margin (−0.000090) are thin and optimistically biased by
selection. Two specific warnings:

- The mid ramp was still improving linearly at −0.07 with no
  sign of flattening, and the steeper cells (−0.08:
  0.122156 / 0.210238 / 0.212299) pass only because the mega
  margin there is −0.000010 — essentially zero. The −0.07
  cell was chosen over −0.08 precisely because its margins
  are still real. Chasing the ramp further is fitting the
  four practice cases, not learning the final launch.
- Per-case, the steeper mid ramp helps p02/p03 (the big
  launches) and hurts p01 monotonically (0.1364 at −0.06 →
  0.1381 at −0.08). p01 is the practice case closest in size
  to a typical LOO-large launch, so the ramp's benefit is
  concentrated exactly where the final case is NOT typical.

The neighbourhood holds together (11 of 11 round-6 cells and
6 of 6 round-7 cells pass the v25 gates; all direct-graded
variants beat v25 on practice), and the per-case gains are
broad rather than one-case luck — but the final is a new
launch in a new regime (lnV1 ≈ 14+, beyond the library max
13.68), and practice is only 4 launches. Treat this as the
best verified fallback, not a guarantee.

## Why 0.100 still held (twenty-sixth round)

The median moved again — 0.1926 → 0.1902 practice, 0.3200 →
0.3192 LOO-large — but the gap to 0.100 is still ~0.090 of
median loss, and per-hour OLS residual sd is still 0.35–0.45
log. No median family remains unbuilt or unmeasured after 26
rounds except ideas that need data the case file does not have
(final-only streams/categories, which cannot be validated).
