"""Forecast GTA VI's launch-day Twitch viewers hour by hour.

Entry for make.fun competition gta6-twitch-ccu-forecast-01 (v26).
Python 3.13, standard library only. No network access.

Method (see DESIGN.md for the reasoning record):
  The forecast starts from four member predictors built from the
  37 comparable past launches in the case file:
    - Y5: a v4-family member (tier EA filter, shape features
      [lnV1, g12], mix 0.5 OLS / 0.2 console-shape / 0.3 all-shape)
    - Z0: the same family with the naive 'early access' filter
    - Y1: the same family, naive filter, features [lnV1, lnPREM]
    - clone: the v9 black-box reconstruction of the v2 baseline
      (whole-library shape pools, sample sd, mix 0.6/0.2/0.2,
      spread x 0.81)
  The LOG-MEDIAN is chosen per hour band from a different source
  in each band -- the median is the bottleneck (best median-only
  practice ever is 0.1975; v26 moves it to 0.1906):
    hours 2-6:   Y1's log-median
    hours 7-14:  half-blend 0.5 * Y5 + 0.5 * clone, with a
      per-hour offset ramp 0.00 -> -0.07 across the band
    hours 15-24: median of the Y5 / Z0 / Y1 log-medians, with a
      per-hour offset ramp 0.00 -> +0.05 across the band
  and then shifted in every band by a size-dependent correction
  -0.015 * max(0, lnV1 - 11.5): the median runs high on big
  launches, and the final case (lnV1 ~ 14+) is the biggest of all.
  The LOG-SPREAD is the 3-way weighted mean of the member spreads
  (45% Y5 + 35% Z0 + 20% clone) at base scale 0.975, widened by a
  disagreement factor 1 + 0.5 * sd(member medians) -- when the
  members disagree the truth is further away -- shaped per band
  with separate lower/upper scales, and narrowed across the late
  band (spread scale 0.975 -> 0.90 from hour 15 to hour 24).
  Quantiles are lognormal: q = exp(mu + z * sig) with the usual
  normal z-scores; the median is spread-free.

  Features: lnV1 = log hour-1 viewers; lnPREM = log MEAN viewers
  in the 7 days before release day; g12 = lnV1 - log viewers at
  the point nearest 12h before release (within 3h), with a
  library-median fallback (upper median) when missing.

Usage: the harness sets MAKEFUN_INPUT_DIR / MAKEFUN_OUTPUT_DIR.
Every *.in file in the input dir is forecast and a matching *.out
file is written: {"hours": [{"hour": h, "q": [q05..q95]}]} for
hours 2..24.
"""

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

TAUS = (0.05, 0.25, 0.5, 0.75, 0.95)
ZS = (-1.6448536269514722, -0.6744897501960817, 0.0,
      0.6744897501960817, 1.6448536269514722)
HOURS = tuple(range(2, 25))

BLEND_W = (0.45, 0.35, 0.20)          # Y5, Z0, clone (spread only)
BASE_SCALE = 0.975
BAND_SCALES = ((0.90, 1.10),          # hours 2-6
               (1.10, 0.80),          # hours 7-14
               (0.95, 0.85))          # hours 15-24
MID_RAMP = (0.00, -0.07)              # hours 7-14, first -> last
LATE_RAMP = (0.00, 0.05)              # hours 15-24, first -> last
LNV1_SLOPE = -0.015
LNV1_PIVOT = 11.5
DISAG_K = 0.5
LATE_SPREAD = (0.975, 0.90)           # hours 15 -> 24


# ------------------------------------------------------------------ numerics
def midpoint(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])


