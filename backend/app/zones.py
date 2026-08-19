"""
zones.py - Zone calculation engine.

This is the single source of truth for level maths. The Pine indicator
(zones_v2.pine) and the Excel workbook implement the same formulas; if you
change anything here, change it there too or the three will disagree.

Level weights come from an empirical study of 541 NSE Nifty sessions
(May 2024 - Jul 2026, 15-minute bars). Weight is proportional to how often
a level family was reached and respected relative to a random-line baseline
of ~62% bounce-on-touch. They are NOT arbitrary.
"""
from dataclasses import dataclass, asdict, field
from typing import Optional

# --- empirical weights (see docs/METHODOLOGY.md) ---
WEIGHTS = {
    'PDC': 1.0, 'PP': 1.0, 'TC': 0.5, 'BC': 0.5,
    'CamS3': 1.0, 'CamS4': 0.7, 'CamR3': 0.6, 'CamR4': 0.4,
    'FibS1': 0.8, 'FibS2': 0.8, 'FibR1': 0.7, 'FibR2': 0.4,
    'ClaS1': 0.8, 'ClaR1': 0.4, 'PDH': 0.6, 'PDL': 0.8,
    'ExtR1': 0.5, 'ExtR2': 0.5, 'ExtR3': 0.4,
    'ExtS1': 0.5, 'ExtS2': 0.5, 'ExtS3': 0.4,
}
ROUND_NUMBER_WEIGHT = 0.3


@dataclass
class ZoneParams:
    """Change these per instrument. Defaults are tuned for Nifty 50."""
    cluster_tol: float = 25.0      # BankNifty 70, Midcap 30
    zone_half_w: float = 15.0      # BankNifty 40, Midcap 20
    round_step: float = 100.0      # BankNifty 500
    zones_per_side: int = 4
    round_span: int = 12           # how many round numbers each way
    # outcome evaluation
    break_pts: float = 15.0        # close this far beyond edge = break
    bounce_pts: float = 45.0       # move this far away = bounce


@dataclass
class Zone:
    label: str
    lo: float
    hi: float
    key: float
    key_name: str
    stars: int
    weight: float
    members: str

    def dict(self):
        return asdict(self)


@dataclass
class ZoneSheet:
    basis_date: str
    basis_high: float
    basis_low: float
    basis_close: float
    range_pts: float
    range_pct: float
    cpr_width: float
    cpr_pct: float
    day_type: str
    resistances: list = field(default_factory=list)
    supports: list = field(default_factory=list)
    at_zone: Optional[Zone] = None

    def dict(self):
        d = asdict(self)
        d['resistances'] = [z.dict() if isinstance(z, Zone) else z for z in self.resistances]
        d['supports'] = [z.dict() if isinstance(z, Zone) else z for z in self.supports]
        d['at_zone'] = self.at_zone.dict() if isinstance(self.at_zone, Zone) else self.at_zone
        return d


def candidate_levels(high: float, low: float, close: float, p: ZoneParams):
    """All candidate price levels from one completed session.

    Nothing here depends on live price, so levels never drift intraday.
    """
    r = high - low
    pp = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = 2.0 * pp - bc

    levels = {
        'PP': pp, 'TC': tc, 'BC': bc,
        'PDC': close, 'PDH': high, 'PDL': low,
        'CamR3': close + r * 1.1 / 4, 'CamR4': close + r * 1.1 / 2,
        'CamS3': close - r * 1.1 / 4, 'CamS4': close - r * 1.1 / 2,
        'FibR1': pp + 0.382 * r, 'FibR2': pp + 0.618 * r,
        'FibS1': pp - 0.382 * r, 'FibS2': pp - 0.618 * r,
        'ClaR1': 2 * pp - low, 'ClaS1': 2 * pp - high,
        'ExtR1': high + 0.5 * r, 'ExtR2': high + r, 'ExtR3': high + 1.5 * r,
        'ExtS1': low - 0.5 * r, 'ExtS2': low - r, 'ExtS3': low - 1.5 * r,
    }
    weights = dict(WEIGHTS)

    base = round(close / p.round_step) * p.round_step
    for k in range(-p.round_span, p.round_span + 1):
        v = base + k * p.round_step
        name = f'RN{int(v)}'
        levels[name] = v
        weights[name] = ROUND_NUMBER_WEIGHT

    meta = dict(range_pts=r, pp=pp, tc=tc, bc=bc, cpr_width=abs(tc - bc))
    return levels, weights, meta


