// 화면 표시용: 이름표(신호·모델 이름을 쉬운 말로)와 날짜·퍼센트 모양
import type { Reason } from './api'

// ---- 이름표: 코드 속 이름 → 화면에 보여 줄 말. 새 신호를 추가하면 여기에도 한 줄
export const SIGNAL_LABELS: Record<string, string> = {
  temp_mean: '기온',
  temp_diff: '기온',
  rain_mm: '비',
  exam_period: '시험기간',
  vacation: '방학',
  festival: '축제',
  nearby_event: '근처 행사',
  event_impact: '행사 영향',
  special_day: '기념일',
  special_lead: '기념일 앞둔 날',
  trend_level: '검색량 유행',
}

export const GROUP_LABELS: Record<string, string> = {
  weather: '날씨',
  events: '학사일정·행사',
  trend: '유행',
  special: '기념일',
}

export const SCHOOL_LABELS: Record<string, string> = { yonsei: '연세대', sogang: '서강대', ewha: '이화여대' }

export const MODEL_LABELS: Record<string, string> = {
  M0: '지난주 같은 요일만큼',
  M1: '판매 기록',
  M2: '판매 기록 + 날씨',
  M3: '판매 기록 + 모든 주변 정보',
}

// ---- 날짜·숫자 모양

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

// 0.191 → "19.1%"
export const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`

// '분석 중' 화면에서 정보 종류마다 쓰는 색 (지도의 표시와 목록의 이름표가 같은 색)
export const KIND_COLOR: Record<string, string> = {
  places: '#8a9bbd',
  plan: '#2b66f6',
  event: '#ff7a45',
  news: '#f43f8e',
  weather: '#0ea5e9',
  academic: '#8b5cf6',
  special: '#f59e0b',
  trend: '#10b981',
  sales: '#15171c',
  article: '#f43f8e',
}
