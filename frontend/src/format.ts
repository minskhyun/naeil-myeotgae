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
  special_impact: '기념일 영향',
  trend_level: '검색량 유행',
}

export const GROUP_LABELS: Record<string, string> = {
  weather: '날씨',
  events: '학사일정·행사',
  trend: '유행',
  special: '기념일',
}

export const SCHOOL_LABELS: Record<string, string> = {
  yonsei: '연세대', sogang: '서강대', ewha: '이화여대',
  sunykorea: '한국뉴욕주립대', utah: '유타대 아시아캠퍼스', gmu: '한국조지메이슨대', ghent: '겐트대 글로벌캠퍼스',
}

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

// ---- 얼마나 맞나: 화면에 보여 주는 두 숫자
// 남거나 모자란 개수 (하루, 모든 메뉴 합) = 예측대로 준비했다면 남았을 개수 + 모자랐을 개수.
// 비율(오차율)로 보여 주지 않는 이유: 하루 한두 개 팔리는 메뉴는 한 개만 틀려도 50~100%가 되어 숫자가 뜻 없이 커진다.
// Σ|실제−예측| = mae × n 이라 예전 결과 파일에서도 계산된다. days가 없는 예전 파일은 fallbackDays(구간의 날짜 수)로 나눈다
export const missPerDay = (s: { mae: number; n: number; days?: number }, fallbackDays = 1) => (s.mae * s.n) / (s.days || fallbackDays || 1)
export const count = (v: number) => Math.round(v).toLocaleString('ko-KR')
// 금액: 1만 원 이상은 '12.3만 원', 그 아래는 천 원 단위
export const won = (v: number) => (Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}만 원` : `${count(Math.round(v / 100) * 100)}원`)
// 지난주 방식보다 하루에 덜 틀린 금액 (판매가를 아는 매장만)
export const savedPerDay = (mine: { amount?: number | null; days?: number }, base: { amount?: number | null }) =>
  mine.amount != null && base.amount != null && mine.days ? (base.amount - mine.amount) / mine.days : null

// 범위 정확도: 예상 범위는 실제 판매의 80%가 들어오도록 만든다 → 80%를 정확히 맞추면 100%(만점).
// 모자라면(범위가 좁다) 그만큼 깎고, 넘쳐도(범위가 쓸데없이 넓다) 같은 만큼 깎는다. 예: 75% → 93.8%, 90% → 87.5%
export const RANGE_TARGET = 0.8
export const rangeScore = (coverage: number) => Math.max(0, 1 - Math.abs(coverage - RANGE_TARGET) / RANGE_TARGET)

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

// ---- 요일 (준비표의 그래프와 문장이 쓴다)
export const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
export const asDate = (iso: string) => new Date(`${iso}T00:00:00`)
export const weekdayName = (iso: string) => WEEKDAYS[asDate(iso).getDay()]
// 내일(nextDate)과 같은 요일의 지난 판매 (오래된 것부터, 휴무일은 뺀다)
export function sameWeekday(dates: string[], values: (number | null)[], nextDate: string): number[] {
  const weekday = asDate(nextDate).getDay()
  return values.filter((v, i): v is number => v !== null && asDate(dates[i]).getDay() === weekday)
}
export const average = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null)

// 예측 날짜를 부르는 말. 예측 날짜 = 판매 기록 마지막 날의 다음 날이라, 화면을 보는 날의 '내일'이 아닐 수 있다
// (어제까지의 기록을 오늘 올리면 예측 날짜는 오늘이다). 오늘이면 '오늘', 내일이면 '내일', 그 밖은 '이날'
export function dayWord(iso: string): '오늘' | '내일' | '이날' {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const gap = Math.round((asDate(iso).getTime() - today) / 86400000)
  return gap === 0 ? '오늘' : gap === 1 ? '내일' : '이날'
}
// 문장 앞에 붙이는 꼴: '오늘 ' · '내일 ' · '' (오늘도 내일도 아니면 아무 말도 붙이지 않는다 → "준비할 개수", "예상")
export const dayPrefix = (iso: string) => {
  const word = dayWord(iso)
  return word === '이날' ? '' : `${word} `
}
