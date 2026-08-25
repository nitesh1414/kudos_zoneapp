import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarRange, CandlestickChart, Expand, Minimize2, RotateCcw } from 'lucide-react'
import { ColorType, CrosshairMode, LineStyle, TickMarkType, createChart } from 'lightweight-charts'
import { useApi, fmtDate, fmtNum } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { useSymbol, withSymbol } from '../lib/symbol.jsx'
import { Badge, Button, Card, Dot, Empty, ErrorState, Input, Skeleton } from './ui.jsx'

const UP = '#22c55e'
const DOWN = '#f43f5e'

/** Line colour = what the zone did that session; unscored zones use the
 * side colours the rest of the app uses (R rose / S emerald / AT amber). */
const RESULT_COLORS = { HELD: UP, BROKE: DOWN, TOUCHED: '#f59e0b', 'NOT REACHED': '#64748b' }
const SIDE_COLORS = { R: '#fb7185', S: '#34d399', AT: '#fbbf24' }
const NEXT_COLOR = '#818cf8' // next session's forward sheet: brand violet, dashed
const GRID = 'rgba(148, 163, 184, 0.07)'
const AXIS_BORDER = 'rgba(148, 163, 184, 0.16)'
const AXIS_TEXT = '#7b87a1'

/** Candle times are stored as Asia/Kolkata wall clock without a zone suffix.
 * Lightweight-charts renders timestamps as UTC, so feeding the wall clock in
 * as UTC seconds makes the axis print market time exactly. */
const fakeUtc = (ts) => {
  const m = String(ts).match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/)
  if (!m) return null
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) / 1000
}

function levelColor(level, next) {
  if (next) return NEXT_COLOR
  if (level.result && RESULT_COLORS[level.result]) return RESULT_COLORS[level.result]
  return SIDE_COLORS[level.side] || '#94a3b8'
}

function drawLevel(series, level, next = false) {
  const color = levelColor(level, next)
  const edge = `${color}45` // faint band edges — the pair reads as the zone
  series.createPriceLine({ price: level.lo, color: edge, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: '' })
  series.createPriceLine({ price: level.hi, color: edge, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: '' })
  series.createPriceLine({
    price: level.key,
    color,
    lineWidth: 2,
    lineStyle: next ? LineStyle.Dashed : LineStyle.Solid,
    axisLabelVisible: true,
    title: next ? `${level.label} · next` : level.result ? `${level.label} · ${level.result}` : level.label,
  })
}

