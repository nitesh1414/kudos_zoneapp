import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarRange, CandlestickChart, Expand, Minimize2, RefreshCw, RotateCcw } from 'lucide-react'
import { ColorType, CrosshairMode, TickMarkType, createChart } from 'lightweight-charts'
import { useApi, fmtDate, fmtNum, shortDate } from '../lib/hooks.js'
import { endpoints } from '../lib/api.js'
import { useSymbol, withSymbol } from '../lib/symbol.jsx'
import { Badge, Button, Card, Dot, Empty, ErrorState, Input, Skeleton } from './ui.jsx'
import {
  DOWN, NEXT_COLOR, RESULT_COLORS, UP, attachZoneLevels, fakeUtc, levelColor, levelModel, levelPriceRange,
} from './chartLevels.js'

const GRID = 'rgba(148, 163, 184, 0.06)'
const AXIS_BORDER = 'rgba(148, 163, 184, 0.16)'
const AXIS_TEXT = '#8b96ad'
/** Bars of empty space kept on the right: that is where the next session's
 * forward sheet is drawn, so it needs room of its own. */
const NEXT_OFFSET = 12

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
    const model = levelModel(data)

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
      rightPriceScale: {
        borderColor: AXIS_BORDER,
        scaleMargins: { top: 0.05, bottom: 0.18 },
        entireTextOnly: true,
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: AXIS_BORDER,
        barSpacing: 7,
        rightOffset: model.next ? NEXT_OFFSET : 3,
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
        priceFormatter: (price) => Number(price).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      },
    })

    const levelRange = levelPriceRange(model)
    const candles = chart.addCandlestickSeries({
      upColor: UP,
      wickUpColor: 'rgba(34, 197, 94, 0.8)',
      downColor: DOWN,
      wickDownColor: 'rgba(244, 63, 94, 0.8)',
      borderVisible: false,
      priceLineVisible: false,
      priceFormat: { type: 'price', precision: 2, minMove: 0.05 },
      // Widen the visible range to include every drawn level, so a line above
      // the candle range is scaled into view instead of being clipped.
      autoscaleInfoProvider: (base) => {
        const original = base()
        if (!levelRange) return original
        const min = Math.min(levelRange.minValue, original?.priceRange?.minValue ?? levelRange.minValue)
        const max = Math.max(levelRange.maxValue, original?.priceRange?.maxValue ?? levelRange.maxValue)
        return { priceRange: { minValue: min, maxValue: max } }
      },
    })
    const bars = data.candles.map((c) => ({
      time: fakeUtc(c.ts), open: +c.o, high: +c.h, low: +c.l, close: +c.c,
    }))
    candles.setData(bars)

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
        color: +c.c >= +c.o ? 'rgba(34, 197, 94, 0.28)' : 'rgba(244, 63, 94, 0.28)',
      })),
    )
    chart.priceScale('').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } })

    // Every level is drawn by chartLevels.js as a segment across its own
    // session's candles only — a full-width line per zone per session made the
    // window unreadable once more than one day was on screen.
    const detachLevels = attachZoneLevels(chart, candles, model)

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
      detachLevels()
      chart.remove()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  return (
    <div className="relative h-full min-h-[240px]">
      <div ref={host} className="absolute inset-0" />
      <div className="num pointer-events-none absolute bottom-2 left-2 z-10 flex flex-wrap items-center gap-x-2.5 rounded-lg bg-ink-950/70 px-2 py-1 text-[10.5px] text-slate-400 ring-1 ring-white/8 backdrop-blur-sm">
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

const QUICK = [
  ['latest', 'Latest'],
  ['today', 'Today'],
  ['next', 'Next'],
  ['prev', 'Prev'],
]

function ZoneChip({ level, next = false }) {
  const color = levelColor(level, next)
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-ink-900/70 px-2 py-1 ring-1 ring-white/8">
      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      <span className="num text-[10.5px] font-semibold text-slate-200">{level.label}</span>
      <span className="num text-[10.5px] text-slate-400">{fmtNum(level.key, 2)}</span>
      {level.result && <span style={{ color }} className="num text-[10px] font-semibold">{level.result}</span>}
    </span>
  )
}

