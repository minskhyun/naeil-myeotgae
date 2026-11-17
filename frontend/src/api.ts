// 백엔드(backend/app/main.py)와 주고받는 데이터와 요청 함수.
// 타입은 contracts/schemas.py와 같다 → 그쪽 형식을 바꾸면 여기도 같이 고친다.

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

// 매장 목록의 한 줄 (GET /api/stores)
export type StoreInfo = { store_id: string; name: string; prep_mode: string }

// 실행 작업 (예측 돌리기). 화면은 useJob.ts로 상태를 물어본다
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
  config: () => call<{ demo_mode: boolean }>('/config'),
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
  // 사장님은 POS 파일과 주소만 준다. 주변 정보는 서버가 주소로 자동 수집한다.
  run: (id: string, pos: File, opts: { closeTime?: string; address?: string }) => {
    const form = new FormData()
    form.append('pos', pos)
    if (opts.closeTime) form.append('close_time', opts.closeTime)
    if (opts.address) form.append('address', opts.address)
    return call<Job>(`/stores/${id}/run`, { method: 'POST', body: form })
  },
}
