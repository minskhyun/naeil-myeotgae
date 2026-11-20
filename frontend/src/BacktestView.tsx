// '얼마나 맞나' 화면 (로그인 뒤의 '자세히' 창, 첫 화면의 예시 3).
// 글은 최소로: 큰 결론 한 줄 → 숫자 세 칸 → 방법별 막대. 용어 풀이와 검증 기록은 접어 둔다.
//   하루 오차 = 예측대로 준비했다면 남았을 개수 + 모자랐을 개수 (모든 메뉴 합, 하루 평균)
//   지난주 그대로 = 지난주 같은 요일에 팔린 만큼 준비하는 방법 (사장님들이 흔히 쓰는 방식, 비교 기준)
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, type ModelScore, type SignalDecision } from './api'
import { count, fmtDate, GROUP_LABELS, missPerDay, MODEL_LABELS, pct1, RANGE_TARGET_TEXT } from './format'
import { RangeMeter } from './RangeMeter'
import { periodName, verdict } from './verdict'

const base = (m: string) => m.slice(0, 2) // "M3(채택 신호만)" → "M3"

// 가로 막대 한 줄: 이름 · 막대 · 값(하루 오차). 우리 방법만 강조색
export function BarRow({ label, value, max, strong }: { label: string; value: number; max: number; strong: boolean }) {
  return (
    <div className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-3 py-1.5 sm:grid-cols-[11rem_1fr_4rem]">
      <span className={`text-sm ${strong ? 'font-bold' : 'text-ink-700'}`}>{label}</span>
      <div className="h-5 overflow-hidden rounded bg-surface">
        <div className={`nm-band h-5 rounded ${strong ? 'bg-ink-900' : 'bg-bar'}`} style={{ width: `${(value / max) * 100}%` }} />
      </div>
      <span className={`text-right tabular-nums ${strong ? 'font-bold' : 'text-ink-700'}`}>{count(value)}개</span>
    </div>
  )
}

// 주변 정보 묶음 하나의 결과를 짧게: "오차 5.1% 감소" · "효과 없음" · "자료 없음". 긴 이유는 마우스를 올리면 보인다
function effect(d: SignalDecision, noDataText?: string) {
  if (d.adopted) return `오차 ${Math.abs(d.wape_change_pct).toFixed(1)}% 감소`
  if (d.folds_total === 0) return noDataText ?? '자료 없음'
  return '효과 없음'
}

// 주변 정보 묶음마다 썼는지 (첫 화면에서는 이것만 따로 보여 준다)
// noDataText: 자료가 없어 평가하지 못한 묶음에 대신 적을 말 (가상 예시는 일부 정보를 아예 모으지 않았다)
export function Decisions({ storeId, noDataText }: { storeId: string; noDataText?: string }) {
  const { data } = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) })
  if (!data) return null
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {data.decisions.map((d) => (
        <li key={d.signal_group} title={d.reason} className={`rounded-2xl border px-5 py-4 ${d.adopted ? 'border-ink-900 bg-white' : 'border-transparent bg-surface'}`}>
          <p className="flex items-center justify-between gap-2">
            <span className="font-bold">{GROUP_LABELS[d.signal_group] ?? d.signal_group}</span>
            <span className={`tag ${d.adopted ? 'bg-ink-900 text-white' : 'bg-white text-ink-500'}`}>
              {d.adopted ? '씀' : '안 씀'}
            </span>
          </p>
          <p className={`mt-1 text-sm ${d.adopted ? 'font-medium text-ink-900' : 'text-ink-500'}`}>{effect(d, noDataText)}</p>
        </li>
      ))}
    </ul>
  )
}

// 숫자 한 칸: 이름 · 큰 값 · (짧은 덧말)
function Stat({ label, value, note, extra }: { label: string; value: ReactNode; note?: string; extra?: ReactNode }) {
  return (
    <div className="rounded-2xl bg-surface px-5 py-4">
      <p className="text-sm text-ink-700">{label}</p>
      <p className="mt-1 text-h2 tabular-nums">{value}</p>
      {note && <p className="mt-0.5 text-sm text-ink-700">{note}</p>}
      {extra}
    </div>
  )
}