/** Sessions whose zones are listed as chips below the chart — the same ones
 * the chart labels session by session. */
const LEGEND_SESSIONS = 6

/** The chips mirror the chart: one row per session, so every chip can be
 * matched to the segment drawn above it. A window too long to label session by
 * session falls back to the session the chart is centred on. */
function ZoneLegend({ rows, data }) {
  if (rows.length < 2)
    return (
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {(data.levels || []).map((l) => <ZoneChip key={`r-${l.label}`} level={l} />)}
        {(data.next_levels || []).map((l) => <ZoneChip key={`n-${l.label}`} level={l} next />)}
      </div>
    )
  return (
    <div className="mt-2.5 space-y-1.5">
      {rows.map((d) => (
        <div key={d.date} className="flex flex-wrap items-center gap-1.5">
          <span className="num w-14 shrink-0 text-[10.5px] font-semibold text-slate-300">{shortDate(d.date)}</span>
          {d.levels.map((l) => <ZoneChip key={`${d.date}-${l.label}`} level={l} />)}
        </div>
      ))}
      {data.next_levels?.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="num w-14 shrink-0 text-[10.5px] font-semibold text-indigo-300">
            {shortDate(data.next_session_date) || 'Next'}
          </span>
          {data.next_levels.map((l) => <ZoneChip key={`n-${l.label}`} level={l} next />)}
        </div>
      )}
    </div>
  )
}

