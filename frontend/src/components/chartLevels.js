/**
 * chartLevels.js — zone levels drawn per session on the chart canvas.
 *
 * Every level used to be a full-width price line, so a three-session window
 * stretched each session's levels across all three days and there was no way to
 * tell which line belonged to 25 Aug and which to 26 Aug. The renderers here
 * are attached to the candle series and draw a level only across the candles of
 * the session it applies to, with that session's date stamped above its block.
 * The forward sheet for the next session is drawn in the empty space to the
 * right of the last candle, since it belongs to a session that has no bars yet.
 */
import { fmtNum, shortDate } from '../lib/hooks.js'

export const UP = '#22c55e'
export const DOWN = '#f43f5e'

/** Line colour = what the zone did that session; unscored zones use the side
 * colours the rest of the app uses (R rose / S emerald / AT amber). */
export const RESULT_COLORS = { HELD: UP, BROKE: DOWN, TOUCHED: '#f59e0b', 'NOT REACHED': '#64748b' }
export const SIDE_COLORS = { R: '#fb7185', S: '#34d399', AT: '#fbbf24' }
export const NEXT_COLOR = '#818cf8' // next session's forward sheet: brand violet
export const PDC_COLOR = '#94a3b8' // each session's previous close

const FONT = '9.5px "JetBrains Mono", ui-monospace, SFMono-Regular, monospace'
const STAMP_FONT = '10px "JetBrains Mono", ui-monospace, SFMono-Regular, monospace'
const STAMP_BG = 'rgba(9, 13, 24, 0.82)'
const STAMP_TEXT = '#cbd5e1'
const STAMP_H = 15
const ROW_H = 9 // labels closer together than this would overlap

/** Candle times are stored as Asia/Kolkata wall clock without a zone suffix.
 * lightweight-charts renders timestamps as UTC, so feeding the wall clock in
 * as UTC seconds makes the axis print market time exactly. */
export const fakeUtc = (ts) => {
  const m = String(ts).match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/)
  if (!m) return null
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) / 1000
}

export function levelColor(level, next = false) {
  if (next) return NEXT_COLOR
  if (level.result && RESULT_COLORS[level.result]) return RESULT_COLORS[level.result]
  return SIDE_COLORS[level.side] || '#94a3b8'
}

/** The candle window split into trading days, oldest first. */
export function sessionBlocks(candles) {
  const blocks = []
  let cur = null
  ;(candles || []).forEach((c) => {
    const date = String(c.ts).slice(0, 10)
    if (!cur || cur.date !== date) {
      cur = { date, from: c.ts, to: c.ts }
      blocks.push(cur)
    } else {
      cur.to = c.ts
    }
  })
  return blocks
}

/** Everything the renderers draw: one entry per session, plus the next sheet. */
export function levelModel(data) {
  const blocks = sessionBlocks(data?.candles)
  const byDate = new Map(blocks.map((b) => [b.date, b]))
  const days = (data?.day_levels || [])
    .filter((d) => byDate.has(d.date))
    .map((d) => ({
      ...byDate.get(d.date),
      tag: shortDate(d.date),
      pdc: d.basis ? d.basis.close : null,
      levels: d.levels || [],
    }))
  const last = blocks[blocks.length - 1]
  const next = data?.next_levels?.length
    ? {
        from: last ? last.to : null,
        tag: `${shortDate(data.next_session_date) || 'Next'} · next`,
        levels: data.next_levels,
      }
    : null
  return { blocks, days, next }
}

/** Attach the per-session level renderers to the candle series. Returns the
 * detach function; the chart itself is torn down with the component. */
export function attachZoneLevels(chart, series, model) {
  const timeScale = chart.timeScale()
  const bands = {
    zOrder: () => 'bottom',
    renderer: () => ({ draw: (target) => target.useMediaCoordinateSpace((s) => drawBands(s, timeScale, model)) }),
  }
  const lines = {
    zOrder: () => 'top',
    renderer: () => ({
      draw: (target) => target.useMediaCoordinateSpace((s) => drawLevels(s, timeScale, series, model)),
    }),
  }
  const primitive = { paneViews: () => [bands, lines] }
  series.attachPrimitive(primitive)
  return () => series.detachPrimitive(primitive)
}

/** The min/max price across every drawn level (and previous close), so the
 * candle series can widen its auto-scale to keep all level lines in view. */
export function levelPriceRange(model) {
  let min = Infinity
  let max = -Infinity
  const consider = (p) => {
    if (p != null && !Number.isNaN(p)) {
      min = Math.min(min, p)
      max = Math.max(max, p)
    }
  }
  model.days.forEach((d) => {
    consider(d.pdc)
    d.levels.forEach((l) => consider(l.key))
  })
  model.next?.levels.forEach((l) => consider(l.key))
  return Number.isFinite(min) ? { minValue: min, maxValue: max } : null
}

/** Horizontal span (canvas pixels) covered by one session's candles. */
function span(timeScale, from, to) {
  const bar = timeScale.options().barSpacing
  const x1 = timeScale.timeToCoordinate(fakeUtc(from))
  const x2 = timeScale.timeToCoordinate(fakeUtc(to))
  if (x1 == null || x2 == null) return null
  return { left: x1 - bar / 2, right: x2 + bar / 2 }
}

