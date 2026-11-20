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

// 신호 묶음의 이름 (ml/features.py의 SIGNAL_GROUPS). 채택 여부를 이 단위로 정한다
// weather · events = 분야 이름: 묶음을 잘게 나누기 전(11/20 전)에 분석한 매장의 결과에 적혀 있다
export const GROUP_LABELS: Record<string, string> = {
  temp: '기온',
  rain: '비',
  exam: '시험기간',
  vacation: '방학',
  festival: '학교 축제',
  nearby: '근처 행사',
  trend: '유행',
  special: '기념일',
  weather: '날씨',
  events: '학사일정·행사',
}

// AI 안내의 상황 종류(contracts.Warning.situation_type)를 화면에 적는 말.
// 계약의 '대형행사'는 작은 북 콘서트에도 붙어 과하게 읽힌다 → 화면에서는 '근처 행사'
export const SITUATION_LABELS: Record<string, string> = {
  대형행사: '근처 행사',
  유행급변: '유행 변화',
  기상특보: '날씨 특보',
  휴무가능성: '휴무 가능성',
  데이터이상: '기록 확인 필요',
}

// "2026-11-18" → "11월 18일"
export const shortDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일`
}

export const SCHOOL_LABELS: Record<string, string> = {
  yonsei: '연세대', sogang: '서강대', ewha: '이화여대',
  sunykorea: '한국뉴욕주립대', utah: '유타대 아시아캠퍼스', gmu: '한국조지메이슨대', ghent: '겐트대 글로벌캠퍼스',
}

export const MODEL_LABELS: Record<string, string> = {
  M0: '지난주 같은 요일 그대로',
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
// 예상 범위 표기: 아래 끝은 내림, 위 끝은 올림 (바깥쪽으로 반올림). 범위를 좁혀 적지 않기 위해서다.
// 가까운 수로 반올림하면 4.6개(1.9~5.1)가 "5개, 범위 2–5"로 보여 예상값이 범위 끝에 붙은 것처럼 읽힌다.
export const rangeText = (lo: number, hi: number) => `${Math.floor(lo + 1e-6).toLocaleString('ko-KR')}–${Math.ceil(hi - 1e-6).toLocaleString('ko-KR')}`
// 금액: 1만 원 이상은 '12.3만 원', 그 아래는 천 원 단위
export const won = (v: number) => (Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}만 원` : `${count(Math.round(v / 100) * 100)}원`)
// 지난주 방식보다 하루에 덜 틀린 금액 (판매가를 아는 매장만)
export const savedPerDay = (mine: { amount?: number | null; days?: number }, base: { amount?: number | null }) =>
  mine.amount != null && base.amount != null && mine.days ? (base.amount - mine.amount) / mine.days : null

// 예상 범위는 실제 판매의 80%가 들어오도록 만든다. 화면에는 실제로 든 비율을 그대로 적고 목표(80%)를 옆에 둔다
// (목표에 견준 점수로 바꿔 적으면 숫자가 실제보다 좋아 보인다)
// '목표 80%'라고 적으면 못 채운 점수처럼 읽히고, '80%가 이상적'만 적으면 무슨 뜻인지 알 수 없다 → 왜 80%인지를 적는다 (그림은 RangeMeter.tsx)
export const RANGE_TARGET_TEXT = '10번 중 8번 들도록 잡은 폭이라, 80%에 가까울수록 알맞아요'
export const RANGE_TARGET = 80 // 예상 범위에 들도록 잡은 비율(%)
export const RANGE_NEAR = 5 // 목표에서 이만큼(%p) 안이면 '알맞다'고 적는다
// 실제로 든 비율(0~1) → 범위의 폭이 어떤지 한마디
export function rangeVerdict(value: number) {
  const pct = value * 100
  if (Math.abs(pct - RANGE_TARGET) <= RANGE_NEAR) return '알맞게 잡혔어요'
  return pct < RANGE_TARGET ? '조금 좁게 잡혔어요' : '조금 넓게 잡혔어요'
}

// '분석 중' 화면에서 정보 종류마다 쓰는 색 (지도의 표시와 목록의 이름표가 같은 색)
export const KIND_COLOR: Record<string, string> = {
  places: '#FF5A1F', // point (작은 점은 CSS에서 옅게 칠한다)
  plan: '#C2410C', // point-text
  event: '#FF5A1F', // point
  news: '#C2410C',
  weather: '#C2410C',
  academic: '#C2410C',
  special: '#C2410C',
  trend: '#C2410C',
  sales: '#14171C', // ink-900 (지도에는 나오지 않고 목록에만 쓴다)
  article: '#C2410C',
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

// 수집한 글의 제목을 화면에 적기 좋게: 깨진 기호(&#x27; &quot; 등)를 원래 글자로 돌리고, 뒤에 붙은 메뉴 경로(" < 사회 < 기사본문 - …")를 뗀다
export function cleanTitle(title: string) {
  const plain = new DOMParser().parseFromString(title, 'text/html').documentElement.textContent ?? title
  return plain.split(' < ')[0].trim()
}
