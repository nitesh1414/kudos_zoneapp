"""Unit tests for session_chart() — no database required.

The chart on the Overview tab draws one zone sheet per session, so each level
line can be drawn only across the candles of the day it belongs to. A
stand-in store returns deterministic candles, so this suite runs anywhere:

    cd backend && python -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from app import service
from app.zones import ZoneParams

IST = ZoneInfo('Asia/Kolkata')
SYMBOL = 'NSE:NIFTY50-INDEX'


def _sessions(n, start='2026-08-03'):
    """`n` weekday sessions with deterministic, drifting OHLC."""
    rows, day, px = [], datetime.strptime(start, '%Y-%m-%d').date(), 24000.0
    while len(rows) < n:
        if day.weekday() < 5:
            i = len(rows)
            rows.append(dict(d=day.isoformat(), o=round(px, 2), h=round(px + 120 + (i % 7) * 11, 2),
                             l=round(px - 130 - (i % 5) * 9, 2), c=round(px + 40 + (i % 3) * 25, 2),
                             n_bars=25))
            px = rows[-1]['c'] + 25
        day += timedelta(days=1)
    return rows


def _bars(session):
    """25 fifteen-minute bars walking from the open to the close of a session."""
    day = datetime.strptime(session['d'], '%Y-%m-%d')
    out = []
    for i in range(25):
        mid = session['o'] + (session['c'] - session['o']) * (i / 24)
        out.append(dict(ts=day + timedelta(hours=9, minutes=15 * i),
                        o=round(mid, 2), h=round(mid + 18, 2), l=round(mid - 18, 2),
                        c=round(mid + 4, 2), v=500000 + i * 1000))
    return out


class FakeStore:
    """Just enough of the persistence layer for session_chart()."""

    def __init__(self, sessions, outcomes=None):
        self.daily_df = pd.DataFrame(sessions)
        self.outcomes = outcomes or []  # list of dicts with target_date + flags
        self.bars_calls = []

    def daily(self, symbol, min_bars=20, resolution='15'):
        return self.daily_df

    def bars_range(self, symbol, date_from, date_to, resolution='15', limit=5000):
        self.bars_calls.append((date_from, date_to, resolution))
        rows = [b for s in self.daily_df.to_dict('records')
                if date_from <= s['d'] <= date_to for b in _bars(s)]
        return pd.DataFrame(rows)

    def bars_for_day(self, symbol, d, resolution='15'):
        frame = self.daily_df[self.daily_df['d'] == d]
        return pd.DataFrame([] if frame.empty else _bars(frame.iloc[0].to_dict()))

    def q(self, sql, params=None):
        if 'zone_outcomes' in sql:
            _, date_from, date_to = params
            rows = [r for r in self.outcomes if date_from <= r['target_date'] <= date_to]
            return pd.DataFrame(rows, columns=['target_date', 'label', 'touched',
                                               'bounced', 'broke', 'held'])
        if 'market_holidays' in sql:
            return pd.DataFrame(columns=['holiday_date'])
        raise AssertionError(f'unexpected query: {sql}')

    def one(self, sql, params=None):
        return None  # no holidays in the stand-in


class SessionChartDayLevelsTest(unittest.TestCase):
    """day_levels must carry one scored sheet per session drawn on the chart."""

    def setUp(self):
        self.sessions = _sessions(8)
        self.store = FakeStore(self.sessions)
        # After the close of the last stored session: it is complete, so the
        # default chart view sits on it and shows the two sessions before it.
        self.now = datetime.fromisoformat(f"{self.sessions[-1]['d']}T17:00:00").replace(tzinfo=IST)
        self._real_now = service._now_ist
        service._now_ist = lambda now=None: now or self.now
        self.addCleanup(setattr, service, '_now_ist', self._real_now)
        self.chart = service.session_chart(self.store, SYMBOL, ZoneParams())

    def test_one_sheet_per_session_in_the_window(self):
        self.assertEqual([d['date'] for d in self.chart['day_levels']],
                         [s['d'] for s in self.sessions[-3:]])
        for entry in self.chart['day_levels']:
            self.assertTrue(entry['levels'], f'no levels for {entry["date"]}')
            self.assertTrue(all(l['result'] for l in entry['levels']),
                            f'{entry["date"]} has unscored levels')

    def test_each_sheet_is_built_from_the_session_before_it(self):
        by_date = {s['d']: s for s in self.sessions}
        for i, entry in enumerate(self.chart['day_levels']):
            expected_basis = self.sessions[-4 + i]['d']
            self.assertEqual(entry['basis']['date'], expected_basis)
            self.assertAlmostEqual(entry['basis']['close'], by_date[expected_basis]['c'])
            # Zones of a session differ from the next session's because their
            # basis OHLC differs — this is what tells the days apart on screen.
        keys = [tuple(l['key'] for l in d['levels']) for d in self.chart['day_levels']]
        self.assertEqual(len(set(keys)), len(keys), 'every session must get its own levels')

    def test_focused_session_still_drives_the_top_level_fields(self):
        """The chips/subtitle read levels + basis; they must match the viewed day."""
        focused = self.chart['day_levels'][-1]
        self.assertEqual(self.chart['date'], focused['date'])
        self.assertEqual(self.chart['levels'], focused['levels'])
        self.assertEqual(self.chart['basis'], focused['basis'])
        self.assertEqual(self.chart['day_type'], focused['day_type'])

    def test_stored_outcomes_win_over_bars_derived_ones(self):
        day = self.sessions[-1]['d']
        label = self.chart['levels'][0]['label']
        store = FakeStore(self.sessions, outcomes=[dict(
            target_date=day, label=label, touched=True, bounced=False, broke=True, held=False)])
        service._now_ist = lambda now=None: now or self.now
        chart = service.session_chart(store, SYMBOL, ZoneParams())
        scored = {l['label']: l['result'] for l in chart['day_levels'][-1]['levels']}
        self.assertEqual(scored[label], 'BROKE')

    def test_long_ranges_are_capped_but_flagged(self):
        store = FakeStore(_sessions(30))
        first, last = store.daily_df['d'].iloc[0], store.daily_df['d'].iloc[-1]
        chart = service.session_chart(store, SYMBOL, ZoneParams(), date_from=first, date_to=last)
        self.assertTrue(chart['day_levels_capped'])
        self.assertEqual(len(chart['day_levels']), service.MAX_DAY_LEVELS)
        self.assertEqual(chart['day_levels'][-1]['date'], last)


if __name__ == '__main__':
    unittest.main()
