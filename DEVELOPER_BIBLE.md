# Zone Levels — Developer Bible

Single reference for building the production app. Read this before writing
code. It contains every formula, the Excel→Python port map, the broker
plug-in contract, performance rules, security rules, and the Phase 2
roadmap for integration into Market Pulse.

**Broker is not finalized.** Everything here is written broker-agnostic on
purpose — one interface (`BrokerAdapter`), swap the implementation later
without touching anything else.

---

## 0. Non-negotiables — read this section twice

1. **No key, token, or secret in any file — ever.** Not in `.py`, not in
   `.xlsx`, not in a comment, not in a commit, not in a log line. Secrets
   live in environment variables or a secrets manager, nowhere else. See §6.
2. **Files stay small.** Target under ~150 lines per file. One
   responsibility per file. If a file is doing two jobs, split it.
3. **No file/module does O(n×m) work against a growing table.** This is not
   a style preference — it caused a real production-blocking bug (§4.4).
4. **Every formula in this document is locked.** If a definition changes
   (bounce_pts, break_pts, weights, clustering tolerance), historical rows
   computed under the old definition are no longer comparable to new ones.
   Version parameters (§2.7), never silently redefine them.
5. **This is a reference map generator, not a signal generator.** No
   specific buy/sell instruction, entry price, target, or stop-loss —
   ever, at any phase. A general session bias/direction display is
   planned for a later phase (§8.0-8.1) but only after SEBI RA
   registration is complete, and even then the line is "direction, not
   tips" — see §8.1 for the exact operational definition. Until §8.1's
   conditions are met, do not build any directional-bias feature at all.

---

## 1. What this system computes, in one paragraph

Each completed session's High/Low/Close produces a set of price levels
(pivot-family formulas + round numbers). Levels within a tolerance of each
other are merged into **zones**. Each zone gets a **star rating** from the
combined empirical weight of its member levels. Zones are classified as
resistance/support against the **session's own close** and stay fixed for
the following session. Separately, every zone's real-world outcome
(touched / bounced / broke / held) is logged daily, which is what produces
the base-rate statistics (gap-fill curve, CPR day-type behavior, etc.).

---

## 2. Complete formula reference

All formulas take **H, L, C** = the basis (completed) session's High, Low,
Close. Nothing here ever depends on live/intraday price — that is what
keeps zones stable for the whole next session.

### 2.1 Core pivot values

```
R  = H − L                      (session range)
PP = (H + L + C) / 3            (pivot point)
BC = (H + L) / 2                (bottom central pivot)
TC = 2·PP − BC                  (top central pivot)
CPR_width = |TC − BC|
CPR_pct   = 100 · CPR_width / C
```

### 2.2 Candidate levels (21 formula levels + round numbers)

| Level | Formula | Weight |
|---|---|---|
| PP | `(H+L+C)/3` | 1.0 |
| TC | `2·PP − BC` | 0.5 |
| BC | `(H+L)/2` | 0.5 |
| PDC | `C` | 1.0 |
| PDH | `H` | 0.6 |
| PDL | `L` | 0.8 |
| CamR3 | `C + R×1.1/4` | 0.6 |
| CamR4 | `C + R×1.1/2` | 0.4 |
| CamS3 | `C − R×1.1/4` | 1.0 |
| CamS4 | `C − R×1.1/2` | 0.7 |
| FibR1 | `PP + 0.382·R` | 0.7 |
| FibR2 | `PP + 0.618·R` | 0.4 |
| FibS1 | `PP − 0.382·R` | 0.8 |
| FibS2 | `PP − 0.618·R` | 0.8 |
| ClaR1 | `2·PP − L` | 0.4 |
| ClaS1 | `2·PP − H` | 0.8 |
| ExtR1/R2/R3 | `H + 0.5R / 1R / 1.5R` | 0.5/0.5/0.4 |
| ExtS1/S2/S3 | `L − 0.5R / 1R / 1.5R` | 0.5/0.5/0.4 |
| RN_k | `round(C/step)·step + k·step`, k=−12..12 | 0.3 each |

Weights are **empirical**, from a 541-session study measuring bounce-on-
touch rate per level family against a random-line control (~62% baseline).
They are not tunable-by-feel — a weight change is a new hypothesis and
needs its own validation pass before it replaces the table above.

`step` (round-number spacing) is instrument-specific: Nifty 100,
BankNifty 500, Midcap 100 (tune per instrument, not guessed).

### 2.3 Clustering — anchor-based, not running-maximum

