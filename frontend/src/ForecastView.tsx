import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, PREP_MODES, type ForecastRow, type Warning } from './api'
import { fmtDate, fmtTime, shortReason, SIGNAL_LABELS } from './format'
import { useJob } from './useJob'

// 예상 범위 그림: 가는 선 위에 범위(굵은 선)와 예상값(눈금)
function Range({ row, max }: { row: ForecastRow; max: number }) {
  const x = (v: number) => `${Math.min(100, (v / max) * 100)}%`
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-3 w-28 shrink-0" aria-hidden>
        <div className="absolute top-1/2 h-px w-full bg-rule" />
        <div className="absolute top-1/2 h-1 -translate-y-1/2 bg-ink/25" style={{ left: x(row.p10), width: `calc(${x(row.p90)} - ${x(row.p10)})` }} />
        <div className="absolute top-0 h-3 w-0.5 -translate-x-1/2 bg-ink" style={{ left: x(row.pred) }} />
      </div>
      <span className="text-sm text-muted tabular-nums">
        {Math.round(row.p10)}–{Math.round(row.p90)}
      </span>
    </div>
  )
}

// AI 주의 안내 한 건: 상황 · 안내 문장 · 원문 인용과 링크
function Notice({ w }: { w: Warning }) {
  const scope = w.menu_scope.includes('*') ? '전체 메뉴' : w.menu_scope.join(', ')
  return (
    <section className="border-l-4 border-warn bg-warn-soft px-5 py-4">
      <p className="text-sm font-semibold text-warn">
        주의 · {w.situation_type} — 손님 {w.direction} 가능 ({scope}, 영향 {w.strength})
      </p>
      <p className="mt-1.5 text-[17px] leading-relaxed">{w.message}</p>
      {w.evidence.map((e, i) => (
        <blockquote key={i} className="mt-2 border-l border-warn/40 pl-3 text-sm leading-relaxed text-muted">
          {e.quote}{' '}
          <a href={e.source_url} target="_blank" rel="noreferrer" className="whitespace-nowrap text-warn underline underline-offset-2">
            원문
          </a>
        </blockquote>
      ))}
    </section>
  )
}

