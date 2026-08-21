import { useMemo } from 'react'
import { marked } from 'marked'
import { BookOpen, ExternalLink, Sliders } from 'lucide-react'
import { endpoints } from '../../lib/api.js'
import { useApi, fmtDateTime } from '../../lib/hooks.js'
import { Badge, Card, ErrorState, Skeleton } from '../../components/ui.jsx'

marked.setOptions({ gfm: true, breaks: false })

const PARAM_HELP = {
  cluster_tol: 'How close two levels must be to merge into one zone',
  zone_half_w: 'Minimum half-width of a zone around its midpoint',
  round_step: 'Spacing of the round-number levels',
  zones_per_side: 'How many R and S zones the sheet carries',
  round_span: 'How many round numbers each way from the close',
  break_pts: 'A close this far beyond the far edge counts as a break',
  bounce_pts: 'A move this far away from the zone counts as a bounce',
}

/** The strategy document, rendered from the same docs/METHODOLOGY.md that
 *  ships in the repository — one source of truth, no drift. */
export default function Methodology() {
  const { data, error, loading, reload } = useApi(endpoints.methodology)
  const html = useMemo(() => (data?.markdown ? marked.parse(data.markdown) : ''), [data?.markdown])

  if (loading) return <Skeleton className="h-[60vh] rounded-2xl" />
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={reload} />
      </Card>
    )

  return (
    <div className="space-y-4">
      <Card
        title="Zone parameters in force on this installation"
        icon={Sliders}
        subtitle="The document below explains what each one does. Changing a parameter starts a new params_hash, because outcomes scored under different definitions are not comparable."
      >
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          {Object.entries(data.params || {}).map(([key, value]) => (
            <div key={key} className="rounded-xl bg-white/4 px-3.5 py-3 ring-1 ring-white/8">
              <p className="num text-[11px] tracking-wide text-slate-500">{key}</p>
              <p className="num mt-0.5 text-lg font-bold text-slate-50">{value}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{PARAM_HELP[key] || ''}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(data.day_types || {}).map(([type, rule]) => (
            <Badge key={type} tone={type === 'NORMAL' ? 'brand' : type === 'NARROW' ? 'warn' : 'up'}>
              {type}: {rule}
            </Badge>
          ))}
        </div>
      </Card>

      <Card
        title="Strategy & definitions"
        icon={BookOpen}
        subtitle="Every metric in the product: what it is, how it is calculated and on what basis."
        right={
          <span className="hidden items-center gap-1.5 text-[11px] text-slate-500 sm:flex">
            <ExternalLink size={12} /> docs/METHODOLOGY.md · {fmtDateTime(data.updated_at)}
          </span>
        }
      >
        <article className="markdown scrollbar-thin max-w-none" dangerouslySetInnerHTML={{ __html: html }} />
      </Card>
    </div>
  )
}