def upper_mid(vals):
    """Upper median (sorted[n//2]) for the g12 / pre_rough fallback."""
    s = sorted(vals)
    return s[len(s) // 2] if s else 0.0


def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0


def sd_pop(vals):
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def sd_samp(vals):
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def bound(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def gauss_solve(mat, vec):
    """Gauss-Jordan with partial pivoting; None if singular."""
    n = len(vec)
    aug = [list(mat[i]) + [vec[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-11:
            return None
        aug[col], aug[piv] = aug[piv], aug[col]
        for r in range(n):
            if r == col:
                continue
            fac = aug[r][col] / aug[col][col]
            if fac == 0.0:
                continue
            for k in range(col, n + 1):
                aug[r][k] -= fac * aug[col][k]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def least_squares(design, targets, ridge=1e-9):
    p = len(design[0])
    gram = [[sum(r[i] * r[j] for r in design)
             + (ridge if i == j else 0.0) for j in range(p)]
            for i in range(p)]
    rhs = [sum(r[i] * y for r, y in zip(design, targets))
           for i in range(p)]
    return gauss_solve(gram, rhs)


def wsum(beta, row):
    return sum(b * x for b, x in zip(beta, row))


# ---------------------------------------------------------------------- data
def read_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def hour_maps(points):
    viewers, channels = {}, {}
    for pt in points:
        val = pt.get("viewers")
        if val is None or val <= 0:
            continue
        t = read_ts(pt["from"])
        viewers[t] = float(val)
        ch = pt.get("channels")
        if ch is not None and ch > 0:
            channels[t] = float(ch)
    return viewers, channels


def prem_roughness(vmap, day_start):
    start = read_ts(day_start)
    pts = sorted((t, v) for t, v in vmap.items()
                 if start - timedelta(days=7) <= t < start)
    diffs = []
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if (t1 - t0).total_seconds() == 3600:
            diffs.append(math.log(v1) - math.log(v0))
    return sd_pop(diffs) if len(diffs) >= 10 else None


def launch_feats(vmap, day_start, hour1):
    start = read_ts(day_start)
    prior = [v for t, v in vmap.items()
             if start - timedelta(days=7) <= t < start]
    if not prior:
        return None
    prem = math.log(mean(prior))
    want = start - timedelta(hours=12)
    best = None
    for t, v in vmap.items():
        gap = abs((t - want).total_seconds())
        if gap <= 3 * 3600 and (best is None or gap < best[0]):
            best = (gap, v)
    g12 = None if best is None else math.log(hour1) - math.log(best[1])
    return {"lnV1": math.log(hour1), "lnPREM": prem, "g12": g12,
            "pre_rough": prem_roughness(vmap, day_start)}


def classify_tier(note):
    t = (note or "").lower()
    if "early-access-contaminated" in t or "early-access contaminated" in t:
        return "ea"
    if "tier: weak" in t:
        return "weak"
    return "comparable"


def read_comparable(comp):
    vmap, _ = hour_maps(comp["hourly"])
    start = read_ts(comp["day_start"])
    v1 = vmap.get(start)
    if v1 is None:
        return None
    curve = {}
    for h in range(1, 25):
        t = start + timedelta(hours=h - 1)
        if t in vmap:
            curve[h] = vmap[t]
    if sum(1 for h in curve if h >= 2) < 20:
        return None
    feats = launch_feats(vmap, comp["day_start"], v1)
    if feats is None:
        return None
    feats["curve"] = curve
    feats["name"] = comp["name"]
    feats["console"] = "PC" not in comp.get("platforms", "")
    note = comp.get("unlock", "") or ""
    feats["tier"] = classify_tier(note)
    feats["space_ea"] = "early access" in note.lower()
    feats["hyphen_ea"] = "early-access" in note.lower()
    return feats


def read_case(case):
    vmap, _ = hour_maps(case["history_hourly"])
    v1 = max(1.0, float(next(k for k in case["known"]
                             if k["hour"] == 1)["viewers"]))
    tgt = launch_feats(vmap, case["day_start"], v1)
    tgt["curve"] = {}
    lib = []
    for comp in case["comparables"]:
        if "before release" in comp["name"]:
            continue
        parsed = read_comparable(comp)
        if parsed is not None:
            lib.append(parsed)
    for key in ("g12", "pre_rough"):
        vals = sorted(f[key] for f in lib if f[key] is not None)
        if not vals:
            continue
        fb = upper_mid(vals)
        if tgt[key] is None:
            tgt[key] = fb
        for f in lib:
            if f[key] is None:
                f[key] = fb
    return tgt, lib


# ---------------------------------------------------------------------- views
def lib_span(lib):
    return min(f["lnV1"] for f in lib), max(f["lnV1"] for f in lib)


def design_row(feats, lo, hi, cols):
    size = bound(feats["lnV1"], lo, hi + 0.5)
    vals = {"lnV1": size, "lnPREM": feats["lnPREM"],
            "g12": feats["g12"]}
    return [1.0] + [vals[c] for c in cols]


def nearby_pool(lib, lnv1, half=2.5):
    close = [f for f in lib if abs(f["lnV1"] - lnv1) <= half]
    return close if len(close) >= 10 else list(lib)


def ols_forecast(lib, tgt, hour, window=2.5,
                 cols=("lnV1", "lnPREM", "g12"), mult=0.8,
                 population=True, count_after=False):
    if count_after:
        pool = [f for f in lib if hour in f["curve"]
                and abs(f["lnV1"] - tgt["lnV1"]) <= window]
        if len(pool) < 10:
            pool = [f for f in lib if hour in f["curve"]]
    else:
        pool = [f for f in nearby_pool(lib, tgt["lnV1"], window)
                if hour in f["curve"]]
    if len(pool) < 8:
        return None
    lo, hi = lib_span(lib)
    design = [design_row(f, lo, hi, cols) for f in pool]
    ys = [math.log(f["curve"][hour]) for f in pool]
    beta = least_squares(design, ys)
    if beta is None:
        return None
    resid = [y - wsum(beta, r) for r, y in zip(design, ys)]
    sd = sd_pop(resid) if population else sd_samp(resid)
    mu = wsum(beta, design_row(tgt, lo, hi, cols)) + midpoint(resid)
    return mu, sd * mult


def ea_pool(base, kind):
    if kind == "tier":
        return [f for f in base if f["tier"] != "ea"]
    if kind == "naive":
        return [f for f in base if not f["space_ea"]]
    return [f for f in base if not f["hyphen_ea"]]


def shape_forecast(lib, tgt, console_only, feats=("lnV1", "lnPREM", "g12"),
                   mult=1.0, population=True, windowed=False,
                   ea_kind="hyphen", fit_hours=20, min_fits=5):
    base = nearby_pool(lib, tgt["lnV1"]) if windowed else list(lib)
    pool = ea_pool(base, ea_kind)
    if console_only:
        pool = [f for f in pool if f["console"]]
    if len(pool) < 6:
        pool = ea_pool(base, ea_kind)
    if len(pool) < 6:
        return None
    template = {}
    for h in HOURS:
        vals = [math.log(f["curve"][h] / f["curve"][1]) for f in pool
                if h in f["curve"] and 1 in f["curve"]]
        template[h] = midpoint(vals) if vals else 0.0
    fits = []
    for f in pool:
        xs = [template[h] for h in HOURS if h in f["curve"]]
        ys = [math.log(f["curve"][h] / f["curve"][1]) for h in HOURS
              if h in f["curve"]]
        if len(xs) < fit_hours:
            continue
        mx, my = mean(xs), mean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
                 if den else 0.0)
        fits.append((f, my - slope * mx, slope))
    if len(fits) < min_fits:
        return None
    lo, hi = lib_span(lib)
    design = [design_row(f, lo, hi, feats) for f, _, _ in fits]
    beta_c = least_squares(design, [c for _, c, _ in fits])
    beta_s = least_squares(design, [s for _, _, s in fits])
    if beta_c is None or beta_s is None:
        return None
    xt = design_row(tgt, lo, hi, feats)
    c_star = wsum(beta_c, xt)
    s_star = bound(wsum(beta_s, xt), 0.0, 2.0)
    out = {}
    for h in HOURS:
        res = [math.log(f["curve"][h] / f["curve"][1])
               - (c + s * template[h])
               for f, c, s in fits if h in f["curve"]]
        sd = sd_pop(res) if population else sd_samp(res)
        out[h] = (tgt["lnV1"] + c_star + s_star * template[h], sd * mult)
    return out


# ------------------------------------------------------------------ predictors
def family_member(lib, tgt, ea_kind, feats, mix=(0.5, 0.2, 0.3)):
    con = shape_forecast(lib, tgt, True, feats=feats, mult=1.0,
                         population=True, windowed=True,
                         ea_kind=ea_kind, fit_hours=10, min_fits=6)
    all_ = shape_forecast(lib, tgt, False, feats=feats, mult=1.0,
                          population=True, windowed=True,
                          ea_kind=ea_kind, fit_hours=10, min_fits=6)
    out = {}
    for h in HOURS:
        views = []
        ov = ols_forecast(lib, tgt, h, window=2.5, mult=0.8,
                          population=True)
        if ov is not None:
            views.append((mix[0], ov))
        else:
            views.append((mix[0], (tgt["lnV1"], 0.5)))
        if con is not None and h in con:
            views.append((mix[1], con[h]))
        if all_ is not None and h in all_:
            views.append((mix[2], all_[h]))
        tot = sum(w for w, _ in views)
        mu = sum(w * v[0] for w, v in views) / tot
        sig = math.sqrt(max(0.02, sum(w * v[1] ** 2 for w, v in views)
                            / tot))
        out[h] = (mu, sig)
    return out


def clone_member(lib, tgt, weights=(0.6, 0.2, 0.2), spread_scale=0.81):
    con = shape_forecast(lib, tgt, True,
                         feats=("lnV1", "lnPREM", "g12"),
                         population=False, ea_kind="hyphen",
                         fit_hours=20, min_fits=5)
    all_ = shape_forecast(lib, tgt, False,
                          feats=("lnV1", "lnPREM", "g12"),
                          population=False, ea_kind="hyphen",
                          fit_hours=20, min_fits=5)
    out = {}
    for h in HOURS:
        views = []
        ov = ols_forecast(lib, tgt, h, window=2.5, population=False,
                          count_after=True)
        if ov is not None:
            views.append((weights[0], ov))
        if con is not None and h in con:
            views.append((weights[1], con[h]))
        if all_ is not None and h in all_:
            views.append((weights[2], all_[h]))
        if not views:
            out[h] = (tgt["lnV1"], 0.5)
            continue
        tot = sum(w for w, _ in views)
        mu = sum(w * v[0] for w, v in views) / tot
        sig = spread_scale * sum(w * v[1] for w, v in views) / tot
        out[h] = (mu, sig)
    return out


def band_idx(hour):
    return 0 if hour <= 6 else 1 if hour <= 14 else 2


def predict_case(case):
    """{hour: [q05..q95]} for one case."""
    tgt, lib = read_case(case)
    y5 = family_member(lib, tgt, "tier", ("lnV1", "g12"))
    z0 = family_member(lib, tgt, "naive", ("lnV1", "g12"))
    y1 = family_member(lib, tgt, "naive", ("lnV1", "lnPREM"))
    cl = clone_member(lib, tgt)
    # Size shift: the median runs high on big launches; the final
    # case (lnV1 ~ 14+) is the furthest extrapolation of all.
    shift = LNV1_SLOPE * max(0.0, tgt["lnV1"] - LNV1_PIVOT)
    out = {}
    for h in HOURS:
        b = band_idx(h)
        if b == 0:
            # Early band: Y1's log-median, flat offset 0.
            mu = y1[h][0] + shift
        elif b == 1:
            # Mid band: half-blend median, ramped 0.00 -> -0.07.
            # The half-blend median runs high late in the band;
            # the ramp corrects a within-band slope, not a level.
            frac = (h - 7) / 7.0
            mu = (0.5 * y5[h][0] + 0.5 * cl[h][0]
                  + MID_RAMP[0] + (MID_RAMP[1] - MID_RAMP[0]) * frac
                  + shift)
        else:
            # Late band: median of the three family members,
            # ramped 0.00 -> +0.05.
            frac = (h - 15) / 9.0
            mu = (midpoint([y5[h][0], z0[h][0], y1[h][0]])
                  + LATE_RAMP[0] + (LATE_RAMP[1] - LATE_RAMP[0]) * frac
                  + shift)
        sig = BASE_SCALE * (BLEND_W[0] * y5[h][1]
                            + BLEND_W[1] * z0[h][1]
                            + BLEND_W[2] * cl[h][1])
        # Disagreement factor: when the four member medians
        # disagree, the truth is further away, so widen.
        meds = [y5[h][0], z0[h][0], y1[h][0], cl[h][0]]
        sig *= 1.0 + DISAG_K * sd_pop(meds)
        # Late-band spread ramp: the curve flattens late, so the
        # spread scale narrows 0.975 -> 0.90 across hours 15-24.
        if h >= 15:
            frac = (h - 15) / 9.0
            sig *= (LATE_SPREAD[0]
                    + (LATE_SPREAD[1] - LATE_SPREAD[0]) * frac) \
                / BASE_SCALE
        lo, hi = BAND_SCALES[b]
        qs = []
        prev = 1.0
        for z in ZS:
            s = sig * (lo if z < 0 else hi if z > 0 else 1.0)
            q = min(1e9, max(1.0, math.exp(mu + z * s)))
            q = max(q, prev)
            prev = q
            qs.append(q)
        out[h] = qs
    return out


def _check_output(doc):
    """Validate one forecast document against the output contract.

    23 hour rows (hours 2..24), each with exactly five finite,
    non-decreasing quantiles. Raises ValueError on any violation,
    so a bad forecast fails loudly instead of being written.
    """
    rows = doc.get("hours")
    if not isinstance(rows, list) or len(rows) != 23:
        raise ValueError("expected 23 hour rows, got "
                         f"{len(rows) if isinstance(rows, list) else rows!r}")
    for row in rows:
        q = row.get("q")
        if not isinstance(q, list) or len(q) != 5:
            raise ValueError(f"hour {row.get('hour')}: expected 5 "
                             f"quantiles, got {q!r}")
        for v in q:
            if not (isinstance(v, (int, float)) and math.isfinite(v)
                    and v > 0):
                raise ValueError(f"hour {row.get('hour')}: non-finite "
                                 f"or non-positive quantile {v!r}")
        if any(q[i + 1] < q[i] for i in range(4)):
            raise ValueError(f"hour {row.get('hour')}: quantiles not "
                             f"non-decreasing: {q!r}")
    return True


def main():
    in_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = sorted(in_dir.glob("*.in"))
    if not inputs:
        raise SystemExit("no .in files in input dir")
    for path in inputs:
        case = json.loads(path.read_text())
        fc = predict_case(case)
        doc = {"hours": [{"hour": h, "q": fc[h]} for h in HOURS]}
        _check_output(doc)
        (out_dir / (path.stem + ".out")).write_text(json.dumps(doc))


if __name__ == "__main__":
    main()
