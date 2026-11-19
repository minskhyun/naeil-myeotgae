import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, PREP_MODES, type ForecastRow, type SalesHistory, type Warning } from './api'
import { CountUp } from './CountUp'
import { BarsLegend, DayBars, Spark } from './ForecastCharts'
import { average, count, fmtDate, fmtTime, sameWeekday, shortReason, SIGNAL_LABELS, signedPct, weekdayName } from './format'
import { useJob } from './useJob'

// 예상 범위 그림: 가는 선 위에 범위(굵은 선, 왼쪽에서 자라남)와 예상값(눈금). narrow = 좁은 칸용
function Range({ row, max, narrow = false }: { row: ForecastRow; max: number; narrow?: boolean }) {
  const x = (v: number) => `${Math.min(100, (v / max) * 100)}%`
  return (
    <div className="flex items-center gap-3">
      <div className={`relative h-3 shrink-0 ${narrow ? 'w-20' : 'w-28'}`} aria-hidden>
        <div className="absolute top-1/2 h-px w-full bg-rule" />
        <div className="nm-band absolute top-1/2 -mt-0.5 h-1 rounded-full bg-ink/25" style={{ left: x(row.p10), width: `calc(${x(row.p90)} - ${x(row.p10)})` }} />
        <div className="nm-fade absolute top-0 h-3 w-0.5 -translate-x-1/2 bg-ink" style={{ left: x(row.pred), animationDelay: '500ms' }} />
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

// 메뉴 하나를 눌렀을 때 펼쳐지는 칸: 그 메뉴의 최근 4주 막대 + 내일 예상, 같은 요일 기록, 평소와 다른 이유(문장)
function MenuDetail({ row, history }: { row: ForecastRow; history: SalesHistory | undefined }) {
  const values = history?.menus[row.menu]
  const past = history && values ? sameWeekday(history.dates, values, row.date) : []
  const usual = average(past)
  return (
    <div className="nm-rise border-t border-dashed border-rule bg-paper/60 px-5 pb-5 pt-4">
      {history && values ? (
        <>
          <p className="mb-3 text-sm text-muted">
            지난 4주 {weekdayName(row.date)}요일에 <b className="text-ink">{past.map((v) => count(v)).join(' · ') || '기록 없음'}</b>
            {usual !== null && <>개 (평균 {count(usual)}개)</>} → 내일 예상 <b className="text-ink">{count(row.pred)}개</b>, 범위 {count(row.p10)}–
            {count(row.p90)}개
          </p>
          <DayBars dates={history.dates} values={values} next={{ date: row.date, value: row.pred, lo: row.p10, hi: row.p90 }} height={110} />
        </>
      ) : (
        <p className="text-sm text-muted">최근 판매 그래프는 예측을 다시 돌리면 보여요.</p>
      )}
      {row.reasons.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm">
          {row.reasons.map((x) => (
            <li key={x.signal} className="flex gap-2">
              <span className={`shrink-0 font-semibold tabular-nums ${x.effect_pct < 0 ? 'text-down' : 'text-up'}`}>{signedPct(x.effect_pct)}</span>
              <span className="text-muted">
                {x.text}
                {x.source_url && (
                  <>
                    {' '}
                    <a href={x.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-accent">
                      출처
                    </a>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// 메뉴별 준비표: 맨 위에 '최근 4주 하루 판매량과 내일 예상' 그래프, 그 아래 메뉴마다 한 줄
//   한 줄 = 메뉴 · 준비(숫자가 올라가며 나타남) · 최근 4주 추이선과 내일 예상 점 · 예상 범위 · 평소와 다른 점. 많이 팔리는 순
//   줄을 누르면 그 메뉴의 그래프와 이유가 펼쳐진다 (MenuDetail)
//   limit    처음에 몇 개만 보여 주고 나머지는 '더 보기'로. 합계는 항상 전체 메뉴
//   compact  좁은 칸에 넣을 때: '예상' 열을 뺀다 (예상값은 범위 그림의 눈금으로 보인다)
//   storeId  주면 최근 판매(api.history)를 받아 그래프를 그린다. 기록이 없는 매장은 그래프 없이 표만
export function ForecastTable({ rows, limit, compact = false, storeId }: {
  rows: ForecastRow[]
  limit?: number
  compact?: boolean
  storeId?: string
}) {
  const [showAll, setShowAll] = useState(false)
  // 펼친 메뉴. 주소에 ?menu=소금빵 이 있으면 그 메뉴를 펼친 채로 시작한다 (?store=, ?open= 과 같은 방식)
  const [open, setOpen] = useState<string | null>(() => new URLSearchParams(window.location.search).get('menu'))
  const history = useQuery({ queryKey: ['history', storeId], queryFn: () => api.history(storeId as string), enabled: !!storeId, retry: false }).data
  const sorted = [...rows].sort((a, b) => b.pred - a.pred)
  const shown = limit && !showAll ? sorted.slice(0, limit) : sorted
  const max = Math.max(...shown.map((r) => r.p90)) * 1.05
  const totalPrep = rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(rows.reduce((sum, r) => sum + r.pred, 0))
  const cols = compact
    ? 'md:grid-cols-[minmax(7rem,1.2fr)_3.5rem_7.5rem_9.5rem_minmax(6rem,1fr)_1rem]'
    : 'md:grid-cols-[minmax(9rem,1.3fr)_5rem_4.5rem_7.5rem_12rem_minmax(9rem,1.4fr)_1rem]'
  const date = rows[0].date
  const past = history ? sameWeekday(history.dates, history.total, date) : []
  const usual = average(past)
  const diff = usual ? Math.round((totalPred / usual - 1) * 100) : null

  return (
    <section className="overflow-hidden rounded-2xl border border-rule bg-sheet">
      {history && (
        <div className="border-b border-rule px-5 pb-4 pt-5">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
            <div>
              <h4 className="font-bold">최근 4주 하루 판매량과 내일 예상</h4>
              {usual !== null && diff !== null && (
                <p className="mt-0.5 text-sm text-muted">
                  지난 4주 {weekdayName(date)}요일은 평균 {count(usual)}개 → 내일은 <b className="text-ink">{count(totalPred)}개</b> 예상
                  {Math.abs(diff) >= 3 && (
                    <>
                      {' '}
                      (<span className={diff < 0 ? 'text-down' : 'text-up'}>{signedPct(diff)}</span>)
                    </>
                  )}
                </p>
              )}
            </div>
            <BarsLegend weekday={weekdayName(date)} />
          </div>
          <DayBars dates={history.dates} values={history.total} next={{ date, value: totalPred }} height={compact ? 130 : 160} />
        </div>
      )}
      <div className={`hidden gap-4 border-b border-rule px-5 py-2.5 text-sm text-muted md:grid ${cols}`}>
        <span>메뉴</span>
        <span className="text-right">준비</span>
        {!compact && <span className="text-right">예상</span>}
        <span>최근 4주 → 내일</span>
        <span>예상 범위</span>
        <span>평소와 다른 점</span>
        <span />
      </div>
      <ol>
        {shown.map((r, i) => (
          <li key={r.menu} className="nm-rise border-b border-rule last:border-b-0" style={{ animationDelay: `${Math.min(i, 12) * 45}ms` }}>
            <button
              type="button"
              onClick={() => setOpen(open === r.menu ? null : r.menu)}
              aria-expanded={open === r.menu}
              className={`grid w-full grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-5 text-left transition-colors hover:bg-accent-soft/50 md:items-center ${cols} ${
                compact ? 'py-2.5' : 'py-3.5'
              } ${open === r.menu ? 'bg-accent-soft/50' : ''}`}
            >
              <span className={`font-semibold ${compact ? 'text-base' : 'text-[17px]'}`}>{r.menu}</span>
              <span className="text-right text-2xl font-bold text-accent tabular-nums md:text-xl">
                {r.prep_qty === null || r.prep_qty === undefined ? '–' : <CountUp to={r.prep_qty} />}
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
                {history?.menus[r.menu] && (
                  <Spark values={history.menus[r.menu]} next={{ date: r.date, value: r.pred, lo: r.p10, hi: r.p90 }} delay={Math.min(i, 12) * 45} />
                )}
              </span>
              <span className="hidden md:block">
                <Range row={r} max={max} narrow={compact} />
              </span>
              <span className="col-span-2 text-sm text-muted md:col-span-1">
                {r.reasons.length ? (
                  r.reasons.map((x, k) => (
                    <span key={x.signal} title={x.text}>
                      {k > 0 && ' · '}
                      <span className={x.effect_pct < 0 ? 'text-down' : 'text-up'}>{shortReason(x)}</span>
                    </span>
                  ))
                ) : (
                  <span className="text-faint">평소와 같음</span>
                )}
              </span>
              <span className={`hidden text-faint transition-transform md:block ${open === r.menu ? 'rotate-180' : ''}`} aria-hidden>
                ▾
              </span>
            </button>
            {open === r.menu && <MenuDetail row={r} history={history} />}
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

      <ForecastTable rows={data.rows} limit={limit} storeId={storeId} />

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
          <dd>날씨·행사 때문에 달라진 정도. 메뉴를 누르면 그래프와 설명</dd>
        </div>
      </dl>
      <p className="text-xs text-faint">{fmtTime(data.generated_at)}에 계산</p>
    </div>
  )
}
