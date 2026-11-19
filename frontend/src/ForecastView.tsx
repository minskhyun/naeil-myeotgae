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
export function Notice({ w }: { w: Warning }) {
  const scope = w.menu_scope.includes('*') ? '전체 메뉴' : w.menu_scope.join(', ')
  return (
    <section className="rounded-2xl border-l-4 border-warn bg-warn-soft px-5 py-4">
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

// 준비 기준(폐기 줄이기 · 균형 · 품절 줄이기) 고르기. 바꾸면 서버가 예측 단계만 다시 돌린다
export function PrepToggle({ storeId, prepMode, readOnly = false }: { storeId: string; prepMode: string; readOnly?: boolean }) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const job = useJob(jobId)
  const changing = job?.status === 'running'

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
    <div>
      <p className="mb-1.5 text-sm text-muted">
        준비 기준 {changing && <span className="text-accent">· 다시 계산 중</span>}
        {readOnly && <span className="text-faint"> · 보기 전용 매장이라 바꿀 수 없음</span>}
      </p>
      <div className="flex overflow-hidden rounded-full border border-ink/80" role="group" aria-label="준비 기준">
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
      {(jobError || job?.status === 'error') && <p className="mt-1 text-sm text-up">{jobError ?? job?.error}</p>}
    </div>
  )
}

// 메뉴별 준비표: 메뉴 · 준비 · 예상 · 예상 범위(그림) · 평소와 다른 점. 많이 팔리는 순
//   limit    처음에 몇 개만 보여 주고 나머지는 '더 보기'로. 합계는 항상 전체 메뉴
//   compact  좁은 칸에 넣을 때: '예상' 열을 뺀다 (예상값은 범위 그림의 눈금으로 보인다)
export function ForecastTable({ rows, limit, compact = false }: { rows: ForecastRow[]; limit?: number; compact?: boolean }) {
  const [showAll, setShowAll] = useState(false)
  const sorted = [...rows].sort((a, b) => b.pred - a.pred)
  const shown = limit && !showAll ? sorted.slice(0, limit) : sorted
  const max = Math.max(...shown.map((r) => r.p90)) * 1.05
  const totalPrep = rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(rows.reduce((sum, r) => sum + r.pred, 0))
  const cols = compact
    ? 'md:grid-cols-[minmax(7.5rem,1.2fr)_4.5rem_11.5rem_minmax(7rem,1.2fr)]'
    : 'md:grid-cols-[minmax(9rem,1.3fr)_5.5rem_5.5rem_12rem_minmax(10rem,1.5fr)]'

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-sheet">
      <div className={`hidden gap-4 border-b border-rule px-5 py-2.5 text-sm text-muted md:grid ${cols}`}>
        <span>메뉴</span>
        <span className="text-right">준비</span>
        {!compact && <span className="text-right">예상</span>}
        <span>예상 범위</span>
        <span>평소와 다른 점</span>
      </div>
      <ol>
        {shown.map((r) => (
          <li
            key={r.menu}
            className={`grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 border-b border-rule px-5 last:border-b-0 md:items-center ${cols} ${compact ? 'py-2.5' : 'py-3.5'}`}
          >
            <span className={`font-semibold ${compact ? 'text-base' : 'text-[17px]'}`}>{r.menu}</span>
            <span className="text-right text-2xl font-bold text-accent tabular-nums md:text-xl">
              {r.prep_qty ?? '–'}
              <span className="ml-0.5 text-sm font-normal text-muted md:hidden">개 준비</span>
            </span>
            <span className={`col-span-2 text-sm text-muted tabular-nums md:col-span-1 md:text-right md:text-base md:text-ink ${compact ? 'md:hidden' : ''}`}>
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
      {limit !== undefined && rows.length > limit && (
        <button onClick={() => setShowAll(!showAll)} className="w-full border-t border-rule px-5 py-2.5 text-left text-sm underline underline-offset-4 hover:text-accent">
          {showAll ? '많이 팔리는 메뉴만 보기' : `나머지 ${rows.length - limit}개 메뉴 더 보기`}
        </button>
      )}
      <div className="flex flex-wrap justify-between gap-2 border-t-2 border-ink px-5 py-3 text-sm">
        <span className="font-semibold">합계 {rows.length}개 메뉴</span>
        <span className="tabular-nums">
          준비 <b className="text-base text-accent">{totalPrep}</b> · 예상 {totalPred}
        </span>
      </div>
    </section>
  )
}

// 내일 준비표 한 화면 (첫 화면의 예시가 쓴다. 로그인 뒤의 화면은 같은 조각들을 Dashboard.tsx가 다르게 배치한다)
// limit: 처음에 많이 팔리는 메뉴 몇 개만 보여 주고 나머지는 '더 보기'로
export function ForecastView({ storeId, prepMode, readOnly = false, limit }: {
  storeId: string
  prepMode: string
  readOnly?: boolean
  limit?: number
}) {
  const { data, error, isLoading } = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) })
  if (isLoading) return <p className="text-muted">불러오는 중…</p>
  if (error || !data) return <p className="text-up">{(error as Error)?.message ?? '예측이 없습니다.'}</p>

  const used = data.signals_used.filter((s) => SIGNAL_LABELS[s]).map((s) => SIGNAL_LABELS[s])

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="text-sm text-muted">내일 준비표</p>
          <h2 className="mt-0.5 text-3xl font-bold tracking-tight">{fmtDate(data.rows[0].date)}</h2>
          <p className="mt-2 text-sm text-muted">
            {used.length ? <>반영한 주변 정보 — {used.join(', ')}</> : '주변 정보 없이 판매 기록만으로 예측했습니다'}
          </p>
        </div>
        <PrepToggle storeId={storeId} prepMode={prepMode} readOnly={readOnly} />
      </div>

      {data.warnings.map((w, i) => (
        <Notice key={i} w={w} />
      ))}

      <ForecastTable rows={data.rows} limit={limit} />

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
