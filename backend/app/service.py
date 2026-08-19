"""
service.py - orchestration and statistics.

Two responsibilities:
  1. run_eod()  - compute the next session's zones and score yesterday's
  2. stats_*()  - historical base rates read back out of the database

A NOTE ON THE NUMBERS THIS RETURNS
    These are base rates: what happened historically, in a sample. They are
    not forecasts and they are not calibrated probabilities. The random-line
    baseline measured on the same data was ~62% bounce-on-touch, so a zone
    showing 66% is an edge of about 4 percentage points, not 16. Any UI that
    surfaces these must show n alongside, and must not round them into
    something that reads like a prediction.
"""
import hashlib
import json
from datetime import date

import pandas as pd

from .zones import ZoneParams, build_sheet, evaluate_session, classify_day


def params_hash(p: ZoneParams) -> str:
    return hashlib.sha1(json.dumps(p.__dict__, sort_keys=True).encode()).hexdigest()[:10]


def _open_position(open_px, sheet):
    sup_lo = min((z.lo for z in sheet.supports), default=None)
    res_hi = max((z.hi for z in sheet.resistances), default=None)
    if sup_lo is not None and open_px < sup_lo:
        return 'BELOW ALL S'
    if res_hi is not None and open_px > res_hi:
        return 'ABOVE ALL R'
    return 'INSIDE BAND'


def next_session_sheet(store, symbol: str, p: ZoneParams = None):
    """Zones for the session after the last COMPLETE one in the database."""
    p = p or ZoneParams()
    basis = store.last_complete_day(symbol)
    if basis is None:
        return None
    return build_sheet(str(basis.d), float(basis.h), float(basis.l), float(basis.c), p)


def run_eod(store, symbol: str, p: ZoneParams = None, rebuild_all: bool = False):
    """Compute zones for every session and score them against what happened.

    Idempotent: safe to run repeatedly. With rebuild_all=False only the last
    few sessions are recomputed, which is what the daily scheduler wants.
    """
    p = p or ZoneParams()
    ph = params_hash(p)
    daily = store.daily(symbol)
    if len(daily) < 2:
        return dict(ok=False, message='Need at least 2 complete sessions')

    start = 1 if rebuild_all else max(1, len(daily) - 3)
    sheets = scored = 0
    for i in range(start, len(daily)):
        basis, target = daily.iloc[i - 1], daily.iloc[i]
        sheet = build_sheet(str(basis.d), float(basis.h), float(basis.l),
                            float(basis.c), p)
        store.save_sheet(symbol, sheet, str(target.d), ph)
        sheets += 1

        bars = store.bars_for_day(symbol, target.d)
        if bars.empty:
            continue
        blist = bars.rename(columns=str).to_dict('records')
        zlist = list(sheet.resistances) + list(sheet.supports)
        if sheet.at_zone:
            zlist.append(sheet.at_zone)
        recs = evaluate_session(blist, zlist, p)
        gap_pct = 100 * (float(target.o) - float(basis.c)) / float(basis.c)
        store.save_outcomes(symbol, str(target.d), recs, sheet.day_type,
                            round(gap_pct, 4), _open_position(float(target.o), sheet))
        scored += 1

    # the forward-looking sheet has no target session yet
    last = daily.iloc[-1]
    fwd = build_sheet(str(last.d), float(last.h), float(last.l), float(last.c), p)
    store.save_sheet(symbol, fwd, None, ph)

    return dict(ok=True, sheets_written=sheets, sessions_scored=scored,
                next_basis=str(last.d), params_hash=ph)


# --------------------------- statistics ---------------------------
def _rate_table(df, group_col, order=None):
    if df.empty:
        return []
    g = df.groupby(group_col, observed=True)
    rows = []
    for key, sub in g:
        n = len(sub)
        t = int(sub.touched.sum())
        rows.append(dict(
            group=str(key), n=n,
            touch_pct=round(100 * t / n, 1) if n else None,
            bounce_pct=round(100 * sub.bounced.sum() / t, 1) if t else None,
            break_pct=round(100 * sub.broke.sum() / t, 1) if t else None,
            hold_pct=round(100 * sub.held.sum() / t, 1) if t else None))
    if order:
        rows.sort(key=lambda r: order.index(r['group']) if r['group'] in order else 99)
    return rows