// hideDecisions: 위 Decisions를 다른 자리에서 이미 보여 줄 때 (첫 화면)
export function BacktestView({ storeId, hideDecisions = false }: { storeId: string; hideDecisions?: boolean }) {
  const { data, error, isLoading } = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) })
  if (isLoading) return <p className="text-ink-700">불러오는 중…</p>
  if (error || !data) return <p className="text-down">{(error as Error)?.message ?? '검증 결과가 없습니다.'}</p>

  const span = (p: [string, string]) => Math.round((Date.parse(p[1]) - Date.parse(p[0])) / 86400000) + 1
  const cvDays = data.cv_scores[0]?.days || data.folds.reduce((sum, f) => sum + span(f), 0) // 실제로 채점한 날 수 (휴무일 제외)
  const cvMiss = (s: ModelScore) => missPerDay(s, cvDays)
  const cvMax = Math.max(...data.cv_scores.map(cvMiss))
  // 실제로 쓰는 방법의 줄: 고른 신호 조합이 기본 M1~M3와 다르면 '(채택 신호만)' 줄이 따로 있다
  const picked = data.cv_scores.find((s) => s.model.includes('채택'))?.model ?? data.chosen_model
  const used = data.decisions.filter((d) => d.adopted).map((d) => GROUP_LABELS[d.signal_group] ?? d.signal_group)
  const name = (m: string) => (m === 'M0' ? '지난주 그대로 준비' : m === picked ? '내일몇개' : (MODEL_LABELS[base(m)] ?? m))
  const v = verdict(data) // 마지막 확인 기간의 결과, 기록이 짧아 없으면 검증 기간 결과

  return (
    <div className="space-y-8">
      {v ? (
        <header>
          <p className="text-sm text-ink-700">{periodName(v)} 동안 맞혀 본 결과</p>
          <h2 className="mt-1 text-h1">
            {v.saved > 0 ? (
              <>
                지난주 그대로 준비할 때보다 <span className="text-point">정확도 {v.gain}% 향상</span>
              </>
            ) : (
              '지난주 그대로 준비하는 것과 비슷해요'
            )}
          </h2>
          <p className="mt-2 text-ink-700">지난주 그대로 준비 = 지난주 같은 요일에 팔린 만큼 준비하는 방법</p>
        </header>
      ) : (
        <h2 className="text-h3">검증 결과가 없습니다.</h2>
      )}

      {v && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="하루 오차" value={`${count(v.mineShown)}개`} note={`지난주 그대로 준비하면 ${count(v.baseShown)}개`} />
          <Stat label="예상 범위 안에 든 비율" value={pct1(v.mine.coverage_80)} note={RANGE_TARGET_TEXT} extra={<RangeMeter value={v.mine.coverage_80} />} />
          <Stat label="쓰는 정보" value={<span className="text-xl">{used.length ? `판매 기록 + ${used.join('·')}` : '판매 기록'}</span>} />
        </div>
      )}

      {v && (
        <section>
          <BarRow label="지난주 그대로 준비" value={v.baseMiss} max={Math.max(v.baseMiss, v.mineMiss)} strong={false} />
          <BarRow label="내일몇개" value={v.mineMiss} max={Math.max(v.baseMiss, v.mineMiss)} strong />
        </section>
      )}

      {!hideDecisions && (
        <section>
          <h3 className="mb-3 text-h3">주변 정보</h3>
          <Decisions storeId={storeId} />
        </section>
      )}

      <details className="text-sm leading-relaxed text-ink-700">
        <summary className="cursor-pointer font-semibold text-ink-900 underline-offset-4 hover:underline">어떻게 쟀나요</summary>
        <ul className="mt-3 max-w-3xl list-disc space-y-1.5 pl-5">
          <li>지난 날짜를 그 전날까지의 기록만 보고 예측한 뒤, 실제 판매와 비교했습니다.</li>
          <li>하루 오차 = 예측대로 준비했다면 남았을 개수 + 모자랐을 개수 (모든 메뉴 합, 하루 평균)</li>
          <li>지난주 그대로 준비 = 지난주 같은 요일에 팔린 만큼 준비하는 방법</li>
          <li>
            예상 범위(예: 18~27개)는 실제 판매 10번 중 8번이 그 안에 들도록 잡은 폭입니다. '예상 범위 안에 든 비율'은 지난 날짜에서 실제로 몇 %가
            들었는지이고, 80%에 가까울수록 폭을 알맞게 잡은 것입니다. 훨씬 낮으면 범위가 좁아 자주 벗어난다는 뜻, 훨씬 높으면 범위가 넓어 쓸모가 줄어든다는
            뜻입니다. 높을수록 좋은 점수가 아닙니다.
          </li>
          {data.test_period && (
            <li>
              위의 숫자는 모두 마지막 확인 기간({fmtDate(data.test_period[0])} ~ {fmtDate(data.test_period[1])}) 기준입니다.
            </li>
          )}
          <li>{data.data_note}</li>
        </ul>
        <p className="mt-4 font-semibold text-ink-900">방법별 하루 오차 (그 앞의 검증 기간 {cvDays}일 기준)</p>
        <div className="mt-2 max-w-2xl">
          {data.cv_scores.map((s) => (
            <BarRow key={s.model} label={name(s.model)} value={cvMiss(s)} max={cvMax} strong={s.model === picked} />
          ))}
        </div>
      </details>
    </div>
  )
}
