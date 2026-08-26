"""
service.py - orchestration and statistics.

Two responsibilities:
  1. run_eod()  - compute the next session's zones and score yesterday's
  2. stats_*()  - historical base rates read back out of the database
  3. dashboard_* — panels surfaced on the client dashboard

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
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .zones import ZoneParams, build_sheet, evaluate_session, classify_day


IST = ZoneInfo('Asia/Kolkata')


def params_hash(p: ZoneParams) -> str:
    return hashlib.sha1(json.dumps(p.__dict__, sort_keys=True).encode()).hexdigest()[:10]


def _now_ist(now=None):
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _is_market_day(store, day):
    """Weekday that is not in the manually/automatically maintained holiday table."""
    if day.weekday() >= 5:
        return False
    try:
        return store.one('SELECT 1 FROM market_holidays WHERE holiday_date=?', [day]) is None
    except Exception:
        return True


def _completed_days(store, symbol, now=None):
    """Stored sessions that are actually complete.

    A session is complete once the market close has passed. The last stored day
    can contain intraday bars while the session is still running; showing it as
    a completed session makes the next-session sheet jump one day too far ahead
    (e.g. showing tomorrow's levels when today's market has not closed yet).
    """
    daily = store.daily(symbol)
    if daily.empty:
        return daily
    now = _now_ist(now)
    today = now.date().isoformat()
    ds = daily['d'].astype(str).str[:10]
    return daily[(ds < today) | ((ds == today) & (now.hour >= 16))].reset_index(drop=True)


def _last_completed_row(store, symbol, now=None):
    df = _completed_days(store, symbol, now)
    return None if df.empty else df.iloc[-1]


def _next_actionable_day(store, last_complete, now=None):
    """The next session the user can actually act on.

    If today's session is running (market open / not yet closed) and it is a
    trading day, the next possible session is today. If today has closed but its
    data is not ingested yet, today is still the actionable sheet (built from the
    last complete close). After today is confirmed complete it moves to the next
    trading day.
    """
    now = _now_ist(now)
    today = now.date()
    last = datetime.strptime(str(last_complete)[:10], '%Y-%m-%d').date()
    if last < today and _is_market_day(store, today):
        return today.isoformat(), 'today-open' if now.hour < 16 else 'today-closed'
    if last == today and now.hour >= 16:
        return _next_trading_day(store, today.isoformat()), 'upcoming'
    return _next_trading_day(store, last.isoformat()), 'upcoming'


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
    basis = _last_completed_row(store, symbol)
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
    from .db import records
    return records(store.q("""
        SELECT o.target_date AS date, o.day_type, o.gap_pct, o.open_pos,
               count(*) FILTER (WHERE o.touched) AS touched,
               count(*) FILTER (WHERE o.held)    AS held,
               count(*) FILTER (WHERE o.broke)   AS broke
        FROM zone_outcomes o
        WHERE o.symbol = ?
        GROUP BY 1,2,3,4
        ORDER BY 1 DESC LIMIT ?
    """, [symbol, limit]))


# --------------------------- DASHBOARD PANELS ---------------------------
def _daily_with_cpr(store, symbol: str) -> pd.DataFrame:
    """Daily OHLC augmented with prior-day fields and CPR classification.

    The standard 'stats_days' helper does almost the same thing; we duplicate
    it here so the dashboard helpers don't have to keep re-loading and so
    zone recalculation can stand alone.
    """
    d = store.daily(symbol)
    if d.empty or len(d) < 3:
        return d
    d = d.reset_index(drop=True)
    d['pc'] = d['c'].shift(1)
    d['ph'] = d['h'].shift(1)
    d['pl'] = d['l'].shift(1)
    d = d.dropna().reset_index(drop=True)
    d['gap_pct'] = (d['o'] - d['pc']) / d['pc'] * 100
    d['abs_gap'] = d['gap_pct'].abs()
    d['rng_pct'] = (d['h'] - d['l']) / d['pc'] * 100
    cpr_pct = (2 * (d['ph'] + d['pl'] + d['pc']) / 3 - (d['ph'] + d['pl'])).abs() / d['pc'] * 100
    d['day_type'] = [classify_day(x) for x in cpr_pct]
    loc = (d['c'] - d['l']) / (d['h'] - d['l']).replace(0, pd.NA)
    median_rng = d['rng_pct'].median()
    d['trend_day'] = ((loc >= 0.75) | (loc <= 0.25)) & (d['rng_pct'] >= median_rng)
    d['filled'] = [
        (row.l <= row.pc) if row.o > row.pc else
        ((row.h >= row.pc) if row.o < row.pc else True)
        for row in d.itertuples()
    ]
    d['up'] = d['c'] > d['o']
    return d


def cpr_matrix(store, symbol: str):
    """CPR-type probability matrix used on the dashboard.

    For each CPR day-type (NARROW / NORMAL / WIDE) we report:
      n              – sample size
      trend_day_pct  – % of those sessions that became trend days
      fill_pct       – % that filled the previous gap
      up_day_pct     – % that closed above their open
      avg_range_pct  – mean intraday range as % of prior close
      avg_gap_pct    – mean absolute gap as % of prior close
    """
    d = _daily_with_cpr(store, symbol)
    if d.empty:
        return dict(rows=[], n=0, total_sample=0)
    rows = []
    for cpr_type in ('NARROW', 'NORMAL', 'WIDE'):
        sub = d[d['day_type'] == cpr_type]
        if sub.empty:
            rows.append(dict(group=cpr_type, n=0, trend_day_pct=None,
                             fill_pct=None, up_day_pct=None,
                             avg_range_pct=None, avg_gap_pct=None))
            continue
        rows.append(dict(
            group=cpr_type,
            n=int(len(sub)),
            trend_day_pct=round(100 * float(sub['trend_day'].mean()), 1),
            fill_pct=round(100 * float(sub['filled'].mean()), 1),
            up_day_pct=round(100 * float(sub['up'].mean()), 1),
            avg_range_pct=round(float(sub['rng_pct'].mean()), 2),
            avg_gap_pct=round(float(sub['abs_gap'].mean()), 2),
        ))
    return dict(rows=rows, total_sample=int(len(d)),
                note='545-session benchmark built from a prior empirical study; '
                     'values shown are computed on your stored sample.')


def gap_guide(store, symbol: str):
    """Return gap-size buckets with their historical fill rates."""
    d = _daily_with_cpr(store, symbol)
    if d.empty:
        return dict(rows=[], total_sample=0, total_gaps=0)
    rows = []
    for a, b in GAP_BUCKETS:
        sub = d[(d['abs_gap'] >= a) & (d['abs_gap'] < b)]
        if len(sub) == 0:
            continue
        rows.append(dict(
            bucket_label=f'{a}-{b}' if b < 900 else f'>{a}',
            bucket_lo=a, bucket_hi=b,
            n=int(len(sub)),
            fill_pct=round(100 * float(sub['filled'].mean()), 1),
        ))
    return dict(rows=rows, total_sample=int(len(d)), total_gaps=int(len(d)))


def _outcome_for(store, symbol: str, target_date: str) -> dict:
    """Pull actual outcomes for one completed session."""
    out = store.q(
        "SELECT label, touched, bounced, broke, held "
        "FROM zone_outcomes WHERE symbol=? AND target_date=?",
        [symbol, target_date]).to_dict('records')
    return {r['label']: r for r in out}


def _zone_result(actual: dict) -> str:
    """One-word outcome for a zone in a completed session. This mapping is
    surfaced verbatim on the dashboards and on the session chart."""
    if actual.get('touched'):
        if actual.get('broke') and not actual.get('held'):
            return 'BROKE'
        if actual.get('held'):
            return 'HELD'
        if actual.get('bounced') and not actual.get('broke'):
            return 'TOUCHED'
        return 'TOUCHED' if not actual.get('broke') else 'BROKE'
    return 'NOT REACHED'


def _zone_side(label: str) -> str:
    return 'R' if label.startswith('R') else ('S' if label.startswith('S') else 'AT')


def _sheet_zones(sheet):
    return (list(sheet.resistances) + list(sheet.supports) +
            ([sheet.at_zone] if sheet.at_zone else []))


def session_recap(store, symbol: str, target_date: str = None, p: ZoneParams = None):
    """Recap one past (completed) session."""
    p = p or ZoneParams()
    daily = store.daily(symbol)
    if daily.empty:
        return None
    daily = daily.reset_index(drop=True)
    daily['d'] = daily['d'].astype(str)

    if target_date is None:
        completed = _completed_days(store, symbol)
        if completed.empty:
            return None
        target_date = str(completed.iloc[-1]['d'])

    target_idx = daily.index[daily['d'] == str(target_date)]
    if len(target_idx) == 0:
        return None
    target_idx = int(target_idx[0])
    if target_idx == 0:
        return None
    target = daily.iloc[target_idx]
    basis = daily.iloc[target_idx - 1]

    sheet = build_sheet(str(basis['d']), float(basis['h']),
                         float(basis['l']), float(basis['c']), p)
    zones = list(sheet.resistances) + list(sheet.supports)
    if sheet.at_zone:
        zones.append(sheet.at_zone)

    baseline_pd = float(basis['c'])
    actuals = dict(
        date=target_date,
        open=float(target['o']), high=float(target['h']),
        low=float(target['l']), close=float(target['c']),
        change_pct=round(100 * (float(target['c']) - baseline_pd) / baseline_pd, 2),
        gap_pct=round(100 * (float(target['o']) - baseline_pd) / baseline_pd, 2),
        day_type=sheet.day_type,
        prev_close=baseline_pd,
        prev_high=float(basis['h']), prev_low=float(basis['l']),
        range_pct=round(100 * (float(target['h']) - float(target['l'])) / baseline_pd, 2),
    )

    outcomes = _outcome_for(store, symbol, target_date)
    zone_payload = []
    for z in zones:
        actual = outcomes.get(z.label, {})
        result = _zone_result(actual) if actual else 'NOT REACHED'
        zone_payload.append(dict(
            label=z.label, lo=z.lo, hi=z.hi, key=z.key,
            key_name=z.key_name, stars=z.stars, weight=z.weight,
            members=z.members, result=result,
        ))

    touched_count = sum(1 for z in zone_payload if z['result'] in ('TOUCHED', 'HELD', 'BROKE'))
    held_count = sum(1 for z in zone_payload if z['result'] == 'HELD')
    broke_count = sum(1 for z in zone_payload if z['result'] == 'BROKE')
    direction = 'Up' if actuals['change_pct'] >= 0 else 'Down'
    gap_dir = 'up' if actuals['gap_pct'] >= 0 else 'down'
    commentary = (
        f"{direction} {abs(round(actuals['change_pct'], 2))}% close-to-close; "
        f"gapped {gap_dir} {abs(round(actuals['gap_pct'], 2))}% from prior close. "
        f"Of {len(zone_payload)} S/R zones, {touched_count} touched · "
        f"{held_count} held · {broke_count} broke. Basis CPR was "
        f"{sheet.day_type}."
    )

    return dict(
        date=target_date,
        basis=dict(
            date=str(basis['d']),
            high=float(basis['h']), low=float(basis['l']), close=baseline_pd,
            range_pct=round(100 * (float(basis['h']) - float(basis['l'])) / baseline_pd, 2),
        ),
        actuals=actuals,
        zones=zone_payload,
        commentary=commentary,
    )


def match_check(store, symbol: str, target_date: str = None, p: ZoneParams = None):
    """Compare what ACTUALLY happened on `target_date` with the BASE LINE
    statistics for that day's CPR-type."""
    p = p or ZoneParams()
    recap = session_recap(store, symbol, target_date, p)
    if recap is None:
        return None

    day_type = recap['actuals']['day_type']
    matrix = cpr_matrix(store, symbol)
    base = next((r for r in matrix['rows'] if r['group'] == day_type), None)

    prev_close = recap['actuals']['prev_close']
    a = recap['actuals']
    # gap fill: did the price retrace to (or past) prev_close during the day?
    if a['gap_pct'] >= 0:
        actual_filled = a['low'] <= prev_close
    else:
        actual_filled = a['high'] >= prev_close

    rng = a['high'] - a['low']
    if rng > 0:
        loc = (a['close'] - a['low']) / rng
        actual_trend = loc >= 0.75 or loc <= 0.25
    else:
        actual_trend = False

    fill_distance_pct = round(100 * (a['close'] - prev_close) / prev_close, 2)

    trend_pct = base['trend_day_pct'] if base and base['trend_day_pct'] is not None else None
    fill_pct = base['fill_pct'] if base and base['fill_pct'] is not None else None

    verdict = (
        f"{'trend day' if actual_trend else 'non-trend day'} · "
        f"Gap {'FILLED' if actual_filled else 'NOT FILLED'} "
        f"({fill_distance_pct}% from PDC)"
    )

    commentary = (
        f"{day_type} CPR type: trend-day {trend_pct if trend_pct is not None else '-'}%, "
        f"gap-fill {fill_pct if fill_pct is not None else '-'}% historically. "
        f"Actual: {verdict}."
    )

    return dict(
        basis_cpr_type=day_type,
        base_row=base,
        actual=dict(
            trend_day=bool(actual_trend),
            filled=bool(actual_filled),
            fill_distance_pct=fill_distance_pct,
        ),
        verdict=verdict,
        commentary=commentary,
    )


