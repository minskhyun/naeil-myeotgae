// '얼마나 맞나'의 결론 한 벌: 우리 예측(mine)과 '지난주 같은 요일만큼'(base)을 어느 기간으로 비교했는지.
// 최종 시험 기간이 있으면 그 결과를, 기록이 짧아(약 5주 미만) 없으면 검증 기간 결과를 쓴다.
// 로그인 뒤 요약(Dashboard)과 자세히 보기(BacktestView)가 같은 숫자를 보여 주도록 여기 한 곳에서 고른다.
import type { Backtest, ModelScore } from './api'
import { missPerDay, savedPerDay } from './format'

const span = (p: [string, string]) => Math.round((Date.parse(p[1]) - Date.parse(p[0])) / 86400000) + 1

export type Verdict = {
  final: boolean // true = 최종 시험 기간, false = 검증 기간
  mine: ModelScore
  base: ModelScore
  days: number // 비교한 날 수
  mineMiss: number // 하루에 남거나 모자란 개수 (모든 메뉴 합)
  baseMiss: number
  gain: number // 지난주 방식보다 몇 % 덜 틀렸나
  money: number | null // 판매가로 환산한 하루 차이 (판매가를 아는 매장만)
}

export function verdict(bt: Backtest | undefined): Verdict | null {
  if (!bt) return null
  const final = bt.test_scores.length > 0
  const rows = final ? bt.test_scores : bt.cv_scores
  const base = rows.find((s) => s.model === 'M0')
  const mine = rows.find((s) => s.model.includes('채택')) ?? rows.find((s) => s.model.slice(0, 2) === bt.chosen_model.slice(0, 2))
  if (!base || !mine || mine === base) return null
  const fallback = final && bt.test_period ? span(bt.test_period) : bt.folds.reduce((sum, f) => sum + span(f), 0)
  const days = mine.days || fallback
  const mineMiss = missPerDay(mine, days)
  const baseMiss = missPerDay(base, days)
  return { final, mine, base, days, mineMiss, baseMiss, gain: Math.round((1 - mineMiss / baseMiss) * 100), money: savedPerDay(mine, base) }
}

// "마지막 7일" / "검증 기간 14일"
export const periodName = (v: Verdict) => `${v.final ? '마지막' : '검증 기간'} ${v.days}일`
