import { SIGNAL_LABELS, type Reason } from './api'

const DAYS = '일월화수목금토'

// "2026-11-01" → "11월 1일 일요일"
export function fmtDate(iso: string) {
  const d = new Date(`${iso}T00:00:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${DAYS[d.getDay()]}요일`
}

// "2026-11-16T22:49:20" → "11월 16일 22:49"
export function fmtTime(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// −16 → "−16%", 5 → "+5%" (마이너스는 하이픈 대신 진짜 빼기 기호)
export const signedPct = (v: number) => `${v > 0 ? '+' : '−'}${Math.abs(Math.round(v))}%`

// 근거 한 줄을 표에 들어갈 짧은 말로: "비 −16%"
export const shortReason = (r: Reason) => `${SIGNAL_LABELS[r.signal] ?? r.signal} ${signedPct(r.effect_pct)}`

export const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`