def _next_trading_day(store, day: str) -> str:
    """Best-effort next session after `day`: skip weekends and stored holidays."""
    d = datetime.strptime(day, '%Y-%m-%d').date() + timedelta(days=1)
    try:
        frame = store.q("SELECT holiday_date FROM market_holidays "
                        "WHERE holiday_date > ? AND holiday_date <= ?",
                        [day, str(d + timedelta(days=45))])
        holidays = {str(x)[:10] for x in frame['holiday_date']} if not frame.empty else set()
    except Exception:
        holidays = set()
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d += timedelta(days=1)
    return d.isoformat()


def session_chart(store, symbol: str, p: ZoneParams = None, date: str = None,
                  date_from: str = None, date_to: str = None, resolution: str = '15',
                  view: str = None):
    """Candles + zone levels for the TradingView-style chart on the Overview tab.

    Default view: the last *completed* session, its zones with their outcomes,
    and the forward-looking sheet for the next possible session. If today's
    market has not closed yet, the incomplete day is never treated as the last
    completed session — so the chart does not jump ahead to tomorrow.

    Quick views:
      latest / next  → last completed result + the actionable next sheet
      today          → today's session (running bars before close, result after)
      prev           → the previous completed session's result
    """
    p = p or ZoneParams()
    now = _now_ist()
    today = now.date().isoformat()
    daily = store.daily(symbol)
    if daily.empty:
        raise LookupError('No candles stored yet for this symbol')
    days = [str(d) for d in daily['d']]
    first_date, last_date = days[0], days[-1]

    completed = _completed_days(store, symbol, now)
    completed_days = [str(d) for d in completed['d']] if not completed.empty else []
    last_complete = completed_days[-1] if completed_days else None
    today_complete = today in completed_days
    view = (view or 'latest').lower()
    if view not in ('latest', 'today', 'next', 'prev'):
        raise ValueError("view must be one of latest, today, next, prev")

    def parse(name, value):
        if value is None:
            return None
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f'{name} must be YYYY-MM-DD')
        return value

    date, date_from, date_to = parse('date', date), parse('date_from', date_from), parse('date_to', date_to)

    # Stored candles may be sparse (weekends, holidays, partial history), so
    # requested dates snap to the nearest session that actually has bars.
    def stored_on_or_before(day):
        known = [d for d in days if d <= day]
        return known[-1] if known else None

    def stored_on_or_after(day):
        known = [d for d in days if d >= day]
        return known[0] if known else None

    if date:
        # A weekend/holiday pick shows the last session before it instead.
        start = end = stored_on_or_before(date)
        if end is None:
            raise LookupError(f'No candles stored on or before {date}')
    elif date_from or date_to:
        if date_from and date_from > last_date:
            raise LookupError(f'Range starts after the last stored session ({last_date})')
        # The default "until" is the last completed session, never a partially
        # filled day that is still running (that would add a future sheet).
        end = stored_on_or_before(date_to) if date_to else last_complete
        if end is None:
            end = last_date
        start = (stored_on_or_after(date_from) or first_date) if date_from else end
        if start > end:
            raise LookupError(f'No candles stored between {date_from} and {date_to}')
        span = days.index(end) - days.index(start) + 1
        if resolution != 'D' and span > 62:
            # Keep intraday payloads bounded; the chart tells the user when
            # its window was cut short.
            start = days[days.index(end) - 61]
    else:
        # Session quick-picker / the default "Latest" view.
        if last_complete is None:
            raise LookupError('No completed session available yet; the market has not closed today')
        if view == 'prev':
            end = completed_days[-2] if len(completed_days) >= 2 else last_complete
        elif view == 'today' and not today_complete and today in days:
            # "Today" while the market is running shows today's real bars plus
            # today's zones; it never jumps ahead to a future session.
            end = today
        else:
            end = last_complete
        start = end

    # Quick views get a TradingView-like multi-session window so the user can
    # see the last few candles (yesterday + today) together, not just one day.
    candle_start, candle_end = start, end
    if not date and not (date_from or date_to) and last_complete and end in days:
        if view in ('latest', 'next') and not today_complete and today in days:
            candle_end = today
        elif view == 'today' and not today_complete and today in days:
            candle_end = today
        idx_end = days.index(candle_end)
        candle_start = days[max(0, idx_end - 2)]

    idx = days.index(end)
    basis_meta = None
    day_type = None
    levels = []
    outcomes = _outcome_for(store, symbol, end)
    if idx > 0:
        basis = daily.iloc[idx - 1]
        sheet = build_sheet(str(basis.d), float(basis.h), float(basis.l), float(basis.c), p)
        if not outcomes:
            # Candles are stored but the market-close job has not scored this
            # session yet (e.g. right after the close). Derive the result from
            # the stored 15-minute bars so the chart still shows it.
            bars_15m = store.bars_for_day(symbol, end, '15')
            if not bars_15m.empty:
                recs = evaluate_session(bars_15m.rename(columns=str).to_dict('records'),
                                        _sheet_zones(sheet), p)
                outcomes = {r['label']: r for r in recs}
        day_type = sheet.day_type
        basis_meta = dict(date=str(basis.d), high=float(basis.h), low=float(basis.l), close=float(basis.c))
        for z in _sheet_zones(sheet):
            actual = outcomes.get(z.label)
            levels.append(dict(label=z.label, lo=z.lo, hi=z.hi, key=z.key, key_name=z.key_name,
                               side=_zone_side(z.label),
                               result=_zone_result(actual) if actual else None))
        levels.sort(key=lambda r: -r['key'])

    # The next session sheet only makes sense at the actionable frontier: the
    # last completed session. It is never rendered on a historical/previous view.
    is_latest_complete = bool(last_complete and end == last_complete)
    next_levels = []
    next_session_date = None
    next_session_kind = None
    if is_latest_complete:
        last_idx = days.index(last_complete)
        last = daily.iloc[last_idx]
        fwd = build_sheet(last_complete, float(last.h), float(last.l), float(last.c), p)
        for z in _sheet_zones(fwd):
            next_levels.append(dict(label=z.label, lo=z.lo, hi=z.hi, key=z.key,
                                    key_name=z.key_name, side=_zone_side(z.label)))
        next_levels.sort(key=lambda r: -r['key'])
        next_session_date, next_session_kind = _next_actionable_day(store, last_complete, now)

    bars = store.bars_range(symbol, candle_start, candle_end, resolution)
    from .db import records
    candles = records(bars)
    return dict(symbol=symbol, resolution=resolution,
                mode='day' if candle_start == candle_end else 'range',
                date=end, date_from=candle_start, date_to=candle_end,
                first_date=first_date, last_date=last_date,
                basis=basis_meta, day_type=day_type,
                levels=levels, next_levels=next_levels,
                next_session_date=next_session_date,
                next_session_kind=next_session_kind,
                today=today, last_complete_date=last_complete,
                session_complete=is_latest_complete, view=view,
                server_time=now.isoformat(timespec='seconds'),
                candles=candles, truncated=len(candles) >= 5000)


