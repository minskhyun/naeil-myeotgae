import { useQuery } from '@tanstack/react-query'
import { api, type ModelScore } from './api'
import { fmtDate, GROUP_LABELS, MODEL_LABELS, pct1 } from './format'

const base = (m: string) => m.slice(0, 2) // "M3(채택 신호만)" → "M3"

// 가로 막대 한 줄: 이름 · 막대 · 값. 선택한 방법만 강조색.
function BarRow({ label, value, max, strong }: { label: string; value: number; max: number; strong: boolean }) {
  return (
    <div className="grid grid-cols-[9rem_1fr_4rem] items-center gap-3 py-1.5 sm:grid-cols-[11rem_1fr_4.5rem]">
      <span className={`text-sm ${strong ? 'font-semibold' : 'text-muted'}`}>{label}</span>
      <div className="h-5 bg-paper">
        <div className={`h-5 ${strong ? 'bg-accent' : 'bg-ink/20'}`} style={{ width: `${(value / max) * 100}%` }} />
      </div>
      <span className={`text-right tabular-nums ${strong ? 'font-semibold' : 'text-muted'}`}>{pct1(value)}</span>
    </div>
  )
}

// 주변 정보 묶음마다 썼는지와 그 이유 (첫 화면에서는 이것만 따로 보여 준다)
export function Decisions({ storeId }: { storeId: string }) {
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
            <span className="col-span-2 text-muted sm:col-span-1">{d.reason}</span>
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

  const test = Object.fromEntries(data.test_scores.map((s) => [base(s.model), s])) as Record<string, ModelScore>
  const chosen = base(data.chosen_model)
  const tChosen = test[chosen]
  const tM0 = test.M0
  const cvMax = Math.max(...data.cv_scores.map((s) => s.wape))
  // 실제로 쓰는 방법의 줄: 고른 신호 조합이 기본 M1~M3와 다르면 '(채택 신호만)' 줄이 따로 있다
  const picked = data.cv_scores.find((s) => s.model.includes('채택'))?.model ?? data.chosen_model
  const used = data.decisions.filter((d) => d.adopted).map((d) => GROUP_LABELS[d.signal_group] ?? d.signal_group)
  // 화면에 보일 이름: 쓰는 방법은 실제로 채택한 정보로 ("판매 기록 + 날씨·유행"), 나머지는 기본 이름
  const name = (m: string) => (m === picked && used.length ? `판매 기록 + ${used.join('·')}` : (MODEL_LABELS[base(m)] ?? m))
  const gain = tChosen && tM0 ? Math.round((1 - tChosen.wape / tM0.wape) * 100) : null
  const testDays = data.test_period
    ? Math.round((Date.parse(data.test_period[1]) - Date.parse(data.test_period[0])) / 86400000) + 1
    : 0

  return (
    <div className="space-y-10">
      <header>
        <p className="text-sm text-muted">얼마나 맞나</p>
        {tChosen && tM0 ? (
          <h2 className="mt-1 max-w-3xl text-2xl font-bold leading-snug tracking-tight sm:text-[28px]">
            마지막 {testDays}일 동안 틀린 양은 판매량의 {pct1(tChosen.wape)}였습니다.{' '}
            <span className="text-muted">
              '지난주 같은 요일만큼' 준비하는 방법({pct1(tM0.wape)})
              {gain !== null && gain > 0 ? `보다 ${gain}% 적습니다.` : '보다 나아지지 않았습니다.'}
            </span>
          </h2>
        ) : (
          <h2 className="mt-1 text-2xl font-bold">기록이 짧아 최종 시험 기간 없이 검증 기간 결과만 있습니다.</h2>
        )}
        {data.test_period && (
          <p className="mt-3 text-sm text-muted">
            시험 기간 {fmtDate(data.test_period[0])} ~ {fmtDate(data.test_period[1])}. 그날그날 전날까지의 기록만 보고 예측한 뒤 실제와 비교했습니다.
          </p>
        )}
      </header>

      <dl className="grid border-y border-rule sm:grid-cols-3 sm:divide-x sm:divide-rule">
        <div className="py-4 sm:pr-6">
          <dt className="text-sm text-muted">쓰는 방법</dt>
          <dd className="mt-1 text-xl font-semibold">{name(picked)}</dd>
        </div>
        <div className="border-t border-rule py-4 sm:border-t-0 sm:px-6">
          <dt className="text-sm text-muted">틀린 양 (시험 기간)</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">{tChosen ? pct1(tChosen.wape) : '–'}</dd>
        </div>
        <div className="border-t border-rule py-4 sm:border-t-0 sm:pl-6">
          <dt className="text-sm text-muted">실제가 예상 범위 안에 든 비율</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">
            {tChosen ? pct1(tChosen.coverage_80) : '–'} <span className="text-sm font-normal text-muted">목표 80%</span>
          </dd>
        </div>
      </dl>

      <section>
        <h3 className="text-lg font-semibold">방법별 틀린 양</h3>
        <p className="mt-1 text-sm text-muted">검증 기간 {data.folds.length}구간 합계. 틀린 개수의 합 ÷ 실제 판매량의 합, 짧을수록 좋습니다.</p>
        <div className="mt-4">
          {data.cv_scores.map((s) => (
            <BarRow key={s.model} label={name(s.model)} value={s.wape} max={cvMax} strong={s.model === picked} />
          ))}
        </div>
      </section>

      {!hideDecisions && <Decisions storeId={storeId} />}

      {data.shared && (
        <section>
          <h3 className="text-lg font-semibold">다른 매장과 함께 배우기</h3>
          <p className="mt-1 text-sm text-muted">
            함께 배우기를 켠 다른 매장 {data.shared.partners}곳의 기록을 더해 배운 모델과, 이 매장 기록만으로 배운 모델을 같은 기간에서 비교했습니다.
          </p>
          <div className="mt-4">
            <BarRow label="이 매장 기록만" value={data.shared.wape_own} max={Math.max(data.shared.wape_own, data.shared.wape_shared)} strong={!data.shared.adopted} />
            <BarRow label="다른 매장과 함께" value={data.shared.wape_shared} max={Math.max(data.shared.wape_own, data.shared.wape_shared)} strong={data.shared.adopted} />
          </div>
          <p className="mt-3 text-sm">
            <span className={data.shared.adopted ? 'font-semibold text-accent' : 'font-semibold'}>{data.shared.adopted ? '씀' : '안 씀'}</span>
            <span className="text-muted"> — {data.shared.reason}</span>
          </p>
        </section>
      )}

      <section className="text-sm leading-relaxed text-muted">
        <h3 className="font-semibold text-ink">데이터 메모</h3>
        <p className="mt-1 max-w-3xl">{data.data_note}</p>
      </section>
    </div>
  )
}