export function ForecastView({ storeId, prepMode, readOnly = false }: { storeId: string; prepMode: string; readOnly?: boolean }) {
  const { data, error, isLoading } = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) })
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const job = useJob(jobId)
  const changing = job?.status === 'running'

  if (isLoading) return <p className="text-muted">불러오는 중…</p>
  if (error || !data) return <p className="text-up">{(error as Error)?.message ?? '예측이 없습니다.'}</p>

  const rows = [...data.rows].sort((a, b) => b.pred - a.pred)
  const max = Math.max(...rows.map((r) => r.p90)) * 1.05
  const used = data.signals_used.filter((s) => SIGNAL_LABELS[s]).map((s) => SIGNAL_LABELS[s])
  const totalPrep = rows.reduce((s, r) => s + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(rows.reduce((s, r) => s + r.pred, 0))

  const choose = async (mode: string) => {
    if (mode === prepMode) return
    setJobError(null)
    try {
      setJobId((await api.setPrepMode(storeId, mode)).job_id)
    } catch (e) {
      setJobError((e as Error).message)
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="text-sm text-muted">내일 준비표</p>
          <h2 className="mt-0.5 text-3xl font-bold tracking-tight">{fmtDate(rows[0].date)}</h2>
          <p className="mt-2 text-sm text-muted">
            {used.length ? <>반영한 주변 정보 — {used.join(', ')}</> : '주변 정보 없이 판매 기록만으로 예측했습니다'}
          </p>
        </div>
        <div>
          <p className="mb-1.5 text-sm text-muted">
            준비 기준 {changing && <span className="text-accent">· 다시 계산 중</span>}
            {readOnly && <span className="text-faint"> · 시연용 화면에서는 바꿀 수 없음</span>}
          </p>
          <div className="flex border border-ink/80" role="group" aria-label="준비 기준">
            {PREP_MODES.map((m, i) => (
              <button
                key={m}
                disabled={changing || readOnly}
                onClick={() => choose(m)}
                aria-pressed={m === prepMode}
                className={`px-3.5 py-1.5 text-sm ${i > 0 ? 'border-l border-ink/80' : ''} ${
                  m === prepMode ? 'bg-ink font-semibold text-white' : 'bg-sheet hover:bg-paper'
                } ${readOnly ? 'disabled:cursor-not-allowed' : 'disabled:cursor-wait'}`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      </div>
      {(jobError || job?.status === 'error') && <p className="text-sm text-up">{jobError ?? job?.error}</p>}

      {data.warnings.map((w, i) => (
        <Notice key={i} w={w} />
      ))}

      <section className="border border-rule bg-sheet">
        <div className="hidden grid-cols-[minmax(9rem,1.3fr)_5.5rem_5.5rem_12rem_minmax(10rem,1.5fr)] gap-4 border-b border-rule px-5 py-2.5 text-sm text-muted md:grid">
          <span>메뉴</span>
          <span className="text-right">준비</span>
          <span className="text-right">예상</span>
          <span>예상 범위</span>
          <span>평소와 다른 점</span>
        </div>
        <ol>
          {rows.map((r) => (
            <li
              key={r.menu}
              className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 border-b border-rule px-5 py-3.5 last:border-b-0 md:grid-cols-[minmax(9rem,1.3fr)_5.5rem_5.5rem_12rem_minmax(10rem,1.5fr)] md:items-center"
            >
              <span className="text-[17px] font-semibold">{r.menu}</span>
              <span className="text-right text-2xl font-bold text-accent tabular-nums md:text-xl">
                {r.prep_qty ?? '–'}
                <span className="ml-0.5 text-sm font-normal text-muted md:hidden">개 준비</span>
              </span>
              <span className="col-span-2 text-sm text-muted tabular-nums md:col-span-1 md:text-right md:text-base md:text-ink">
                <span className="md:hidden">예상 </span>
                {Math.round(r.pred)}
                <span className="md:hidden">
                  {' '}· 범위 {Math.round(r.p10)}–{Math.round(r.p90)}
                </span>
              </span>
              <span className="hidden md:block">
                <Range row={r} max={max} />
              </span>
              <span className="col-span-2 text-sm text-muted md:col-span-1">
                {r.reasons.length ? (
                  r.reasons.map((x, i) => (
                    <span key={x.signal} title={x.text} className="cursor-help">
                      {i > 0 && ' · '}
                      <span className={x.effect_pct < 0 ? 'text-down' : 'text-up'}>{shortReason(x)}</span>
                    </span>
                  ))
                ) : (
                  <span className="text-faint">평소와 같음</span>
                )}
              </span>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap justify-between gap-2 border-t-2 border-ink px-5 py-3 text-sm">
          <span className="font-semibold">합계 {rows.length}개 메뉴</span>
          <span className="tabular-nums">
            준비 <b className="text-base text-accent">{totalPrep}</b> · 예상 {totalPred}
          </span>
        </div>
      </section>

      <dl className="grid gap-x-8 gap-y-2 text-sm text-muted sm:grid-cols-3">
        <div>
          <dt className="font-semibold text-ink">준비</dt>
          <dd>고른 준비 기준({prepMode})으로 정한 권장 개수</dd>
        </div>
        <div>
          <dt className="font-semibold text-ink">예상 범위</dt>
          <dd>실제 판매가 들어올 것으로 보는 구간. 넓을수록 내일이 불확실</dd>
        </div>
        <div>
          <dt className="font-semibold text-ink">평소와 다른 점</dt>
          <dd>날씨·행사 때문에 달라진 정도. 숫자에 마우스를 올리면 설명</dd>
        </div>
      </dl>
      <p className="text-xs text-faint">{fmtTime(data.generated_at)}에 계산</p>
    </div>
  )
}
