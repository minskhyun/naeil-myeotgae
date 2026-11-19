import { useQuery } from '@tanstack/react-query'
import { api, type ModelScore } from './api'
import { count, fmtDate, GROUP_LABELS, missPerDay, MODEL_LABELS, pct1, rangeScore, won } from './format'
import { periodName, verdict } from './verdict'

const base = (m: string) => m.slice(0, 2) // "M3(채택 신호만)" → "M3"

// 가로 막대 한 줄: 이름 · 막대 · 값(하루에 남거나 모자란 개수). 선택한 방법만 강조색.
export function BarRow({ label, value, max, strong }: { label: string; value: number; max: number; strong: boolean }) {
  return (
    <div className="grid grid-cols-[9rem_1fr_4rem] items-center gap-3 py-1.5 sm:grid-cols-[11rem_1fr_4.5rem]">
      <span className={`text-sm ${strong ? 'font-semibold' : 'text-muted'}`}>{label}</span>
      <div className="h-5 bg-paper">
        <div className={`h-5 ${strong ? 'bg-accent' : 'bg-ink/20'}`} style={{ width: `${(value / max) * 100}%` }} />
      </div>
      <span className={`text-right tabular-nums ${strong ? 'font-semibold' : 'text-muted'}`}>{count(value)}개</span>
    </div>
  )
}