/** The lightweight-charts instance itself. Recreated whenever the payload changes. */
function ChartCanvas({ data }) {
  const host = useRef(null)
  const legendDate = useRef(null)
  const legendO = useRef(null)
  const legendH = useRef(null)
  const legendL = useRef(null)
  const legendC = useRef(null)
  const legendV = useRef(null)

  useEffect(() => {
    const el = host.current
    if (!el || !data?.candles?.length) return undefined

    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: AXIS_TEXT,
        fontSize: 11,
        fontFamily: 'JetBrains Mono, ui-monospace, monospace',
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: AXIS_BORDER },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: AXIS_BORDER,
        tickMarkFormatter: (time, type) => {
          const d = new Date(time * 1000)
          if (type <= TickMarkType.DayOfMonth)
            return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' })
          return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' })
        },
      },
      localization: {
        locale: 'en-IN',
        timeFormatter: (time) => {
          const d = new Date(time * 1000)
          const day = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' })
          const hm = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' })
          return `${day} · ${hm}`
        },
      },
    })

    const candles = chart.addCandlestickSeries({
      upColor: UP,
      wickUpColor: 'rgba(34, 197, 94, 0.85)',
      downColor: DOWN,
      wickDownColor: 'rgba(244, 63, 94, 0.85)',
      borderVisible: false,
      priceLineVisible: false,
    })
    const bars = data.candles.map((c) => ({
      time: fakeUtc(c.ts), open: +c.o, high: +c.h, low: +c.l, close: +c.c,
    }))
    candles.setData(bars)
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } })

    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    volume.setData(
      data.candles.map((c) => ({
        time: fakeUtc(c.ts),
        value: Number(c.v) || 0,
        color: +c.c >= +c.o ? 'rgba(34, 197, 94, 0.30)' : 'rgba(244, 63, 94, 0.30)',
      })),
    )
    chart.priceScale('').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    if (data.basis?.close)
      candles.createPriceLine({
        price: +data.basis.close,
        color: '#64748b',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'PDC',
      })
    ;(data.levels || []).forEach((l) => drawLevel(candles, l, false))
    ;(data.next_levels || []).forEach((l) => drawLevel(candles, l, true))

    chart.timeScale().fitContent()

    // TradingView-style OHLCV legend that follows the crosshair.
    const paint = (b, when, vol) => {
      if (!b) return
      const d = new Date(when * 1000)
      if (legendDate.current)
        legendDate.current.textContent = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' }) +
          ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' })
      if (legendO.current) legendO.current.textContent = fmtNum(b.open, 2)
      if (legendH.current) legendH.current.textContent = fmtNum(b.high, 2)
      if (legendL.current) legendL.current.textContent = fmtNum(b.low, 2)
      if (legendC.current) {
        legendC.current.textContent = fmtNum(b.close, 2)
        legendC.current.parentElement.style.color = b.close >= b.open ? UP : DOWN
      }
      if (legendV.current) legendV.current.textContent = vol != null ? fmtNum(vol) : ''
    }
    const last = bars[bars.length - 1]
    const lastVol = Number(data.candles[data.candles.length - 1].v) || 0
    paint(last, last.time, lastVol)
    chart.subscribeCrosshairMove((param) => {
      const b = param?.seriesData?.get(candles)
      if (b) paint(b, param.time, param.seriesData?.get(volume)?.value)
    })

    const ro = new ResizeObserver(() => {
      if (el.clientWidth && el.clientHeight)
        chart.applyOptions({ width: el.clientWidth, height: el.clientHeight })
    })
    ro.observe(el)
    return () => {
      ro.disconnect()
      chart.remove()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  return (
    <div className="relative h-full min-h-[220px]">
      <div ref={host} className="absolute inset-0" />
      <div className="num pointer-events-none absolute top-1.5 left-2 z-10 flex flex-wrap items-center gap-x-2.5 rounded-lg bg-ink-950/60 px-2 py-1 text-[10.5px] text-slate-400 ring-1 ring-white/8 backdrop-blur-sm">
        <span ref={legendDate} className="text-slate-500" />
        <span>O <b ref={legendO} className="text-slate-200" /></span>
        <span>H <b ref={legendH} className="text-emerald-400" /></span>
        <span>L <b ref={legendL} className="text-rose-400" /></span>
        <span>C <b ref={legendC} className="text-slate-200" /></span>
        <span>V <b ref={legendV} className="text-slate-500" /></span>
      </div>
    </div>
  )
}

const LEGEND_ROWS = [
  ['HELD', 'Held'],
  ['TOUCHED', 'Touched'],
  ['BROKE', 'Broke'],
  ['NOT REACHED', 'Not reached'],
]

