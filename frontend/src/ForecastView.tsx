import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, PREP_MODES, type ForecastRow, type SalesHistory, type Warning } from './api'
import { CountUp } from './CountUp'
import { BarsLegend, DayBars, Spark } from './ForecastCharts'
import { average, count, dayPrefix, dayWord, expectedTotal, fmtDate, rangeText, sameWeekday, shortReason, SIGNAL_LABELS, signedPct, SITUATION_LABELS, weekdayName } from './format'
import { useJob } from './useJob'

// 예상 범위 그림: 가는 선 위에 범위(굵은 선, 왼쪽에서 자라남)와 예상값(눈금). narrow = 좁은 칸용
function Range({ row, max, narrow = false }: { row: ForecastRow; max: number; narrow?: boolean }) {
  const x = (v: number) => `${Math.min(100, (v / max) * 100)}%`
  return (
    <div className="flex items-center gap-3">
      <div className={`relative h-3 shrink-0 ${narrow ? 'w-20' : 'w-28'}`} aria-hidden>
        <div className="absolute top-1/2 h-px w-full bg-line" />
        <div className="nm-band absolute top-1/2 -mt-0.5 h-1 rounded-full bg-ink-300" style={{ left: x(row.p10), width: `calc(${x(row.p90)} - ${x(row.p10)})` }} />
        <div className="nm-fade absolute top-0 h-3 w-0.5 -translate-x-1/2 bg-ink-900" style={{ left: x(row.pred), animationDelay: '500ms' }} />
      </div>
      <span className="text-sm text-ink-700 tabular-nums">
        {rangeText(row.p10, row.p90)}
      </span>
    </div>
  )
}

// AI가 읽은 소식 한 건: 상황 한 줄 · 안내 문장. 근거(원문 인용과 링크)는 접어 두고 누르면 펼친다
export function Notice({ w }: { w: Warning }) {
  return (
    <section className="rounded-2xl bg-ink-900 px-5 py-4 text-white">
      <p className="text-label font-semibold text-point">
        {SITUATION_LABELS[w.situation_type] ?? w.situation_type} · 손님 {w.direction} 가능
      </p>
      <p className="mt-1.5 text-[17px] leading-relaxed">{w.message}</p>
      {w.evidence.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer font-semibold text-white underline-offset-4 hover:underline">근거 {w.evidence.length}건</summary>
          {w.evidence.map((e, i) => (
            <blockquote key={i} className="mt-2 border-l border-white/30 pl-3 leading-relaxed text-white/75">
              {e.quote}{' '}
              <a href={e.source_url} target="_blank" rel="noreferrer" className="whitespace-nowrap text-white underline underline-offset-2">
                원문
              </a>
            </blockquote>
          ))}
        </details>
      )}
    </section>
  )
}

// 준비 기준마다의 한 줄 풀이 (폐기 줄이기 = 분포의 40% 지점, 균형 = 예상 판매량, 품절 줄이기 = 80% 지점)
const PREP_HINTS: Record<string, string> = { '폐기 줄이기': '남지 않게 조금 적게', 균형: '예상 판매만큼', '품절 줄이기': '모자라지 않게 넉넉히' }

// 준비 기준(폐기 줄이기 · 균형 · 품절 줄이기) 고르기. 바꾸면 서버가 예측 단계만 다시 돌린다
//   onPick  주면 서버를 부르지 않고 화면에서만 바꾼다 (보기 전용 예시: 세 기준의 개수를 눌러서 비교)
export function PrepToggle({ storeId, prepMode, readOnly = false, onPick }: {
  storeId: string
  prepMode: string
  readOnly?: boolean
  onPick?: (mode: string) => void
}) {
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const job = useJob(jobId)
  const changing = job?.status === 'running'

  const choose = async (mode: string) => {
    if (mode === prepMode) return
    if (onPick) return onPick(mode)
    setJobError(null)
    try {
      setJobId((await api.setPrepMode(storeId, mode)).job_id)
    } catch (e) {
      setJobError((e as Error).message)
    }
  }

  // 가운데에 크게 둔다: 준비 개수 전체를 바꾸는 선택이라 눈에 잘 띄어야 한다. 기준마다 한 줄 풀이를 붙인다
  return (
    <div className="mx-auto w-full max-w-2xl text-center">
      <p className="mb-3 text-h3">
        준비 기준 {changing && <span className="text-base font-normal text-ink-500">· 다시 계산 중</span>}
      </p>
      <div className="grid grid-cols-3 overflow-hidden rounded-xl border border-ink-900" role="group" aria-label="준비 기준">
        {PREP_MODES.map((m, i) => (
          <button
            key={m}
            disabled={changing || (readOnly && !onPick)}
            onClick={() => choose(m)}
            aria-pressed={m === prepMode}
            className={`flex flex-col items-center justify-center gap-0.5 px-2 py-3.5 transition-colors duration-150 ${i > 0 ? 'border-l border-ink-900' : ''} ${
              m === prepMode ? 'bg-ink-900 text-white' : 'bg-white hover:bg-surface'
            } ${readOnly ? 'disabled:cursor-not-allowed' : 'disabled:cursor-wait'}`}
          >
            <span className="text-lg font-semibold">{m}</span>
            <span className={`text-sm ${m === prepMode ? 'text-white/75' : 'text-ink-500'}`}>{PREP_HINTS[m]}</span>
          </button>
        ))}
      </div>
      {(jobError || job?.status === 'error') && <p className="mt-2 text-sm text-down">{jobError ?? job?.error}</p>}
    </div>
  )
}

