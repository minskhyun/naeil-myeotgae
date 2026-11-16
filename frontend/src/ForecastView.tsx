import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, PREP_MODES, SIGNAL_LABELS, type ForecastRow, type Warning } from './api'
import { useJob } from './useJob'

// 예상 범위 막대: p10~p90 구간과 예상 판매량(점)
function RangeBar({ row, max }: { row: ForecastRow; max: number }) {
  const pct = (v: number) => `${Math.min(100, (v / max) * 100)}%`
  return (
    <div className="mt-3">
      <div className="relative h-2 rounded-full bg-stone-100">
        <div
          className="absolute h-2 rounded-full bg-orange-200"
          style={{ left: pct(row.p10), width: `calc(${pct(row.p90)} - ${pct(row.p10)})` }}
        />
        <div
          className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-orange-500 shadow"
          style={{ left: pct(row.pred) }}
        />
      </div>
      <div className="mt-1 flex justify-between text-xs text-stone-500">
        <span>예상 범위 {Math.round(row.p10)}~{Math.round(row.p90)}개</span>
      </div>
    </div>
  )
}

function MenuCard({ row, max }: { row: ForecastRow; max: number }) {
  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-stone-900">{row.menu}</h3>
        {row.prep_qty !== null && (
          <span className="shrink-0 rounded-full bg-orange-50 px-3 py-1 text-sm font-semibold text-orange-700">
            준비 {row.prep_qty}개
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        <span className="text-4xl font-bold tracking-tight text-stone-900">{Math.round(row.pred)}</span>
        <span className="text-stone-500">개 예상</span>
      </div>
      <RangeBar row={row} max={max} />
      {row.reasons.length > 0 && (
        <ul className="mt-4 space-y-1.5 border-t border-stone-100 pt-3">
          {row.reasons.map((r) => (
            <li key={r.signal} className="flex items-start gap-2 text-sm">
              <span
                className={`mt-0.5 shrink-0 rounded px-1.5 text-xs font-semibold ${
                  r.effect_pct < 0 ? 'bg-sky-50 text-sky-700' : 'bg-rose-50 text-rose-700'
                }`}
              >
                {r.effect_pct > 0 ? '+' : ''}
                {Math.round(r.effect_pct)}%
              </span>
              <span className="text-stone-600">
                {r.text}
                {r.source_url && !r.source_url.includes('#') && (
                  <a href={r.source_url} target="_blank" rel="noreferrer" className="ml-1 text-orange-600 hover:underline">
                    출처
                  </a>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function WarningCard({ w }: { w: Warning }) {
  const scope = w.menu_scope.includes('*') ? '모든 메뉴' : w.menu_scope.join(', ')
  return (
    <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5">
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-amber-800">
        <span>⚠ {w.situation_type}</span>
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs">손님 {w.direction}</span>
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs">영향 {w.strength}</span>
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-xs">{scope}</span>
      </div>
      <p className="mt-2 text-stone-800">{w.message}</p>
      {w.evidence.map((e, i) => (
        <p key={i} className="mt-2 text-sm text-stone-600">
          근거: “{e.quote}”{' '}
          <a href={e.source_url} target="_blank" rel="noreferrer" className="text-amber-700 hover:underline">
            원문 보기
          </a>
        </p>
      ))}
      <p className="mt-3 text-xs text-stone-500">AI가 원문을 읽고 쓴 안내입니다. 예상 판매량 숫자는 바꾸지 않습니다.</p>
    </div>
  )
}

export function ForecastView({ storeId, prepMode }: { storeId: string; prepMode: string }) {
  const { data, error, isLoading } = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) })
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const job = useJob(jobId)
  const changing = job?.status === 'running'

  if (isLoading) return <p className="text-stone-500">불러오는 중…</p>
  if (error || !data) return <p className="text-rose-600">{(error as Error)?.message ?? '예측이 없습니다.'}</p>

  const rows = [...data.rows].sort((a, b) => b.pred - a.pred)
  const max = Math.max(...rows.map((r) => r.p90)) * 1.1
  const used = data.signals_used.filter((s) => SIGNAL_LABELS[s]).map((s) => SIGNAL_LABELS[s])

  const choose = async (mode: string) => {
    setJobError(null)
    try {
      setJobId((await api.setPrepMode(storeId, mode)).job_id)
    } catch (e) {
      setJobError((e as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-stone-900">{rows[0]?.date} 메뉴별 예상</h2>
          <p className="mt-1 text-sm text-stone-500">
            {used.length ? `반영한 주변 정보: ${used.join(' · ')}` : '판매 기록만으로 예측했어요 (주변 정보는 예측을 더 정확하게 만들지 못해 쓰지 않음)'}
          </p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-stone-500">준비 방식 {changing && '· 다시 계산 중…'}</p>
          <div className="inline-flex rounded-xl border border-stone-200 bg-white p-1">
            {PREP_MODES.map((m) => (
              <button
                key={m}
                disabled={changing}
                onClick={() => choose(m)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  m === prepMode ? 'bg-orange-500 text-white' : 'text-stone-600 hover:bg-stone-100'
                } disabled:opacity-50`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      </div>
      {(jobError || job?.status === 'error') && <p className="text-sm text-rose-600">{jobError ?? job?.error}</p>}

      {data.warnings.length > 0 && (
        <div className="space-y-3">
          {data.warnings.map((w, i) => (
            <WarningCard key={i} w={w} />
          ))}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((r) => (
          <MenuCard key={r.menu} row={r} max={max} />
        ))}
      </div>
      <p className="text-xs text-stone-400">예측 만든 시각 {data.generated_at.replace('T', ' ')}</p>
    </div>
  )
}
