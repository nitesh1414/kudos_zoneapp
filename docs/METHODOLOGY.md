# ZoneApp methodology

How every number in this application is produced, in the order the engine
produces it. Each heading matches a label you will see in the interface.

The system turns **one completed session's High, Low and Close** into a map of
price zones for the **next** session, then measures — every day, on real data —
what those zones actually did. Nothing is predicted; everything on screen is
either arithmetic on a finished session or a count of what happened in the
stored sample.

> This is a reference map generator, not a signal generator. No entry, target
> or stop-loss is produced anywhere in the product.

---

## 0. Vocabulary at a glance

| Term | One line | Where you see it |
|---|---|---|
| **Basis session** | The last completed session; every level is derived from it | Overview, Zones |
| **High / Low / Close** | That session's extremes and settlement price | Overview, Zones |
| **Range** | `High − Low`, shown as % of Close | Overview, Zones |
| **CPR width** | Distance between the two central pivots, as % of Close | Overview, Zones |
| **CPR type** | NARROW / NORMAL / WIDE bucket of CPR width | Everywhere |
| **Zone** | A cluster of levels treated as one band (`lo … hi`) | Zones |
| **Level** | The single most important price inside a zone | Zones |
| **Built from** | Which level family gave the zone its key price | Zones |
| **Touch rate** | How often a zone of this quality was reached | Zones, Base rates |
| **Held** | Reached, pushed away from, and never closed through | Zones, Base rates |
| **Touched / Bounced / Broke** | The three outcome flags scored per zone per session | Base rates, Sessions |
| **Gap %** | Opening price versus the previous close | Sessions, Gap & CPR |
| **Open position** | Where the open sat relative to the whole zone band | Sessions, Base rates |
| **Base rate** | A plain historical frequency, always shown with its `n` | Base rates |

---

## 1. Inputs: the basis session

Raw **15-minute candles** are the source of truth. A trading day is rolled up
into daily OHLC only when it has at least **20 candles**, so half-days and
partial downloads never become a basis session.

```
High  (H)  = highest high of the session
Low   (L)  = lowest low of the session
Close (C)  = close of the final candle
Range (R)  = H − L                 shown as  100 × R / C  (%)
```

Everything below uses only H, L and C. No live or intraday price enters the
calculation, which is why the zone map cannot drift while the market is open.

---

## 2. Central pivot range (CPR)

```
PP (pivot point)        = (H + L + C) / 3
BC (bottom central)     = (H + L) / 2
TC (top central)        = 2 × PP − BC
CPR width               = |TC − BC|
CPR %                   = 100 × CPR width / C
```

**CPR width** is the compression of the previous session: a tight CPR means the
session closed near the middle of a small balance area.

### CPR type

| Type | Rule (CPR %) | Reading |
|---|---|---|
| **NARROW** | `< 0.08` | Compressed previous session |
| **NORMAL** | `0.08 – 0.26` | Ordinary balance |
| **WIDE** | `> 0.26` | Previous session was already stretched |

The thresholds are fixed constants in the engine, so a session's type never
changes retroactively. Every base-rate table that groups by "CPR day type" uses
exactly this classification, computed from the **previous** session — that is
what makes it usable before the day starts.

---

## 3. Candidate levels and their weights

Twenty-one formula levels plus round numbers are generated from H, L, C.
The weight is how much that family contributed in the original study of ~541
NSE Nifty sessions (May 2024 – Jul 2026, 15-minute bars), scaled against a
random-line baseline of ≈62% bounce-on-touch. They are empirical, not opinions.

| Level | Formula | Weight |
|---|---|---|
| PDC (previous close) | `C` | 1.0 |
| PP | `(H+L+C)/3` | 1.0 |
| CamS3 | `C − R×1.1/4` | 1.0 |
| PDL | `L` | 0.8 |
| FibS1 / FibS2 | `PP − 0.382R` / `PP − 0.618R` | 0.8 |
| ClaS1 | `2×PP − H` | 0.8 |
| CamS4 | `C − R×1.1/2` | 0.7 |
| FibR1 | `PP + 0.382R` | 0.7 |
| PDH | `H` | 0.6 |
| CamR3 | `C + R×1.1/4` | 0.6 |
| TC / BC | `2×PP − BC` / `(H+L)/2` | 0.5 |
| ExtR1, ExtR2, ExtS1, ExtS2 | `H ± 0.5R`, `H ± R` | 0.5 |
| CamR4 | `C + R×1.1/2` | 0.4 |
| FibR2 | `PP + 0.618R` | 0.4 |
| ClaR1 | `2×PP − L` | 0.4 |
| ExtR3 / ExtS3 | `H + 1.5R` / `L − 1.5R` | 0.4 |
| Round numbers | multiples of the round step around C | 0.3 each |