export default function SessionChart() {
  const { symbol } = useSymbol()
  const [pending, setPending] = useState({ from: '', to: '' })
  const [range, setRange] = useState(null) // applied {from,to}; null = quick view
  const [quick, setQuick] = useState('latest')
  const [full, setFull] = useState(false)

  const query = useMemo(() => {
    if (range) {
      if (!range.from || range.from === range.to) return `date=${range.to || range.from}`
      return `date_from=${range.from}&date_to=${range.to}`
    }
    return quick && quick !== 'latest' ? `view=${quick}` : ''
  }, [range, quick])

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
    setQuick('latest')
  }

  const reset = () => {
    setPending({ from: '', to: '' })
    setRange(null)
    setQuick('latest')
  }

  const applyQuick = (key) => {
    setQuick(key)
    setRange(null)
    setPending({ from: '', to: '' })
  }

  // The chips and the outcome counts cover the same sessions: the ones the
  // chart labels session by session.
  const legendRows = (data?.day_levels || []).slice(-LEGEND_SESSIONS)
  const legendChips = legendRows.length > 1 ? legendRows.flatMap((d) => d.levels) : data?.levels || []
  const results = {}
  legendChips.forEach((l) => {
    if (l.result) results[l.result] = (results[l.result] || 0) + 1
  })
  const hasResults = legendChips.some((l) => l.result)
  const isTodayOpen = ['today-open', 'today-closed'].includes(data?.next_session_kind)
  const isTodayOpenView = data?.view === 'today' && data?.date === data?.today && data?.session_complete === false
  const title = range
    ? `Session chart · ${fmtDate(range.to || range.from)}`
    : quick === 'today' ? 'Session chart · Today'
    : quick === 'next' ? 'Session chart · Next possible session'
    : quick === 'prev' ? 'Session chart · Previous session'
    : 'Session chart'

  const subtitle = data
    ? isTodayOpenView
      ? `Today ${shortDate(data.today)} · market running · zones from ${shortDate(data.last_complete_date)} close, no result yet`
      : `Result ${fmtDate(data.date)}${data.last_complete_date ? ` · last completed ${shortDate(data.last_complete_date)}` : ''}${data.next_session_date ? ` · next possible ${shortDate(data.next_session_date)}${isTodayOpen ? ` (today${data.next_session_kind === 'today-open' ? ', market not closed yet' : ', awaiting close data'})` : ''}` : ''}`
    : '15-minute candles with each session’s zones drawn only across its own candles. The violet sheet to the right is the next possible session; results are listed per session below the chart.'

  return (
    <Card
      title={title}
      icon={CandlestickChart}
      subtitle={subtitle}
      className={full ? 'fixed inset-0 z-[70] flex flex-col overflow-hidden' : ''}
      bodyClass={full ? 'flex min-h-0 flex-1 flex-col overflow-y-auto' : ''}
      style={full ? { borderRadius: 0 } : undefined}
      right={
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" icon={RefreshCw} onClick={reload} title="Fetch the latest data now">
            <span className="hidden sm:inline">Refresh</span>
          </Button>
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
        </div>
      }
    >
      <form onSubmit={apply} className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-xl bg-ink-900/60 p-1 ring-1 ring-white/10">
          {QUICK.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => applyQuick(key)}
              className={`rounded-lg px-2.5 py-1.5 text-[11px] font-semibold transition active:scale-[.98] ${
                !range && quick === key ? 'bg-brand-600 text-white shadow-lg shadow-brand-600/25' : 'text-slate-400 hover:bg-white/10 hover:text-slate-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="hidden h-5 w-px bg-white/10 sm:block" />
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
        {(range || quick !== 'latest') && (
          <Button type="button" variant="subtle" size="sm" icon={RotateCcw} onClick={reset}>
            Reset
          </Button>
        )}
        {data && (
          <div className="ml-auto flex flex-wrap items-center gap-1.5 text-[11px]">
            {range ? (
              <Badge tone="brand">
                {data.mode === 'day' ? fmtDate(data.date) : `${fmtDate(data.date_from)} → ${fmtDate(data.date_to)}`}
              </Badge>
            ) : quick === 'prev' ? (
              <Badge tone="brand">Previous · {fmtDate(data.date)}</Badge>
            ) : isTodayOpenView ? (
              <Badge tone="warn">Today · market running</Badge>
            ) : (
              <Badge tone="brand">Last completed {shortDate(data.last_complete_date)}</Badge>
            )}
            {data.day_type && <Badge tone="neutral">{data.day_type} CPR</Badge>}
            {data.next_levels?.length > 0 && (
              <Badge tone={isTodayOpen ? 'warn' : 'brand'}>
                {isTodayOpen
                  ? `Today · ${data.next_session_kind === 'today-open' ? 'market not closed' : 'awaiting close'}`
                  : 'Next'}{' '}
                {shortDate(data.next_session_date)}
              </Badge>
            )}
            {data.truncated && <Badge tone="warn">Window capped (max 62 sessions)</Badge>}
          </div>
        )}
      </form>

      {loading && <Skeleton className="h-[460px] rounded-2xl" />}
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
          <div className={full ? 'min-h-0 flex-1' : 'h-[460px]'}>
            <ChartCanvas key={`${symbol}:${data.date_from}:${data.date_to}:${data.resolution}:${data.view}`} data={data} />
          </div>

          <ZoneLegend rows={legendRows} data={data} />

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
                Next {isTodayOpen ? 'today' : 'session'} ({shortDate(data.next_session_date) || 'upcoming'})
              </span>
            )}
            <span className="inline-flex items-center gap-1.5">
              <Dot tone="neutral" /> PDC · previous close
            </span>
            <span className="inline-flex items-center gap-1.5 text-slate-600">
              Each level is drawn across its own session only
            </span>
            <span className="ml-auto">
              {fmtNum(data.candles.length)} candles · zones for {fmtDate(data.date)} from {data.basis ? fmtDate(data.basis.date) : '—'} close
              {data.day_levels_capped && ' · level lines limited to the last 20 sessions'}
            </span>
          </div>
        </>
      )}
    </Card>
  )
}