export default function SessionChart() {
  const { symbol } = useSymbol()
  const [pending, setPending] = useState({ from: '', to: '' })
  const [range, setRange] = useState(null) // applied {from,to}; null = default view
  const [full, setFull] = useState(false)

  const query = useMemo(() => {
    if (!range) return ''
    if (!range.from || range.from === range.to) return `date=${range.to || range.from}`
    return `date_from=${range.from}&date_to=${range.to}`
  }, [range])

  const { data, error, loading, reload } = useApi(
    () => withSymbol(query ? `${endpoints.chartSession}?${query}` : endpoints.chartSession, symbol),
    [symbol, query],
  )

  useEffect(() => {
    if (!full) return undefined
    const onKey = (e) => e.key === 'Escape' && setFull(false)
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [full])

  const apply = (e) => {
    e.preventDefault()
    let { from, to } = pending
    if (!from && !to) return setRange(null)
    if (!from) from = to
    if (!to) to = from
    if (from > to) [from, to] = [to, from]
    setRange({ from, to })
  }

  const reset = () => {
    setPending({ from: '', to: '' })
    setRange(null)
  }

  const results = {}
  ;(data?.levels || []).forEach((l) => {
    if (l.result) results[l.result] = (results[l.result] || 0) + 1
  })
  const hasResults = (data?.levels || []).some((l) => l.result)
  const title = range
    ? `Session chart · ${fmtDate(range.to || range.from)}`
    : 'Session chart'

  return (
    <Card
      title={title}
      icon={CandlestickChart}
      subtitle="15-minute candles with the session zones drawn as levels. Solid lines are that session's zones (colour = result), dashed violet = next session's levels."
      className={full ? 'fixed inset-0 z-[70] flex flex-col overflow-hidden' : ''}
      bodyClass={full ? 'flex min-h-0 flex-1 flex-col overflow-y-auto' : ''}
      style={full ? { borderRadius: 0 } : undefined}
      right={
        <Button
          variant="ghost"
          size="sm"
          icon={full ? Minimize2 : Expand}
          onClick={() => setFull((v) => !v)}
          title={full ? 'Exit full screen (Esc)' : 'Full screen'}
          aria-label={full ? 'Exit full screen' : 'Full screen'}
        >
          <span className="hidden sm:inline">{full ? 'Exit' : 'Full screen'}</span>
        </Button>
      }
    >
      <form onSubmit={apply} className="mb-3 flex flex-wrap items-center gap-2">
        <CalendarRange size={15} className="text-slate-500" />
        <div className="w-36 sm:w-40">
          <Input
            type="date"
            aria-label="From date"
            className="px-2.5 py-1.5 text-xs"
            value={pending.from}
            min={data?.first_date || undefined}
            max={pending.to || data?.last_date || undefined}
            onChange={(e) => setPending((p) => ({ ...p, from: e.target.value }))}
          />
        </div>
        <span className="text-xs text-slate-600">→</span>
        <div className="w-36 sm:w-40">
          <Input
            type="date"
            aria-label="To date"
            className="px-2.5 py-1.5 text-xs"
            value={pending.to}
            min={pending.from || data?.first_date || undefined}
            max={data?.last_date || undefined}
            onChange={(e) => setPending((p) => ({ ...p, to: e.target.value }))}
          />
        </div>
        <Button type="submit" size="sm" variant="ghost">
          Apply
        </Button>
        {range && (
          <Button type="button" variant="subtle" size="sm" icon={RotateCcw} onClick={reset}>
            Reset
          </Button>
        )}
        {data && (
          <div className="ml-auto flex flex-wrap items-center gap-1.5 text-[11px]">
            <Badge tone="brand">
              {data.mode === 'day' ? fmtDate(data.date) : `${fmtDate(data.date_from)} → ${fmtDate(data.date_to)}`}
            </Badge>
            {data.day_type && <Badge tone="neutral">{data.day_type} CPR</Badge>}
            {data.next_levels?.length > 0 && <Badge tone="brand">Next-session levels</Badge>}
            {data.truncated && <Badge tone="warn">Window capped (max 62 sessions)</Badge>}
          </div>
        )}
      </form>

      {loading && <Skeleton className="h-[420px] rounded-2xl" />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && data.candles.length === 0 && (
        <Empty
          icon={CandlestickChart}
          title="No candles for this window"
          hint="Pick dates between the first and last stored sessions, or seed more history in the admin panel."
        />
      )}

      {data && data.candles.length > 0 && (
        <>
          <div className={full ? 'min-h-0 flex-1' : 'h-[420px]'}>
            <ChartCanvas key={`${symbol}:${data.date_from}:${data.date_to}:${data.resolution}`} data={data} />
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-white/5 pt-2.5 text-[11px] text-slate-500">
            {hasResults &&
              LEGEND_ROWS.filter(([k]) => results[k]).map(([k, label]) => (
                <span key={k} className="inline-flex items-center gap-1.5">
                  <span className="num inline-block h-0.5 w-5 rounded-full" style={{ backgroundColor: RESULT_COLORS[k] }} />
                  {label}
                  {results[k] > 1 ? ` ×${results[k]}` : ''}
                </span>
              ))}
            {data.next_levels?.length > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block h-0.5 w-5 rounded-full"
                  style={{ background: `repeating-linear-gradient(90deg, ${NEXT_COLOR} 0 4px, transparent 4px 7px)` }}
                />
                Next session
              </span>
            )}
            <span className="inline-flex items-center gap-1.5">
              <Dot tone="neutral" /> PDC · previous close
            </span>
            <span className="ml-auto">
              {fmtNum(data.candles.length)} candles · zones for {fmtDate(data.date)} from {data.basis ? fmtDate(data.basis.date) : '—'} close
            </span>
          </div>
        </>
      )}
    </Card>
  )
}
