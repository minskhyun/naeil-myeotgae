import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, GROUP_LABELS, MODEL_LABELS, type ModelScore } from './api'

const pct = (v: number) => `${(v * 100).toFixed(1)}%`
const baseModel = (m: string) => m.slice(0, 2) // "M3(채택 신호만)" → "M3"

export function BacktestView({ storeId }: { storeId: string }) {
  const { data, error, isLoading } = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) })
  if (isLoading) return <p className="text-stone-500">불러오는 중…</p>
  if (error || !data) return <p className="text-rose-600">{(error as Error)?.message ?? '검증 결과가 없습니다.'}</p>

  const test = Object.fromEntries(data.test_scores.map((s) => [baseModel(s.model), s])) as Record<string, ModelScore>
  const chart = data.cv_scores.map((s) => ({
    model: s.model,
    label: `${baseModel(s.model)} ${MODEL_LABELS[baseModel(s.model)] ?? ''}`,
    wape: +(s.wape * 100).toFixed(1),
    chosen: s.model === data.chosen_model,
  }))
  const m0 = data.cv_scores.find((s) => s.model === 'M0')
  const chosen = data.cv_scores.find((s) => s.model === data.chosen_model)
  const gain = m0 && chosen ? Math.round((1 - chosen.wape / m0.wape) * 100) : null

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-stone-900">예측이 얼마나 맞았나</h2>
        <p className="mt-1 text-sm text-stone-500">
          과거 기록을 시간순으로 나눠, 그때까지의 기록만으로 다음 날을 예측해 보고 실제와 비교했습니다.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-stone-200 bg-white p-5">
          <p className="text-sm text-stone-500">선택한 방법</p>
          <p className="mt-1 text-xl font-bold text-stone-900">
            {baseModel(data.chosen_model)} {MODEL_LABELS[baseModel(data.chosen_model)]}
          </p>
        </div>
        <div className="rounded-2xl border border-stone-200 bg-white p-5">
          <p className="text-sm text-stone-500">'지난주 같은 요일'보다</p>
          <p className="mt-1 text-xl font-bold text-stone-900">{gain !== null ? `오차 ${gain}% 적음` : '-'}</p>
          <p className="text-xs text-stone-400">검증 기간 기준</p>
        </div>
        <div className="rounded-2xl border border-stone-200 bg-white p-5">
          <p className="text-sm text-stone-500">실제가 예상 범위 안에 든 비율</p>
          <p className="mt-1 text-xl font-bold text-stone-900">
            {test[baseModel(data.chosen_model)] ? pct(test[baseModel(data.chosen_model)].coverage_80) : '-'}
          </p>
          <p className="text-xs text-stone-400">최종 테스트 기간 기준 (목표 80%)</p>
        </div>
      </div>

      <div className="rounded-2xl border border-stone-200 bg-white p-5">
        <h3 className="font-semibold text-stone-900">방법별 오차율 (검증 기간, 낮을수록 좋음)</h3>
        <p className="mt-1 text-xs text-stone-500">오차율 = 틀린 개수 합 ÷ 실제 판매량 합</p>
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
              <CartesianGrid vertical={false} stroke="#e7e5e4" />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#57534e' }} tickLine={false} axisLine={{ stroke: '#d6d3d1' }} />
              <YAxis unit="%" tick={{ fontSize: 12, fill: '#78716c' }} tickLine={false} axisLine={false} width={44} />
              <Tooltip
                cursor={{ fill: '#f5f5f4' }}
                formatter={(v) => [`${v}%`, '오차율']}
                labelStyle={{ color: '#1c1917', fontWeight: 600 }}
              />
              <Bar dataKey="wape" radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false}>
                {chart.map((d) => (
                  <Cell key={d.model} fill={d.chosen ? '#f97316' : '#d6d3d1'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b border-stone-200 text-left text-stone-500">
              <th className="py-2 font-medium">방법</th>
              <th className="py-2 text-right font-medium">검증 오차율</th>
              <th className="py-2 text-right font-medium">최종 테스트 오차율</th>
              <th className="py-2 text-right font-medium">범위 적중 (최종 테스트)</th>
            </tr>
          </thead>
          <tbody>
            {data.cv_scores.map((s) => {
              const t = s.model === data.chosen_model || s.model === 'M0' ? test[baseModel(s.model)] : undefined
              return (
                <tr key={s.model} className={`border-b border-stone-100 ${s.model === data.chosen_model ? 'font-semibold text-stone-900' : 'text-stone-600'}`}>
                  <td className="py-2">
                    {baseModel(s.model)} {MODEL_LABELS[baseModel(s.model)]}
                    {s.model === data.chosen_model && <span className="ml-2 text-xs text-orange-600">선택</span>}
                  </td>
                  <td className="py-2 text-right tabular-nums">{pct(s.wape)}</td>
                  <td className="py-2 text-right tabular-nums">{t ? pct(t.wape) : '-'}</td>
                  <td className="py-2 text-right tabular-nums">{t ? pct(t.coverage_80) : '-'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="rounded-2xl border border-stone-200 bg-white p-5">
        <h3 className="font-semibold text-stone-900">주변 정보를 쓸지 정한 이유</h3>
        <ul className="mt-3 space-y-2">
          {data.decisions.map((d) => (
            <li key={d.signal_group} className="flex items-start gap-3 text-sm">
              <span
                className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
                  d.adopted ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'
                }`}
              >
                {d.adopted ? '✓ 사용' : '사용 안 함'}
              </span>
              <span className="text-stone-700">
                <b className="font-semibold">{GROUP_LABELS[d.signal_group] ?? d.signal_group}</b> · {d.reason}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-2xl bg-stone-100 p-4 text-sm text-stone-600">
        <p className="font-semibold text-stone-700">데이터 메모</p>
        <p className="mt-1">{data.data_note}</p>
        {data.test_period && (
          <p className="mt-1 text-xs text-stone-500">
            최종 테스트 기간 {data.test_period[0]} ~ {data.test_period[1]} · 검증 구간 {data.folds.length}개
          </p>
        )}
      </div>
    </div>
  )
}