def dashboard_payload(store, symbol: str, p: ZoneParams = None):
    """All panels surfaced on the client dashboard, in one round-trip."""
    p = p or ZoneParams()
    basis = _last_completed_row(store, symbol)
    sheet = next_session_sheet(store, symbol, p)

    basis_meta = None
    if basis is not None:
        rng_pct = (100 * (float(basis.h) - float(basis.l)) / float(basis.c)) if basis.c else 0
        basis_meta = dict(
            date=str(basis.d),
            high=float(basis.h), low=float(basis.l), close=float(basis.c),
            range_pct=round(float(rng_pct), 2),
            cpr_pct=round(float(sheet.cpr_pct), 3) if sheet is not None else None,
        )

    # Historical touch/hold rate for each zone's strength band, so the client
    # dashboard can show the base rate without exposing the star rating.
    rate_by_star = {str(r['group']): r for r in stats_zones(store, symbol).get('by_stars', [])}

    zones_panel = dict(basis=basis_meta, day_type=None, rows=[])
    if sheet is not None and basis is not None:
        zones_panel['day_type'] = sheet.day_type

        # Order rows in 'spread' order, top-down: R4, R3, R2, R1, AT, S1, S2, S3, S4
        # The sheet gives them naturally ordered; just relabel zones as R/S
        rows = []
        for z in (list(sheet.resistances) + list(sheet.supports) +
                  ([sheet.at_zone] if sheet.at_zone else [])):
            kind = ('R' if z.label.startswith('R') else
                    'S' if z.label.startswith('S') else 'AT')
            rows.append(dict(
                label=z.label, lo=z.lo, hi=z.hi,
                key=z.key, key_name=z.key_name,
                weight=z.weight, stars=z.stars,
                kind=kind,
                dist_from_pdc=round(z.key - float(basis.c), 1),
                touch_pct=rate_by_star.get(str(z.stars), {}).get('touch_pct'),
                hold_pct=rate_by_star.get(str(z.stars), {}).get('hold_pct'),
            ))
        zones_panel['rows'] = rows

    completed = _completed_days(store, symbol)
    recap_target = None if completed.empty else str(completed.iloc[-1].d)

    recap = session_recap(store, symbol, recap_target, p)
    match = match_check(store, symbol, recap_target, p)

    gift = store.kv_get("dashboard_gift_nifty", default=None)

    return dict(
        server_time=datetime.utcnow().isoformat() + 'Z',
        symbol=symbol,
        zones=zones_panel,
        cpr_matrix=cpr_matrix(store, symbol),
        gap_guide=gap_guide(store, symbol),
        session_recap=recap,
        match_check=match,
        gift_nifty=gift,
    )