Support-side families carry more weight than their mirror images because that
is what the sample showed; the asymmetry is deliberate.

---

## 4. From levels to a zone

Levels that sit close together are one decision area, not several. They are
merged by **anchor clustering**:

1. Sort every candidate level by price.
2. Take the lowest unused level as the **anchor**.
3. Absorb every level within `cluster_tol` **of the anchor** (not of the running
   maximum — chaining would produce 130-point "zones" on quiet days).
4. The cluster becomes one zone.

For each zone the engine stores:

| Field | Meaning |
|---|---|
| **lo … hi** (`Range` column) | The band: the cluster's extent, widened to at least `zone_half_w` either side of its midpoint |
| **key** (`Level` column) | The single price inside the band with the highest weight — what you would actually watch |
| **key_name** (`Built from` column) | Which family that key price came from, e.g. `PDH`, `PP`, `CamS3`, `RN24800` |
| **members** | Every level in the cluster, joined with `+` — the full provenance |
| **weight** | Sum of the member weights |
| **stars** | `min(5, max(1, round(weight × 1.5)))` |

**Built from** is therefore not decoration: it tells you whether a zone is a
previous-day extreme, a pivot, a Camarilla level or just a round number.

### Star rating (administrator view only)

Stars compress the summed weight into 1–5. They measure **how often a zone of
that quality is REACHED**, not how often it holds — a five-star zone is a busy
one. Clients see the touch and hold percentages instead, which is the same
information without the shorthand.

---

## 5. Zone map for the next session

Zones are labelled **against the basis close**, once, and then frozen:

| Label | Rule |
|---|---|
| **R1 … R4** | Zone midpoint above the basis close, nearest first |
| **AT** | The zone that contains the basis close (price is *at* it) |
| **S1 … S4** | Zone midpoint below the basis close, nearest first |

Four a side by default (`zones_per_side`). Because the labels come from the
basis close and never from live price, R2 is still R2 at 14:30 — that stability
is the whole point of computing the sheet after the close.

The Zones tab shows, per row: `Zone`, `Level`, `Range`, `Strength` (admin),
`Built from`, `Touch rate` and `Held`. The last two are the historical base
rates for zones of that strength — see §8.

---

## 6. Outcome scoring: Touched, Bounced, Broke, Held

Every zone from the sheet is replayed against the **next** session's 15-minute
candles. Four flags are stored per zone per session, and they are what all the
base rates are counted from.

| Flag | Exact rule |
|---|---|
| **Touched** | Some candle's high/low range intersected `lo … hi` |
| **Bounced** | After the first touch, price moved at least `bounce_pts` away, measured on the side it approached from and before any break |
| **Broke** | Some candle **closed** at least `break_pts` beyond the far edge of the zone |
| **Held** | `Touched AND Bounced AND NOT Broke` |
| **Opened inside** | The session's open was inside `lo … hi` |

Notes that matter when reading the numbers:

- **A close is required to break.** A wick through the zone is not a break;
  that is why "touched" is far more common than "broke".
- **Approach side decides the measurement.** If price came from below, the
  bounce is measured as how far it fell back below `lo`; from above, how far it
  rose back above `hi`.
- **Not reached** is a real outcome. Roughly half of a day's zones are never
  touched, and they are counted in the denominator of the touch rate but not in
  bounce/break/hold.
- **Bounce, break and hold are conditional on a touch.** In every table,
  `touch %` is out of all observations, while `bounce %`, `break %` and
  `held %` are out of the **touched** ones.

---

## 7. Session-level measurements

Computed once per completed session, from daily OHLC plus the previous close
(`PC`).

| Field | Formula | Notes |
|---|---|---|
| **Gap %** | `100 × (Open − PC) / PC` | Positive = gap up. `|Gap|%` is used for bucketing |
| **Gap filled** | Gap up: `Low ≤ PC`. Gap down: `High ≥ PC`. Flat open: counted as filled | "Did price trade back to yesterday's close at any point?" |
| **Trend day** | Close in the top or bottom 25% of the day's range **and** range ≥ the sample's median range | Both conditions — a directional close on a tiny range is not a trend day |
| **Up day** | `Close > Open` | |
| **Range %** | `100 × (High − Low) / PC` | |
| **Open position** | `BELOW ALL S` if the open is under the lowest support band, `ABOVE ALL R` if above the highest resistance band, otherwise `INSIDE BAND` | Measured against that session's own zone sheet |

### Recent sessions

One row per scored session, newest first:

| Column | Meaning |
|---|---|
| **Date** | The session being scored |
| **CPR type** | Type of the *basis* session that produced the sheet |
| **Gap %** | Open versus previous close |
| **Open position** | Where the open sat relative to the zone band |
| **Touched / Held / Broke** | How many of that day's zones ended in each state |

