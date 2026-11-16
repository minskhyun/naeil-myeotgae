// 백엔드(backend/app/main.py)와 주고받는 데이터. 형식은 contracts/schemas.py와 같다.

export type Reason = { signal: string; effect_pct: number; text: string; source_url: string | null }

export type ForecastRow = {
  date: string
  menu: string
  pred: number // 예상 판매량 (= p50)
  p10: number // 예상 범위 아래 끝
  p90: number // 예상 범위 위 끝
  prep_qty: number | null // 준비 권장량
  model: string
  reasons: Reason[]
}

export type Evidence = { source_url: string; quote: string }

export type Warning = {
  date: string
  menu_scope: string[] // ["*"] = 전체 메뉴
  situation_type: string
  direction: '증가' | '감소' | '불확실'
  strength: '낮음' | '중간' | '높음'
  evidence: Evidence[]
  message: string
}

export type Forecast = {
  store_id: string
  generated_at: string
  rows: ForecastRow[]
  signals_used: string[]
  warnings: Warning[]
}

export type ModelScore = {
  model: string
  wape: number
  mae: number
  bias: number
  coverage_80: number
  n: number
  wape_by_fold: number[]
}

export type SignalDecision = {
  signal_group: string
  signals: string[]
  adopted: boolean
  wape_change_pct: number
  folds_improved: number
  folds_total: number
  reason: string
}

export type Backtest = {
  store_id: string
  generated_at: string
  folds: [string, string][]
  test_period: [string, string] | null
  cv_scores: ModelScore[]
  decisions: SignalDecision[]
  chosen_model: string
  test_scores: ModelScore[]
  data_note: string
  calibration?: { adopted: boolean; reason: string } | null
}

export type StoreInfo = {
  store_id: string
  name: string
  prep_mode: string
  close_time: string | null
  has_backtest: boolean
  running: boolean
}

export type Job = {
  job_id: string
  store_id: string
  status: 'running' | 'done' | 'error'
  log: string[]
  error: string | null
}

export const PREP_MODES = ['폐기 줄이기', '균형', '품절 줄이기'] as const

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `요청 실패 (${res.status})`)
  }
  return res.json()
}

export const api = {
  stores: () => call<StoreInfo[]>('/stores'),
  forecast: (id: string) => call<Forecast>(`/stores/${id}/forecast`),
  backtest: (id: string) => call<Backtest>(`/stores/${id}/backtest`),
  job: (jobId: string) => call<Job>(`/jobs/${jobId}`),
  demo: () => call<Job>('/stores/sinchon-a/demo', { method: 'POST' }),
  setPrepMode: (id: string, prepMode: string) => {
    const form = new FormData()
    form.append('prep_mode', prepMode)
    return call<Job>(`/stores/${id}/settings`, { method: 'POST', body: form })
  },
  run: (id: string, files: { pos: File; signals?: File; collection?: File }, closeTime?: string) => {
    const form = new FormData()
    form.append('pos', files.pos)
    if (files.signals) form.append('signals', files.signals)
    if (files.collection) form.append('collection', files.collection)
    if (closeTime) form.append('close_time', closeTime)
    return call<Job>(`/stores/${id}/run`, { method: 'POST', body: form })
  },
}

// 화면에 보여 줄 이름
export const SIGNAL_LABELS: Record<string, string> = {
  temp_diff: '기온',
  rain_mm: '비',
  exam_period: '시험기간',
  vacation: '방학',
  festival: '축제',
  nearby_event: '근처 행사',
  special_day: '기념일',
  trend_level: '유행',
}

export const GROUP_LABELS: Record<string, string> = {
  weather: '날씨',
  events: '학사일정·행사',
  trend: '유행',
  special: '기념일',
}

export const MODEL_LABELS: Record<string, string> = {
  M0: '지난주 같은 요일만큼',
  M1: '판매 기록',
  M2: '판매 기록 + 날씨',
  M3: '판매 기록 + 날씨·행사',
}