```
sort all candidate levels by price
i = 0
while i < n:
    anchor = price[i]
    cluster = [i]
    j = i + 1
    while j < n and price[j] − anchor <= cluster_tol:
        cluster.append(j)
        j += 1
    # zone bounds, padded to a minimum half-width
    mid = (price[cluster[0]] + price[cluster[-1]]) / 2
    zone.lo = min(price[cluster[0]], mid − zone_half_w)
    zone.hi = max(price[cluster[-1]], mid + zone_half_w)
    zone.weight = sum(weight[k] for k in cluster)
    zone.stars  = clamp(round(zone.weight × 1.5), 1, 5)
    zone.key    = price of the max-weight member (not the midpoint)
    i = j
```

**Why anchor, not running-max:** comparing each new level against the
*anchor* (not the growing cluster's upper edge) stops chains from forming.
Running-max clustering merges A→B→C→D indefinitely on a narrow-range day
and produces a single 130-point "zone" that means nothing. This was a real
bug, fixed once, must not be reintroduced.

**Zone `key` is the highest-weight member's own price, not the cluster
midpoint.** The midpoint is not a real level; the key member is.

Defaults: `cluster_tol` = 25 pts (Nifty) / 70 (BankNifty) / 30 (Midcap).
`zone_half_w` = 15 / 40 / 20 respectively.

### 2.4 Classification — against basis close, fixed for the session

```
for each zone:
    mid = (zone.lo + zone.hi) / 2
    if zone.lo <= C <= zone.hi:   label = "AT"
    elif mid > C:                 label = "R" + rank (nearest first)
    else:                          label = "S" + rank (nearest first)
```

Classify against the **session's own close (C)**, never against live
intraday price. An earlier version classified against live price; the
moment price crossed a level, that zone silently relabelled and the
morning's reference stopped existing mid-session. Labels are fixed once
per session, full stop.

### 2.4.1 Field note — this exact bug happened three times, in three places

Not hypothetical: the "basis = session's own data instead of the prior
session's" mistake occurred independently in the Excel workbook three
times — once in `Tracking` (basis columns copied from the wrong row),
once in `PredictionLog` (a stored snapshot written against the wrong
zone set), and once in `ZoneLog` (a later feature's basis block built off
the target session's own close). Same root cause every time: a human or
assistant set the basis by hand instead of it being derived.

This is the empirical justification for §2.4's rule being a hard
structural constraint, not a coding guideline: **basis must be computed
from "the last complete session in the database," in code, every single
time — never accepted as an input, never copied, never typed.** If a
function signature anywhere takes a basis H/L/C as a parameter that isn't
itself the direct output of "fetch the last complete row," that's the
same bug waiting to happen a fourth time.

**First unit test to write, before anything else:** given a sequence of
sessions, assert that computing session N+1's basis always equals session
N's actual close (never session N+1's own close, never any other row).
This one test would have caught all three historical incidents.

### 2.4.2 The Excel workbook is not a reference implementation

The retired workbook (frozen at Phase 1 close-out, 01-Aug-2026) is a
findings archive, not a spec to read formulas from. Features added to it
after close-out (e.g. a later trade-scenario dashboard) were not held to
the same validation rigor as §2 and reproduced the exact bug in §2.4.1.
Build from the formula reference in §2 and the schema in §8.2, not by
inspecting the workbook's live cells.

### 2.5 Gap and fill definitions

```
gap_pts  = open − PDC
gap_pct  = 100 · gap_pts / PDC

filled   = (gap_pts > 0 AND day_low  <= PDC) OR
           (gap_pts < 0 AND day_high >= PDC) OR
           (gap_pts == 0)

closure_pct   (gap up)   = clamp(0,100, 100·(open − day_low)  / (open − PDC))
closure_pct   (gap down) = clamp(0,100, 100·(day_high − open) / (PDC − open))
closure_pct   (no gap)   = 100

category = "FILLED"     if filled
         = "NEAR MISS"  if closure_pct >= 85
         = "PARTIAL"    if closure_pct >= 40
         = "FAR"        otherwise
```

**The denominator must be gap size, never day range.** Dividing by day
range instead of gap size is a formula bug that produces impossible values
above 100% — this happened once in production (row-level incident, see the
retired workbook's AuditReport for the full trace) and must not recur.

### 2.6 Zone outcome definitions — locked, do not loosen

```
touched  = any bar's [low, high] intersects [zone.lo, zone.hi]
bounced  = after the first touch, price moved >= bounce_pts (45)
           away from the zone on the approach side
broke    = a bar CLOSED >= break_pts (15) beyond the zone's far edge
held     = touched AND bounced AND NOT broke
```

`bounced` and `broke` are independent booleans and can both be true in one
session (bounce first, break later). They do not sum to 100% — that is by
design, not a bug.

**"Touched" requires the bar range to actually intersect the zone.** A
session that gaps clean over a zone and never revisits it did NOT touch
that zone, even if the close ends up on the far side. This distinction
was itself the subject of a real scoring error — see §7.3.

### 2.7 CPR day type and trend day

```
day_type = "NARROW" if CPR_pct < 0.08
         = "WIDE"   if CPR_pct > 0.26
         = "NORMAL" otherwise

close_loc = (C_today − L_today) / (H_today − L_today)
trend_day = (close_loc >= 0.75 OR close_loc <= 0.25)
            AND range_pct_today >= median(range_pct, trailing sample)
```

**Confirmed finding, do not re-derive from scratch:** NARROW CPR days have
*fewer* trend days than WIDE CPR days (26.3% vs 32.1% in the reference
sample) — the inverse of the popular "narrow CPR → big move" claim. This
was independently confirmed twice. If a future dataset contradicts it,
that's a real finding worth investigating, not a bug to "fix" back toward
the popular belief.

### 2.8 Parameter set (version everything)

```python
@dataclass
class ZoneParams:
    cluster_tol: float = 25.0
    zone_half_w: float = 15.0
    round_step: float = 100.0
    zones_per_side: int = 4
    break_pts: float = 15.0
    bounce_pts: float = 45.0
```

Any change to these values invalidates comparison with historically
computed rows. Hash the param set (`sha1` of sorted dict) and store it on
every computed row (`params_hash`). Never mix rows computed under
different hashes in one statistic without accounting for it.

---

## 3. Rejected hypotheses — do not rebuild these

Each was tested against this exact dataset and failed. If asked to add one
back, the answer is "tested, here are the numbers," not a rebuild.

| Idea | Result |
|---|---|
| VWAP side as a direction signal | 50.5% — coin flip |
| VWAP slope/angle as reversal filter | winners 1.52 vs losers 1.80 pts/bar — no discrimination |
| "Narrow CPR ⇒ trending day" | narrow CPR had *fewer* trend days, not more |
| "Open above CPR ⇒ bullish" | 42.8% closed green — inverted |
| **Star rating → touch rate (H-007)** | **confounded by distance-from-open**; controlled delta ±1-2pp, noise |
| **Star rating → hold rate (H-008)** | flat 33–38% across all star levels |
| **Star rating → reversal size (H-009)** | inverted — 1★ zones showed the *largest* reversals |
| VWAP-consolidation breakout sleeve | PF 0.97, Era-1 negative |
| Gap-retest at outermost zone (Variant A) | PF 0.81 |

**Star count must never be presented as a reliability or performance
metric anywhere in the app.** Display it as "confluence" (how many
independent formulas overlap) with no implied predictive claim. This was
a real bug in an earlier share-card design — fixed once, do not reintroduce.

## 3.1 What survived — build on these

| Finding | Status |
|---|---|
| Gap-fill curve (monotonic, |gap| vs fill %) | Solid, stable across two eras |
| CPR day-type inversion (§2.7) | Solid, confirmed twice |
| Gap-retest Variant B (basis zone break + retest, trade in gap direction) | PF 1.52, both eras positive, promising — not yet validated for live capital |
| Overnight vs intraday drift split | Solid structural finding — index gains concentrate overnight |

---

## 4. Excel → Python port map

The retired Excel workbook (`nifty_zones_tracker*.xlsx`) is now frozen and
disposable. Its *findings* are permanent; its *implementation* is not. This
table maps every Excel concept to its Python equivalent so nothing gets
silently lost in translation.

| Excel | Python | Notes |
|---|---|---|
| `Levels` tab formulas | `zones.py::candidate_levels()` + `cluster()` | Formula-for-formula identical, verified by cross-check |
| `Tracking` basis columns (C,D,E) | `db.py::daily()` → last complete row | Basis = prior session's own H/L/C, never live/self |
| `ZoneLog` | `zone_outcomes` table | One row per zone per session |
| `Pivot` tab | `service.py::stats_zones()` | COUNTIFS → pandas groupby |
| `DayStats` tab | `service.py::stats_days()` | Gap-fill curve, CPR table, weekday table |
| `Backtest` tab | separate research repo, not the live app | Gap-retest Variant B lives here once promoted |
| `HypothesisRegister` | `docs/HYPOTHESIS_REGISTER.md` (§9) | Port as a markdown table, keep IDs (H-001…) |
| `AuditReport` incident log | `CHANGELOG.md` + git history | Real incidents worth a paragraph, not every commit |
| `Share` tab | dashboard `/` route + a `/api/share` endpoint | No star-performance columns (§3) |
| Whole-column `COUNTIFS(ZoneLog!$X:$X, …)` per Tracking row | a single indexed SQL query (`GROUP BY target_date`) | This is the fix for the O(n×m) bug — see §4.4 |

### 4.1 Formula translation pattern

Every Excel formula in §2 has a 1:1 Python function. Example:

```python
# Excel: =2*E5-E6   (TC = 2*PP - BC)
def tc(pp: float, bc: float) -> float:
    return 2 * pp - bc
```

Do not "improve" the formula while porting it (rename variables, fine;
change the math, not without a new validation pass). If in doubt, the
Excel cell reference is the spec.

### 4.2 Row-relative logic, not date-hardcoded

Excel's later fixes used row-relative comparisons (`this row's basis =
previous row's actual`) instead of hardcoded dates. Keep that discipline in
Python: every query should be relative to "the last complete session" or
"the row above," never a literal date string. This is what let an audit
script work correctly regardless of how much history existed.

### 4.3 Never hardcode a number where a computation belongs

This was an explicit rule in the Excel workbook and it carries over
directly: no magic numbers in code without a name and a source. `0.08`,
`0.26`, `15`, `45`, `1.1`, `0.382` — every constant in §2 needs to live in
one place (`zones.py::ZoneParams` and the `WEIGHTS`/formula constants), not
scattered as literals through the codebase.

### 4.4 The O(n×m) bug — do not reintroduce this class of bug

**What happened:** the Excel workbook grew a `Tracking` sheet where every
row ran ~30 `COUNTIFS` formulas against the *entire* `ZoneLog` sheet
(4,900+ rows). With 546 Tracking rows, that's roughly 546 × 4,900 × 30 ≈
80 million formula evaluations, repeated on every keystroke. Recalculation
started timing out past two minutes.

**The fix, and the rule for Python:** aggregate once, keyed by date, not
per-row-scan-everything:

```python
# WRONG — O(rows × outcomes), gets slower every day
for row in tracking_rows:
    touched = sum(1 for z in zone_outcomes if z.date == row.date and z.touched)

# RIGHT — one indexed query, O(rows)
stats = db.q("""
    SELECT target_date, count(*) FILTER (WHERE touched) AS touched
    FROM zone_outcomes GROUP BY target_date
""")
```

DuckDB (or any real database) with a `GROUP BY` and an index on the date
column does this in milliseconds regardless of how many years of history
accumulate. A spreadsheet re-evaluating a whole-column formula per row does
not scale, ever — this is not a spreadsheet failure, it's the wrong tool
for a table that will keep growing. Do not port the whole-column-scan
pattern into Python "because that's how Excel did it."

---

## 5. Broker abstraction — plug-in contract

**Broker is not decided yet.** Everything downstream (zones, stats,
dashboard) must not know or care which broker is plugged in. One interface,
swap implementations freely.

```python
# broker_adapter.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd

@dataclass
class AuthStatus:
    connected: bool
    message: str

class BrokerAdapter(ABC):
    """Every broker integration implements exactly this. Nothing else in
    the app is allowed to import a broker-specific SDK directly — only
    adapter files under brokers/ may do that."""

    name: str

    @abstractmethod
    def auth_status(self) -> AuthStatus:
        """Is the connection alive right now? No network call side-effects
        beyond a lightweight profile/ping check."""

    @abstractmethod
    def fetch_historical(self, symbol: str, resolution: str,
                          date_from: str, date_to: str) -> pd.DataFrame:
        """Returns columns: ts, o, h, l, c, v (v optional -> 0.0).
        ts must be timezone-naive IST. Raise BrokerError on failure,
        never return partial silent data."""

    @abstractmethod
    def fetch_live_quote(self, symbol: str) -> dict:
        """Returns {ts, ltp, o, h, l, c, v}. Used for the 'live' badge on
        the dashboard, not for zone computation (zones only ever use
        completed sessions)."""

    def stream_live(self, symbol: str, on_tick):
        """Optional. Only implement if the broker supports websockets and
        a live-updating dashboard is actually needed (see §8.3). Default:
        not supported, dashboard falls back to polling fetch_live_quote."""
        raise NotImplementedError(f"{self.name} does not support streaming")


class BrokerError(RuntimeError):
    """Always carries the raw provider response so failures are debuggable
    without guessing."""
    def __init__(self, msg, raw=None):
        super().__init__(msg)
        self.raw = raw
```

### 5.1 Historical vs live — different jobs, different cost

- **Historical** feeds the EOD job (§ service layer) once a day, or backfills
  years of history once. Pull daily/15-min candles for a date range. Cost:
  cheap, infrequent.
- **Live** feeds a "current price" badge and, later, live zone-touch
  alerts (§8.3). This is a different, higher-frequency need. Do not use the
  historical endpoint in a polling loop for this — use a quote/LTP endpoint
  or a websocket if the broker offers one.

Keep these as two separate methods (as above) even if one broker happens to
serve both from the same underlying call — the interface should not assume
that.

### 5.2 Adding a new broker

1. New file `brokers/<name>_adapter.py`, implements `BrokerAdapter`.
2. Credentials read from environment variables only (§6), never from a
   config file checked into git.
3. Add one entry to a broker registry dict — nothing else in the codebase
   changes.
4. **Verify before trusting**, every time: pull a small (5-10 day) date
   range and manually compare 2-3 candles against a chart on the broker's
   own platform before wiring it into the EOD job. No adapter should be
   trusted just because it compiles and returns data — a broker call that
   silently returns the wrong candles is worse than one that fails loudly.

### 5.3 What NOT to do

- Do not let `zones.py`, `service.py`, or the dashboard import a broker SDK
  directly. If you find yourself importing a broker's SDK outside
  `brokers/`, stop — that import belongs in the adapter file only.
- Do not hardcode a symbol format assumption (`NSE:...`) outside the
  adapter — different brokers format symbols differently; normalize at the
  adapter boundary.

---

## 6. Security

1. **Secrets live in environment variables, injected at deploy time.**
   `.env` file on the server, never committed, `chmod 600`. See the
   existing `.env.example` pattern.
2. **The app refuses to start without its own API key set.** Do not add a
   default/fallback key "for convenience" — that is how internal tools end
   up world-writable.
3. **Broker tokens (often expiring daily) live in the database, encrypted
   at rest if the deployment ever becomes multi-user.** For a single-user
   VPS, plain storage in a local DuckDB file the owner controls is
   acceptable; it is not acceptable the moment this becomes multi-tenant.
4. **Never log a secret.** Broker tokens, API keys, auth codes — none of
   these belong in application logs, error messages returned to the
   frontend, or exception tracebacks shown to a user. Redact before
   logging.
5. **Write endpoints require auth; read endpoints for the owner's own
   computed levels can be open**, but put the whole app behind nginx basic
   auth or equivalent if it's reachable from the public internet — the API
   key alone protects *writes*, not visibility.
6. **`.gitignore` must include:** `.env`, `*.duckdb`, `data/`, `venv/`,
   `__pycache__/`. Check this before the first commit, not after a key
   leaks.
7. **Rate-limit outbound broker calls.** A bug that loops and re-fetches
   history can burn through a broker's daily API quota or trigger an
   account flag. Cap retries, back off on failure, log the call count.
8. **No key or token in the Excel workbook, ever, under any circumstance.**
   This was explicit in this project from day one and stays explicit here.

---

## 7. Performance rules

1. **Small, single-responsibility files.** ~150 lines is the target, not a
   hard ceiling — if a file legitimately needs 200, that's fine; if it's
   creeping toward 400, split it.
2. **Aggregate in the database, not in application loops.** See §4.4. Any
   time you're tempted to write a Python `for` loop that queries the
   database once per iteration, write one aggregate query instead.
3. **DuckDB, not pandas-in-memory-forever.** For anything beyond a few
   years of 15-minute bars, let DuckDB do the grouping/filtering with SQL;
   pull into pandas only the already-small result.
4. **Cache computed zone sheets.** A session's zones never change once the
   session is complete — compute once, store, serve from storage. Do not
   recompute on every dashboard load.
5. **Config-driven, not hardcoded per-instrument.** Nifty/BankNifty/Midcap
   differ only in `ZoneParams` values (§2.8) and `round_step` — this should
   be a config lookup by symbol, not three copy-pasted code paths.
6. **DuckDB is correct for solo Phase 1 development, not for the published
   build.** Multi-user access at launch is confirmed, not hypothetical —
   see §9 for the full production architecture (Postgres + Redis) and
   why. Keep `db.py`'s `Store` class as the only thing that talks to the
   database, so that migration is a swap, not a rewrite.

---

## 8. Phase 2 — Market Pulse integration and new features

This section is the actual roadmap. Everything above is the foundation;
this is what gets built on top of it.

### 8.0 Launch sequencing — confirmed order, do not reorder

1. **Now:** Zone Levels app launches **standalone**. Historical reference
   levels + base-rate stats only, computed from completed sessions. No
   live data, no direction/bias display of any kind.
2. **Later, gated:** live broker data (§5) gets wired in, **and** SEBI RA
   registration is completed — these two are meant to land together, not
   live-data-first. Do not ship live data ahead of registration being in
   place.
3. **After that:** Market Pulse integration (§8.1 onward, multi-user
   architecture §9). Direction/bias display (§8.1) is only switched on at
   this stage, never before.

If asked to build live data or a direction feature before registration is
confirmed complete, say so and hold — this is a sequencing rule, not a
suggestion.

### 8.1 Product boundary — direction is allowed later, tips never are

The line is **"direction, not tips."** Both terms need a precise,
operational definition so nobody has to guess where a specific feature
falls:

**Allowed, once gated conditions in §8.0 are met:**
- A session-level bias/lean display — e.g. "session bias: bullish /
  bearish / neutral," or a bounded score like the VWAP+PDC+OR30 composite
  already researched (§3.1-adjacent work), shown as a general market
  read.
- Zone/level display with historical base rates (already built, §2-§3) —
  this is descriptive, not directional, and needs no gating at all.
- Educational framing: "historically, sessions with this gap size filled
  X% of the time" — a fact about the past, not an instruction for today.

**Never allowed, at any phase, regardless of registration status:**
- A specific buy/sell instruction for a specific instrument.
- An entry price, target price, or stop-loss level presented as
  actionable guidance.
- Position sizing or "how much to trade" suggestions.
- Any phrasing that reads as an instruction rather than information —
  "buy near S2," "short below R1," "target R3" are all instructions,
  regardless of how much historical data backs them. "S2 historically
  held 68% of the time when touched" is information; the same fact
  phrased as "buy near S2" is a tip.

**When in doubt about a specific piece of copy or a new feature, this is
the owner's compliance call to make, not a default the app should assume
either way.** Flag it and wait for an explicit decision rather than
guessing which side of the line a new feature falls on — this is a
regulatory boundary, not a style preference, and getting it wrong has
real consequences for a registered RA.

### 8.2 Calibration log (highest-value next feature)

Port the Excel `PredictionLog` concept properly: freeze a session's
prediction (CPR type, expected trend%, expected gap-fill%) *before* the
session opens, then score it against the actual outcome afterward. This is
what turns the base rates in §2/§3 from "what happened historically" into
"how well-calibrated is this system, tracked over time, in public." Given
the compliance context, a transparent, auto-updating calibration record is
a genuine trust asset for the academy — display it, don't hide it.

Schema sketch:

```sql
CREATE TABLE predictions (
    symbol VARCHAR, target_date DATE,
    pred_cpr_type VARCHAR, pred_trend_pct DOUBLE, pred_gapfill_pct DOUBLE,
    locked_at TIMESTAMP,             -- must be before session open
    actual_trend BOOLEAN, actual_gap_filled BOOLEAN,
    match_trend BOOLEAN, match_gapfill BOOLEAN,
    resolved_at TIMESTAMP,
    PRIMARY KEY (symbol, target_date)
);
```

`locked_at` before session open is the whole point — a prediction written
after the fact is not a prediction.

### 8.3 Live zone-touch awareness (needs `stream_live` or polling)

Once a broker with live data is chosen: a lightweight background task
polls or streams price, and flags on the dashboard when price enters a
stored zone *today*. This is descriptive ("price is now inside S2"), not
prescriptive — do not let this drift into an alert that reads as a trade
signal. Compliance check applies here specifically because this is the
feature most likely to accidentally cross the line.

### 8.4 Multi-symbol and per-symbol parameters

The DB schema is already keyed by `symbol` throughout (§4). What's missing:
a per-symbol `ZoneParams` config (Nifty/BankNifty/Midcap need different
`cluster_tol`/`zone_half_w`/`round_step`, §2.8) and a symbol selector on the
dashboard. This is additive, not a rearchitecture.

### 8.5 H-019 — distance-from-open (open research question)

Not yet tested with a proper control. If pursued: compare against the
same random-line baseline used for the original weight table (§2.2), or it
will rediscover ordinary mean-reversion and mistake it for a real finding
— this exact mistake has already happened once with the star-rating
hypotheses (§3) and is the single most important lesson from this project.

### 8.6 Gap-retest Variant B → real sleeve

The one surviving, promising backtest result (§3.1, PF 1.52, both eras
positive) is the natural next research task: paper-trade it forward with
the live app's data before any live-capital consideration. This is
research work, separate from the app build, but the app's live feed (§8.3)
is what will eventually make forward-testing possible without manual data
pulls.

### 8.7 What each new feature must ship with

Every new feature in this list needs, at minimum: (a) the exact formula or
rule, written down like §2, before it's coded; (b) a test against historical
data showing it does what it claims; (c) an explicit compliance check
against §8.1. Skipping any of these three is how the star-rating mistake
happened the first time.

---

## 9. Multi-user production architecture — confirmed for launch

**This is locked, not speculative.** After Market Pulse publish, this app
will have many concurrent read users (students) plus one admin (the owner)
doing writes. Build for this from day one — do not build single-user and
retrofit later.

### 10.1 Two-tier access model

| Tier | Who | Access | Auth |
|---|---|---|---|
| **ADMIN** | Owner only, one account | Full — ingest, EOD job, params, broker config | `X-API-Key` header, current model, unchanged |
| **USER** | Students, many concurrent | Read-only — levels, stats, share card | See §9.5 (open question) |

Nothing about the ADMIN tier changes. Everything in §9 below is about
serving the USER tier at scale without falling over or leaking write access.

### 10.2 Database: DuckDB now, Postgres at publish

**Keep DuckDB through the rest of Phase 1 development** — it's still the
right tool while one person is iterating (cheap, zero-ops, matches the
small-footprint philosophy in §7). **Postgres is the confirmed target for
the published build.** Reason: DuckDB is fundamentally single-writer,
single-process-friendly. The moment the app runs multiple workers (which
it must, to serve concurrent students — see §9.4), several processes will
try to open the same `.duckdb` file at once, which is not what it's built
for. Postgres's connection pooling and MVCC model is built for exactly
this.

**Migration is mostly mechanical, if the storage layer is kept clean now:**

- Keep all database access behind `db.py`'s `Store` class — the same
  discipline as `BrokerAdapter` (§5). Nothing else in the app should write
  raw SQL directly; it should call `Store` methods.
- DuckDB's SQL is close to Postgres's already (same `GROUP BY`,
  aggregate functions, window functions). The schema in §4 translates
  close to as-is.
- Swap the connection layer (`duckdb.connect()` → a Postgres pool, e.g.
  `asyncpg` or SQLAlchemy) inside `db.py` only. If `Store`'s public methods
  don't change shape, nothing outside `db.py` needs to know the database
  changed — same pattern as swapping a broker adapter.
- Size the connection pool to worker count (§9.4), not arbitrarily large.

### 10.3 Redis — now justified, here's exactly what it's for

Three specific uses, not "add Redis because scale":

1. **Pub/sub fan-out for live price.** One broker connection publishes
   ticks to a Redis channel per symbol; every connected student's
   dashboard subscribes to that channel. This is the actual reason Redis
   earns its place — without it, N concurrent viewers would mean N
   separate broker connections, which gets rate-limited or blocked by the
   broker fast.
2. **Response caching for hot read paths.** `/api/stats/*` and
   `/api/levels/next` are read constantly by many users but only change
   once a day (after the EOD job). Cache with a short TTL or explicit
   invalidation right after the EOD job writes — don't hit Postgres for
   every student's page load.
3. **Per-user rate limiting.** A simple Redis counter (`INCR` + `EXPIRE`)
   per user/IP stops one runaway script or bot from hammering the API.
   Needed the moment the app is public-facing.

Do not use Redis for anything beyond these three. It is not a database,
not a queue for the EOD job (cron is still correct for that, §7), and not
a session store unless §9.5 lands on that pattern.

### 10.4 App server: multiple workers, stateless

Move from the current `--workers 1` to multiple Uvicorn/Gunicorn workers.
This is only safe once §9.2 and §9.3 are in place — with Postgres
handling concurrent connections and Redis handling anything that needs to
be shared *across* worker processes (live ticks, rate-limit counters), no
worker needs to hold state that another worker can't see. Keep every
request handler stateless; anything that looks like "remember this between
requests" belongs in Postgres or Redis, never in a Python global.

### 10.5 Open question — student auth

Not yet decided, and worth deciding before building it: does this app run
its own login (email/OTP, its own user table), or does it **trust a
session/token issued by the main Market Pulse app** it's integrating into
(§8) and just verify that token on each request? Given this is explicitly
being folded into an existing product with its own user base, the second
option (delegate auth to Market Pulse, this app stays a verified-token
consumer) avoids building and maintaining a second user/password system
for the same students. Flag this back to the owner before the USER tier
is implemented — it changes what §9.5 needs, not the rest of §9.

### 10.6 Sequencing

1. **Now (rest of Phase 1):** keep DuckDB, single worker, `X-API-Key` only.
   Nothing in §9 blocks current work.
2. **Before publish:** implement §9.2 (Postgres) and §9.3 (Redis) behind
   the same `Store`/interface discipline used for brokers, resolve §9.5,
   then move to §9.4 (multi-worker).
3. **Do not do these out of order** — multi-worker before Postgres will
   produce intermittent, hard-to-debug database lock errors under real
   traffic.

---

## 10. Bug detection strategy — how future bugs get found, not just this one

The three basis-self-reference incidents (§2.4.1) share a root cause worth
generalizing: **every time a value was trusted from a single source, it
was eventually found wrong. Every time it was independently recomputed a
second way and compared, the bug surfaced immediately.** That is not luck
to rely on — it needs to be a structural habit for every future bug class,
not just this one.

### 11.1 Invariant assertions — fail loud, not silent

Every computed value has a "this can never be true" list. Assert it in
code, don't just hope:

```python
assert 0 <= closure_pct <= 100, f"impossible closure_pct: {closure_pct}"
assert 1 <= stars <= 5
assert zone.lo < zone.hi
assert not (basis_date == target_date), "basis must be a prior session"
assert basis_high == prior_session.high, "basis drifted from source row"
```

A closure% of 125% happening once in Excel and going unnoticed for several
turns of conversation is exactly what an assertion exists to prevent — it
should have thrown the moment the number was computed, not been discovered
by a human reading a screenshot later.

### 11.2 One regression test per confirmed bug, forever

Every bug that gets independently confirmed (not just suspected) gets a
permanent test named after it. Do not fix a bug and move on without one —
the fix protects today; the test protects every day after.

```python
def test_basis_never_self_references():
    """Regression test for the incident documented in §2.4.1 —
    occurred 3x in the Excel implementation before this test existed."""
    daily = build_test_sessions(n=10)
    for i in range(1, len(daily)):
        sheet = build_sheet(daily[i-1].d, daily[i-1].h, daily[i-1].l, daily[i-1].c)
        assert sheet.basis_high == daily[i-1].h  # never daily[i].h
        assert sheet.basis_close == daily[i-1].c  # never daily[i].c
```

### 11.3 A daily health check — the guard-row pattern, run automatically

The Excel workbook's `DailyChecks` tab was the right idea, implemented in
the wrong tool (it's what caused the O(n×m) slowdown, §4.4). Same
discipline, run as code instead of spreadsheet formulas:

```python
def health_check(store, symbol: str) -> list[str]:
    """Run daily, right after the EOD job. Returns a list of problems;
    empty list = all clear. Alert (log/email/webhook) on any non-empty
    result — do not let this run silently."""
    issues = []
    daily = store.daily(symbol)
    if len(daily) < 2:
        return issues
    last, prev = daily.iloc[-1], daily.iloc[-2]

    sheet = store.get_sheet(symbol, str(prev.d))
    if sheet.empty:
        issues.append(f"no zone sheet stored for basis {prev.d}")
    else:
        # the exact check that would have caught all three historical
        # incidents in §2.4.1
        stored_basis_h = sheet.iloc[0].get('basis_h')  # adjust to schema
        if stored_basis_h is not None and abs(stored_basis_h - prev.h) > 0.5:
            issues.append(f"basis mismatch: stored {stored_basis_h}, expected {prev.h}")

    if last.h < last.l:
        issues.append(f"{last.d}: high < low, impossible session")
    if last.nb < 20:
        issues.append(f"{last.d}: only {last.nb} bars, session may be incomplete")

    return issues
```

Wire this into the same cron job that runs the EOD job (§7), not a
separate manual step someone has to remember to run.

### 11.4 New features need a second, independent computation before launch

Before trusting any new calculation — a new statistic, a new hypothesis
test, a new derived field — compute it two different ways and compare.
This was the single most effective technique used throughout this
project's development: an independent Python recompute caught the zone-
cluster misread, the touch-vs-broken definition error, and the basis bug
itself, every time, faster than reasoning about the formula in the
abstract. It does not need to be elaborate — a 10-line script that
recomputes the same number a different way and asserts they match is
enough. Do this before shipping, not after a user reports something looks
off.

## 11. Quick reference — file map

```
zones.py            level maths, clustering, outcome scoring   (§2)
db.py                storage, aggregate queries                 (§4.4, §7)
brokers/*.py         one file per broker, implements BrokerAdapter (§5)
service.py            EOD job orchestration, statistics          (§4.4)
main.py                API routes, auth                           (§6)
docs/HYPOTHESIS_REGISTER.md   ported from Excel, keep IDs stable  (§3, §4)
CHANGELOG.md           real incidents, not every commit            (§4)
```

If a change doesn't fit cleanly into one of these files, that's a signal
to make a new small file, not to grow an existing one past its job.