Touched ≥ Held + Broke always: a zone can be touched without doing either.

---

## 8. Base rates

A base rate is a count divided by a count. Nothing is smoothed, weighted or
back-fitted, and `n` is always displayed next to it.

### The 62% baseline

Drawing a **random** line on this dataset produced a bounce-on-touch of about
**62%**. So a zone showing 66% is a ~4-point edge, not a 16-point one. Every
bounce and hold number should be read against 62, never against 50.

### By zone strength (administrator view)

Groups every stored zone observation by its star rating.

| Column | Computation |
|---|---|
| n | Observations in that band |
| Touch % | `touched / n` |
| Bounce % | `bounced / touched` |
| Break % | `broke / touched` |
| Held % | `held / touched` |

This is the table the Zones tab reads to fill its `Touch rate` and `Held`
columns for each row.

### By side, by CPR day type, by opening position

The same four percentages, grouped differently:

- **By side** — `R`, `S` or `AT`, taken from the zone label.
- **By CPR day type** — NARROW / NORMAL / WIDE of the basis session.
- **By opening position** — INSIDE BAND / BELOW ALL S / ABOVE ALL R.

### Gap fill curve

Sessions are bucketed by **absolute** gap size and each bucket reports how
often the gap was filled.

| Bucket (`|Gap| %`) | 0–0.1 · 0.1–0.2 · 0.2–0.3 · 0.3–0.45 · 0.45–0.6 · 0.6–0.9 · >0.9 |
|---|---|
| **n** | Sessions in the bucket |
| **Fill %** | Share where price traded back to the previous close |
| **Trend-day %** | Share that became trend days |
| **Avg range** | Mean `Range %` in the bucket |

The shape is the point: small gaps fill almost always, large ones frequently do
not, and the trend-day share moves the other way.

### CPR day-type matrix

Grouped by the CPR type of the **previous** session, so it can be read before
the day starts.

| Column | Computation |
|---|---|
| n | Sessions of that type |
| Trend day % | Share that became trend days |
| Fill % | Share that filled the gap |
| Up day % | Share that closed above their open |
| Avg range % | Mean intraday range as % of previous close |
| Avg gap % | Mean absolute gap |

### By CPR day type (daily OHLC)

The same grouping computed from the **daily OHLC series alone**, without the
zone sheets. It exists as a cross-check: the two tables are built by different
code paths from different inputs, so when they disagree materially the data
pipeline is at fault, not the market.

### Weekday behaviour

Trend-day, fill and up-day shares by weekday. Displayed with a caveat because
it mixes expiry effects into small per-weekday samples — an observation, not a
rule.

---

## 9. Parameters

Tuned per instrument; the defaults suit Nifty 50.

| Parameter | Default | What it controls | Suggested |
|---|---|---|---|
| `cluster_tol` | 25 pts | How close levels must be to merge | BankNifty 70, Midcap 30 |
| `zone_half_w` | 15 pts | Minimum half-width of a zone | BankNifty 40, Midcap 20 |
| `round_step` | 100 pts | Round-number spacing | BankNifty 500 |
| `zones_per_side` | 4 | R1…Rn and S1…Sn depth | |
| `break_pts` | 15 pts | Close beyond the edge that counts as a break | |
| `bounce_pts` | 45 pts | Move away that counts as a bounce | |

Every stored sheet records a **`params_hash`**. Change a parameter and new rows
carry a new hash, because outcomes scored under different definitions are not
comparable — the old rows are not silently rewritten.

---

## 10. How the data gets there

1. **Ingest** — 15-minute (and daily) candles from the broker connection, by
   the market-close job at 17:00 IST on trading weekdays, or on demand from the
   Data seeding tab. Candles are upserted on `(symbol, resolution, timestamp)`,
   so re-fetching a period repairs gaps instead of duplicating rows.
2. **Roll up** — daily OHLC per symbol, sessions with ≥20 candles only.
3. **Build** — a zone sheet from each session, stored against the *following*
   session.
4. **Score** — replay that following session's candles to set touched /
   bounced / broke / held per zone.
5. **Aggregate** — the base-rate tables above, recomputed from the stored
   observations on every request.

Steps 3–5 are deterministic and idempotent: re-running them on the same candles
reproduces the same numbers exactly.

---

## 11. Reading the output honestly

- Base rates describe **the stored sample for that symbol**, not the future.
- Always look at `n`. A 90% hold rate on 11 observations means very little.
- Compare bounce and hold against **62%**, the random-line baseline.
- Stars track how often a level is **reached**, not how often it holds.
- A fresh symbol has no history: its zones are still computed, but its base
  rates stay empty until sessions have been scored.