def stats_zones(store, symbol: str):
    df = store.q("SELECT * FROM zone_outcomes WHERE symbol = ?", [symbol])
    if df.empty:
        return dict(by_stars=[], by_side=[], by_day_type=[], by_open_pos=[], n=0)
    df['side'] = df.label.str[0].map(lambda x: 'R' if x == 'R' else ('S' if x == 'S' else 'AT'))
    return dict(
        n=int(len(df)),
        sessions=int(df.target_date.nunique()),
        by_stars=_rate_table(df, 'stars'),
        by_side=_rate_table(df, 'side', ['R', 'S', 'AT']),
        by_day_type=_rate_table(df, 'day_type', ['NARROW', 'NORMAL', 'WIDE']),
        by_open_pos=_rate_table(df, 'open_pos',
                                ['INSIDE BAND', 'BELOW ALL S', 'ABOVE ALL R']),
        baseline_note='Random-line baseline on this dataset was ~62% bounce-on-touch. '
                      'Compare against 62, not 50.')


GAP_BUCKETS = [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.45),
               (0.45, 0.6), (0.6, 0.9), (0.9, 999)]


def stats_days(store, symbol: str):
    """Gap-fill curve, CPR day types, weekday table - all from daily OHLC."""
    d = store.daily(symbol)
    if len(d) < 3:
        return dict(gap_fill=[], day_type=[], weekday=[], n=0)
    d = d.reset_index(drop=True)
    d['pc'] = d.c.shift(1)
    d['ph'] = d.h.shift(1)
    d['pl'] = d.l.shift(1)
    d = d.dropna().reset_index(drop=True)

    d['gap_pct'] = (d.o - d.pc) / d.pc * 100
    d['abs_gap'] = d.gap_pct.abs()
    d['rng_pct'] = (d.h - d.l) / d.pc * 100
    cpr = (2 * (d.ph + d.pl + d.pc) / 3 - (d.ph + d.pl)).abs() / d.pc * 100
    d['day_type'] = [classify_day(x) for x in cpr]
    loc = (d.c - d.l) / (d.h - d.l).replace(0, pd.NA)
    d['trend_day'] = ((loc >= 0.75) | (loc <= 0.25)) & (d.rng_pct >= d.rng_pct.median())
    d['filled'] = [(row.l <= row.pc) if row.o > row.pc else
                   ((row.h >= row.pc) if row.o < row.pc else True)
                   for row in d.itertuples()]
    d['up'] = d.c > d.o
    d['dow'] = pd.to_datetime(d.d).dt.day_name().str[:3]

    gap_fill = []
    for a, b in GAP_BUCKETS:
        sub = d[(d.abs_gap >= a) & (d.abs_gap < b)]
        if len(sub) == 0:
            continue
        gap_fill.append(dict(bucket=f'{a}-{b}' if b < 900 else f'>{a}', n=int(len(sub)),
                             fill_pct=round(100 * sub.filled.mean(), 1),
                             trend_pct=round(100 * sub.trend_day.mean(), 1),
                             avg_range_pct=round(sub.rng_pct.mean(), 2)))

    def block(col, order):
        out = []
        for key, sub in d.groupby(col):
            out.append(dict(group=str(key), n=int(len(sub)),
                            trend_pct=round(100 * sub.trend_day.mean(), 1),
                            fill_pct=round(100 * sub.filled.mean(), 1),
                            up_pct=round(100 * sub.up.mean(), 1),
                            avg_range_pct=round(sub.rng_pct.mean(), 2)))
        out.sort(key=lambda r: order.index(r['group']) if r['group'] in order else 99)
        return out

    return dict(
        n=int(len(d)),
        first_date=str(d.d.iloc[0]), last_date=str(d.d.iloc[-1]),
        gap_fill=gap_fill,
        day_type=block('day_type', ['NARROW', 'NORMAL', 'WIDE']),
        weekday=block('dow', ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']),
        caveat='Weekday numbers mix in expiry-day effects and have small n per '
               'weekday. Treat as observation, not a rule.')


def recent_sessions(store, symbol: str, limit: int = 20):
    return store.q("""
        SELECT o.target_date AS date, o.day_type, o.gap_pct, o.open_pos,
               count(*) FILTER (WHERE o.touched) AS touched,
               count(*) FILTER (WHERE o.held)    AS held,
               count(*) FILTER (WHERE o.broke)   AS broke
        FROM zone_outcomes o
        WHERE o.symbol = ?
        GROUP BY 1,2,3,4
        ORDER BY 1 DESC LIMIT ?
    """, [symbol, limit]).to_dict('records')