def cluster(levels: dict, weights: dict, p: ZoneParams):
    """Anchor-based clustering.

    Each cluster starts at an anchor level and absorbs everything within
    cluster_tol OF THE ANCHOR. Using the running maximum instead would let
    clusters chain indefinitely and produce 130-point 'zones' on narrow days.
    """
    items = sorted(levels.items(), key=lambda kv: kv[1])
    out = []
    i = 0
    while i < len(items):
        anchor_name, anchor = items[i]
        hi = anchor
        total = weights[anchor_name]
        best_w, best_p, best_n = weights[anchor_name], anchor, anchor_name
        members = [anchor_name]
        j = i + 1
        while j < len(items) and items[j][1] - anchor <= p.cluster_tol:
            nm, v = items[j]
            hi = v
            total += weights[nm]
            members.append(nm)
            if weights[nm] > best_w:
                best_w, best_p, best_n = weights[nm], v, nm
            j += 1
        mid = (anchor + hi) / 2
        out.append(Zone(
            label='', lo=min(anchor, mid - p.zone_half_w),
            hi=max(hi, mid + p.zone_half_w),
            key=best_p, key_name=best_n,
            stars=min(5, max(1, round(total * 1.5))),
            weight=round(total, 2), members='+'.join(members)))
        i = j
    return out


def classify_day(cpr_pct: float) -> str:
    if cpr_pct < 0.08:
        return 'NARROW'
    if cpr_pct > 0.26:
        return 'WIDE'
    return 'NORMAL'


def build_sheet(basis_date: str, high: float, low: float, close: float,
                p: ZoneParams = None) -> ZoneSheet:
    """Full R1..Rn / S1..Sn sheet for the session AFTER basis_date.

    Zones are classified against the BASIS CLOSE, not live price, so the
    R/S labels stay fixed for the whole of the next session.
    """
    p = p or ZoneParams()
    levels, weights, meta = candidate_levels(high, low, close, p)
    zs = cluster(levels, weights, p)

    at = next((z for z in zs if z.lo <= close <= z.hi), None)
    rest = [z for z in zs if z is not at]
    res = [z for z in rest if (z.lo + z.hi) / 2 > close][:p.zones_per_side]
    sup = [z for z in rest if (z.lo + z.hi) / 2 < close][::-1][:p.zones_per_side]

    for i, z in enumerate(res):
        z.label = f'R{i + 1}'
    for i, z in enumerate(sup):
        z.label = f'S{i + 1}'
    if at:
        at.label = 'AT'

    cpr_pct = 100 * meta['cpr_width'] / close
    return ZoneSheet(
        basis_date=str(basis_date), basis_high=high, basis_low=low, basis_close=close,
        range_pts=round(meta['range_pts'], 2),
        range_pct=round(100 * meta['range_pts'] / close, 3),
        cpr_width=round(meta['cpr_width'], 2), cpr_pct=round(cpr_pct, 4),
        day_type=classify_day(cpr_pct),
        resistances=res, supports=sup, at_zone=at)


def evaluate_session(bars, zones, p: ZoneParams = None):
    """What each zone actually did during one session.

    bars: list of dicts with o/h/l/c in chronological order.

    Definitions (kept identical to the 541-session study - do not loosen
    these or historical base rates stop being comparable):
      touched : a bar's high/low range intersected the zone
      bounced : price then moved >= bounce_pts away on the approach side
      broke   : a bar CLOSED >= break_pts beyond the far edge
      held    : touched and bounced and never broke
    """
    p = p or ZoneParams()
    if not bars:
        return []
    hi = [b['h'] for b in bars]
    lo = [b['l'] for b in bars]
    cl = [b['c'] for b in bars]
    op = bars[0]['o']

    results = []
    for z in zones:
        rec = dict(label=z.label, key=z.key, key_name=z.key_name, lo=z.lo, hi=z.hi,
                   stars=z.stars, touched=False, bounced=False, broke=False,
                   held=False, opened_inside=z.lo <= op <= z.hi)
        first = next((j for j in range(len(hi)) if lo[j] <= z.hi and hi[j] >= z.lo), None)
        if first is None:
            results.append(rec)
            continue
        rec['touched'] = True
        from_below = (cl[first - 1] if first > 0 else op) < z.lo
        pc, ph, pl = cl[first:], hi[first:], lo[first:]
        if from_below:
            bidx = next((k for k, x in enumerate(pc) if x > z.hi + p.break_pts), None)
            pre_lo = min(pl[:bidx + 1]) if bidx is not None else min(pl)
            rec['bounced'] = (z.lo - pre_lo) >= p.bounce_pts
        else:
            bidx = next((k for k, x in enumerate(pc) if x < z.lo - p.break_pts), None)
            pre_hi = max(ph[:bidx + 1]) if bidx is not None else max(ph)
            rec['bounced'] = (pre_hi - z.hi) >= p.bounce_pts
        rec['broke'] = bidx is not None
        rec['held'] = rec['touched'] and rec['bounced'] and not rec['broke']
        results.append(rec)
    return results