// 주변 정보 묶음마다 썼는지와 그 이유 (첫 화면에서는 이것만 따로 보여 준다)
// noDataText: 자료가 없어 평가하지 못한 묶음에 대신 적을 말 (가상 예시는 일부 정보를 아예 모으지 않았다)
export function Decisions({ storeId, noDataText }: { storeId: string; noDataText?: string }) {
  const { data } = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) })
  if (!data) return null
  return (
    <section>
      <h3 className="text-lg font-semibold">주변 정보를 쓴 이유, 안 쓴 이유</h3>
      <p className="mt-1 text-sm text-muted">넣었을 때 과거 예측이 실제로 더 정확해진 정보만 씁니다.</p>
      <ul className="mt-3 divide-y divide-rule border-y border-rule">
        {data.decisions.map((d) => (
          <li key={d.signal_group} className="grid grid-cols-[6rem_1fr] gap-3 py-3 text-sm sm:grid-cols-[8rem_4rem_1fr]">
            <span className="font-semibold">{GROUP_LABELS[d.signal_group] ?? d.signal_group}</span>
            <span className={d.adopted ? 'font-semibold text-accent' : 'text-faint'}>{d.adopted ? '씀' : '안 씀'}</span>
            <span className="col-span-2 text-muted sm:col-span-1">{noDataText && d.folds_total === 0 && !d.adopted ? noDataText : d.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// hideDecisions: 위 Decisions를 다른 자리에서 이미 보여 줄 때 (첫 화면)
export function BacktestView({ storeId, hideDecisions = false }: { storeId: string; hideDecisions?: boolean }) {
  const { data, error, isLoading } = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) })
  if (isLoading) return <p className="text-muted">불러오는 중…</p>
  if (error || !data) return <p className="text-up">{(error as Error)?.message ?? '검증 결과가 없습니다.'}</p>

  const span = (p: [string, string]) => Math.round((Date.parse(p[1]) - Date.parse(p[0])) / 86400000) + 1
  const cvDays = data.cv_scores[0]?.days || data.folds.reduce((sum, f) => sum + span(f), 0) // 실제로 채점한 날 수 (휴무일 제외)
  const cvMiss = (s: ModelScore) => missPerDay(s, cvDays)
  const cvMax = Math.max(...data.cv_scores.map(cvMiss))
  // 실제로 쓰는 방법의 줄: 고른 신호 조합이 기본 M1~M3와 다르면 '(채택 신호만)' 줄이 따로 있다
  const picked = data.cv_scores.find((s) => s.model.includes('채택'))?.model ?? data.chosen_model
  const used = data.decisions.filter((d) => d.adopted).map((d) => GROUP_LABELS[d.signal_group] ?? d.signal_group)
  // 화면에 보일 이름: 쓰는 방법은 실제로 채택한 정보로 ("판매 기록 + 날씨·유행"), 나머지는 기본 이름
  const name = (m: string) => (m === picked && used.length ? `판매 기록 + ${used.join('·')}` : (MODEL_LABELS[base(m)] ?? m))
  const v = verdict(data) // 최종 시험 결과, 기록이 짧아 없으면 검증 기간 결과

  return (
    <div className="space-y-10">
      <header>
        <p className="text-sm text-muted">얼마나 맞나</p>
        {v ? (
          <h2 className="mt-1 max-w-3xl text-2xl font-bold leading-snug tracking-tight sm:text-[28px]">
            {periodName(v)} 동안 하루 평균 {count(v.mineShown)}개가 남거나 모자랐습니다.{' '}
            <span className="text-muted">
              '지난주 같은 요일만큼' 준비하는 방법(하루 {count(v.baseShown)}개)
              {v.saved > 0 ? `보다 하루 ${count(v.saved)}개(${v.gain}%) 적습니다.` : '보다 나아지지 않았습니다.'}
              {v.money !== null && v.money > 0 && ` 판매가로 환산하면 하루 약 ${won(v.money)}입니다.`}
            </span>
          </h2>
        ) : (
          <h2 className="mt-1 text-2xl font-bold">검증 결과가 없습니다.</h2>
        )}
        {v && !v.final && (
          <p className="mt-3 text-sm text-muted">
            기록이 짧아 마지막 확인 기간을 따로 두지 못했습니다. 검증 기간 결과입니다: 그날그날 전날까지의 기록만 보고 예측한 뒤 실제와 비교했습니다.
          </p>
        )}
        {data.test_period && (
          <p className="mt-3 text-sm text-muted">
            마지막 확인 기간 {fmtDate(data.test_period[0])} ~ {fmtDate(data.test_period[1])}. 방법을 다 정한 뒤 딱 한 번, 그날그날 전날까지의 기록만 보고 예측해 실제와
            비교했습니다.
          </p>
        )}
      </header>

      <dl className="grid border-y border-rule sm:grid-cols-3 sm:divide-x sm:divide-rule">
        <div className="py-4 sm:pr-6">
          <dt className="text-sm text-muted">쓰는 방법</dt>
          <dd className="mt-1 text-xl font-semibold">{name(picked)}</dd>
        </div>
        <div className="border-t border-rule py-4 sm:border-t-0 sm:px-6">
          <dt className="text-sm text-muted">남거나 모자란 개수 (하루, {v ? periodName(v) : '확인 기간'} 기준)</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">{v ? `${count(v.mineShown)}개` : '–'}</dd>
          {v && v.overShown !== null ? (
            <dd className="mt-1 text-sm text-muted">
              남는 쪽 {count(v.overShown)}개 + 모자란 쪽 {count(v.mineShown - v.overShown)}개 (모든 메뉴 합)
            </dd>
          ) : null}
        </div>
        <div className="border-t border-rule py-4 sm:border-t-0 sm:pl-6">
          <dt className="text-sm text-muted">예상 범위 정확도</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">
            {v ? pct1(rangeScore(v.mine.coverage_80)) : '–'} <span className="text-sm font-normal text-muted">100%가 만점</span>
          </dd>
          {v && <dd className="mt-1 text-sm text-muted">실제 판매의 {pct1(v.mine.coverage_80)}가 범위 안 · 목표 80%를 맞추면 100%</dd>}
        </div>
      </dl>

      <section>
        <h3 className="text-lg font-semibold">방법별 하루에 남거나 모자란 개수</h3>
        <p className="mt-1 text-sm text-muted">
          검증 기간 {cvDays}일({data.folds.length}구간) 기준. 예측대로 준비했다면 남았을 개수 + 모자랐을 개수(모든 메뉴 합), 짧을수록 좋습니다.
          {v?.final && ` 위의 숫자(${periodName(v)} 기준)와는 기간이 달라 값이 조금 다릅니다.`}
        </p>
        <div className="mt-4">
          {data.cv_scores.map((s) => (
            <BarRow key={s.model} label={name(s.model)} value={cvMiss(s)} max={cvMax} strong={s.model === picked} />
          ))}
        </div>
      </section>

      {!hideDecisions && <Decisions storeId={storeId} />}

      <details className="text-sm leading-relaxed text-muted">
        <summary className="cursor-pointer font-semibold text-ink underline-offset-4 hover:underline">자세한 검증 기록 보기</summary>
        <p className="mt-2 max-w-3xl">
          {data.data_note} <span className="text-faint">(M0 = 지난주 같은 요일만큼, M1 = 판매 기록만, M2 = + 날씨, M3 = + 학사일정·행사·유행)</span>
        </p>
      </details>
    </div>
  )
}