// 메뉴 하나를 눌렀을 때 펼쳐지는 칸: 그 메뉴의 최근 4주 막대 + 내일 예상, 같은 요일 기록, 평소와 다른 이유(문장)
function MenuDetail({ row, history }: { row: ForecastRow; history: SalesHistory | undefined }) {
  const values = history?.menus[row.menu]
  const past = history && values ? sameWeekday(history.dates, values, row.date) : []
  const usual = average(past)
  return (
    <div className="nm-rise border-t border-dashed border-line bg-surface/60 px-5 pb-5 pt-4">
      {history && values ? (
        <>
          <p className="mb-3 text-sm text-ink-700">
            {usual !== null && (
              <>
                지난 4주 {weekdayName(row.date)}요일 평균 <b className="text-ink-900">{count(usual)}개</b> →{' '}
              </>
            )}
            {dayPrefix(row.date)}예상 <b className="text-ink-900">{count(row.pred)}개</b>
          </p>
          <DayBars dates={history.dates} values={values} next={{ date: row.date, value: row.pred, lo: row.p10, hi: row.p90 }} height={110} />
        </>
      ) : (
        <p className="text-sm text-ink-700">최근 판매 기록이 없어요.</p>
      )}
      {row.reasons.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm">
          {row.reasons.map((x) => (
            <li key={x.signal} className="flex gap-2">
              <span className={`shrink-0 font-semibold tabular-nums ${x.effect_pct < 0 ? 'text-down' : 'text-up'}`}>{signedPct(x.effect_pct)}</span>
              <span className="text-ink-700">
                {x.text}
                {x.source_url && (
                  <>
                    {' '}
                    <a href={x.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-ink-900">
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
  const cut = limit !== undefined && rows.length > limit + 2 ? limit : undefined // 한두 개만 숨기느니 다 보여 준다
  const shown = cut && !showAll ? sorted.slice(0, cut) : sorted
  const max = Math.max(...shown.map((r) => r.p90)) * 1.05
  const totalPrep = rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = expectedTotal(rows)
  const why = rows.some((r) => r.reasons.length > 0) // '평소 대비'에 적을 것이 하나라도 있나 (주변 정보를 안 쓰는 매장은 열을 숨긴다)
  const cols = compact
    ? why
      ? 'md:grid-cols-[minmax(6.5rem,1fr)_3.5rem_7.5rem_8.75rem_minmax(8.5rem,1.1fr)_1rem]'
      : 'md:grid-cols-[minmax(8rem,1.4fr)_4rem_8rem_minmax(8.75rem,1fr)_1rem]'
    : why
      ? 'md:grid-cols-[minmax(9rem,1.3fr)_5rem_4.5rem_7.5rem_12rem_minmax(9rem,1.4fr)_1rem]'
      : 'md:grid-cols-[minmax(10rem,1.6fr)_5rem_5rem_8rem_minmax(12rem,1fr)_1rem]'
  const date = rows[0].date

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-white">
      {history && (
        <div className="border-b border-line px-5 pb-4 pt-5">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
            <h4 className="font-bold">최근 4주 판매</h4>
            <BarsLegend date={date} />
          </div>
          <DayBars dates={history.dates} values={history.total} next={{ date, value: totalPred }} height={compact ? 130 : 160} />
        </div>
      )}
      <div className={`hidden gap-4 border-b border-line px-5 py-2.5 text-sm text-ink-700 md:grid ${cols}`}>
        <span>메뉴</span>
        <span className="text-right">준비</span>
        {!compact && <span className="text-right">예상</span>}
        <span>최근 4주</span>
        <span>예상 범위</span>
        {why && <span>평소 대비</span>}
        <span />
      </div>
      <ol>
        {shown.map((r, i) => (
          <li key={r.menu} className="nm-rise border-b border-line last:border-b-0" style={{ animationDelay: `${Math.min(i, 12) * 45}ms` }}>
            <button
              type="button"
              onClick={() => setOpen(open === r.menu ? null : r.menu)}
              aria-expanded={open === r.menu}
              className={`grid w-full grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-5 text-left transition-colors hover:bg-surface md:items-center ${cols} ${
                compact ? 'py-2.5' : 'py-3.5'
              } ${open === r.menu ? 'bg-surface' : ''}`}
            >
              <span className={`font-semibold ${compact ? 'text-base' : 'text-[17px]'}`}>{r.menu}</span>
              <span className="text-right text-2xl font-semibold text-ink-900 tabular-nums md:text-xl">
                {r.prep_qty === null || r.prep_qty === undefined ? '–' : <CountUp to={r.prep_qty} />}
                <span className="ml-0.5 text-sm font-normal text-ink-700 md:hidden">개 준비</span>
              </span>
              <span className={`col-span-2 text-sm text-ink-700 tabular-nums md:col-span-1 md:text-right md:text-base md:text-ink-900 ${compact ? 'md:hidden' : ''}`}>
                <span className="md:hidden">예상 </span>
                {Math.round(r.pred)}
                <span className="md:hidden">
                  {' '}· 범위 {rangeText(r.p10, r.p90)}
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
              <span className={`col-span-2 text-sm text-ink-700 md:col-span-1 md:whitespace-nowrap ${why ? '' : 'hidden'}`}>
                {r.reasons.length ? (
                  r.reasons.map((x, k) => (
                    <span key={x.signal} title={x.text}>
                      {k > 0 && ' · '}
                      <span className={x.effect_pct < 0 ? 'text-down' : 'text-up'}>{shortReason(x)}</span>
                    </span>
                  ))
                ) : (
                  <span className="text-ink-500">–</span>
                )}
              </span>
              <span className={`hidden text-ink-500 transition-transform md:block ${open === r.menu ? 'rotate-180' : ''}`} aria-hidden>
                ▾
              </span>
            </button>
            {open === r.menu && <MenuDetail row={r} history={history} />}
          </li>
        ))}
      </ol>
      {cut !== undefined && (
        <button onClick={() => setShowAll(!showAll)} className="w-full border-t border-line px-5 py-2.5 text-left text-sm underline underline-offset-4 hover:text-ink-900">
          {showAll ? '많이 팔리는 메뉴만 보기' : `나머지 ${rows.length - cut}개 메뉴 더 보기`}
        </button>
      )}
      <div className="flex flex-wrap justify-between gap-2 border-t border-line px-5 py-3 text-sm">
        <span className="font-semibold">합계 {rows.length}개 메뉴</span>
        <span className="tabular-nums">
          준비 <b className="text-base text-ink-900">{totalPrep}</b> · 예상 {totalPred}
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
  const [picked, setPicked] = useState<string | null>(null) // 보기 전용 예시에서 눌러 본 준비 기준
  if (isLoading) return <p className="text-ink-700">불러오는 중…</p>
  if (error || !data) return <p className="text-down">{(error as Error)?.message ?? '예측이 없습니다.'}</p>

  // 보기 전용 예시: 준비 기준을 눌러 보면 서버 없이 그 기준의 개수로 바꿔 보여 준다 (예측할 때 세 기준을 모두 계산해 둔다)
  const local = readOnly && data.rows.some((r) => r.prep_by_mode)
  const mode = (local && picked) || prepMode
  const rows = local ? data.rows.map((r) => ({ ...r, prep_qty: r.prep_by_mode?.[mode] ?? r.prep_qty })) : data.rows
  // 이날 숫자를 실제로 바꾼 정보 (메뉴마다의 '평소 대비' 이유에서 모은다)
  const day = dayWord(data.rows[0].date)
  const moved = [...new Set(data.rows.flatMap((r) => r.reasons.map((x) => SIGNAL_LABELS[x.signal] ?? x.signal)))]

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="text-sm font-semibold text-ink-700">{day === '이날' ? '준비표' : `${day} 준비표`}</p>
          <h2 className="mt-0.5 text-h2">{fmtDate(data.rows[0].date)}</h2>
          {moved.length > 0 && (
            <ul className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              <li className="text-ink-700">반영한 정보</li>
              {moved.map((m) => (
                <li key={m} className="tag bg-surface text-ink-900">
                  {m}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {data.warnings.length > 0 && (
        <div className="space-y-3">
          {data.warnings.map((w, i) => (
            <Notice key={i} w={w} />
          ))}
        </div>
      )}

      <PrepToggle storeId={storeId} prepMode={mode} readOnly={readOnly} onPick={local ? setPicked : undefined} />

      <ForecastTable rows={rows} limit={limit} storeId={storeId} />

    </div>
  )
}