/** Alternate sessions get a faint tint so the candle groups read as days. */
function drawBands(scope, timeScale, model) {
  const ctx = scope.context
  const { width, height } = scope.mediaSize
  ctx.save()
  ctx.fillStyle = 'rgba(148, 163, 184, 0.05)'
  model.blocks.forEach((block, i) => {
    if (i % 2 === 0) return
    const s = clip(span(timeScale, block.from, block.to), width)
    if (s) ctx.fillRect(s.left, 0, s.right - s.left, height)
  })
  ctx.restore()
}

function drawLevels(scope, timeScale, series, model) {
  const ctx = scope.context
  const { width, height } = scope.mediaSize
  ctx.save()
  ctx.lineWidth = 1
  ctx.font = FONT
  // Session separators: a block of candles never blurs into the next day.
  for (let i = 1; i < model.blocks.length; i++) {
    const prev = span(timeScale, model.blocks[i - 1].from, model.blocks[i - 1].to)
    const cur = span(timeScale, model.blocks[i].from, model.blocks[i].to)
    if (!prev || !cur) continue
    const x = Math.round((prev.right + cur.left) / 2) + 0.5
    if (x < 0 || x > width) continue
    ctx.setLineDash([1.5, 3])
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.32)'
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, height)
    ctx.stroke()
  }
  model.days.forEach((day) => drawSession(ctx, timeScale, series, day, width))
  if (model.next) drawSession(ctx, timeScale, series, model.next, width, true)
  ctx.restore()
}

/** One session: its previous close and zone levels, across its own candles. */
function drawSession(ctx, timeScale, series, day, width, next = false) {
  const s = clip(next ? forwardSpan(timeScale, day.from, width) : span(timeScale, day.from, day.to), width)
  if (!s) return
  const marks = []
  if (!next && day.pdc != null) {
    const y = series.priceToCoordinate(day.pdc)
    if (y != null) {
      stroke(ctx, PDC_COLOR, [1.5, 2.5], s, y, 0.65)
      marks.push({ text: 'PDC', y, color: PDC_COLOR, align: 'left', x: s.left + 3 })
    }
  }
  day.levels.forEach((l) => {
    const y = series.priceToCoordinate(l.key)
    if (y == null) return
    const color = next ? NEXT_COLOR : levelColor(l)
    stroke(ctx, color, next ? [6, 4] : l.result ? [5, 3.5] : [2, 3], s, y, next ? 0.95 : 0.85)
    marks.push({ text: `${l.label} ${fmtNum(l.key, 2)}`, y, color, align: 'right', x: s.right - 3 })
  })
  stamp(ctx, day.tag, s)
  // A label sits just above its line; where two would overlap the lower-priority
  // one is dropped instead of being drawn on top of the other.
  let labelled = -Infinity
  marks
    .sort((a, b) => a.y - b.y)
    .forEach((m) => {
      if (m.y < STAMP_H + 9) return // the session stamp owns the top row
      if (m.align === 'right') {
        if (m.y - labelled < ROW_H) return
        labelled = m.y
      }
      ctx.textAlign = m.align
      ctx.fillStyle = m.color
      ctx.fillText(m.text, m.x, m.y - 3)
    })
}

/** The next session has no candles yet, so its sheet sits in the empty space
 * after the last bar (the chart keeps a right offset for exactly this). */
function forwardSpan(timeScale, from, width) {
  if (!from) return null
  const x = timeScale.timeToCoordinate(fakeUtc(from))
  if (x == null) return null
  return { left: x + timeScale.options().barSpacing / 2, right: width - 2 }
}

/** Keep a span inside the canvas, and drop it when it is entirely off-screen. */
function clip(s, width) {
  if (!s || s.right < 0 || s.left > width) return null
  return { left: Math.max(s.left, 0), right: Math.min(s.right, width) }
}

function stroke(ctx, color, dash, s, y, alpha) {
  ctx.setLineDash(dash)
  ctx.globalAlpha = alpha
  ctx.strokeStyle = color
  ctx.beginPath()
  ctx.moveTo(s.left, Math.round(y) + 0.5)
  ctx.lineTo(s.right, Math.round(y) + 0.5)
  ctx.stroke()
  // an end cap, so it is obvious where the level stops applying
  ctx.setLineDash([])
  ctx.fillStyle = color
  ctx.beginPath()
  ctx.arc(s.right, y, 1.4, 0, Math.PI * 2)
  ctx.fill()
  ctx.globalAlpha = 1
}

/** Session stamp in the top-right corner of a block, on a solid pill so it
 * stays readable over candles. */
function stamp(ctx, text, s) {
  if (!text || s.right - s.left < 30) return
  ctx.font = STAMP_FONT
  const w = ctx.measureText(text).width + 10
  ctx.fillStyle = STAMP_BG
  ctx.fillRect(s.right - w, 6, w, STAMP_H)
  ctx.fillStyle = STAMP_TEXT
  ctx.textAlign = 'right'
  ctx.fillText(text, s.right - 5, 17)
  ctx.font = FONT
}
