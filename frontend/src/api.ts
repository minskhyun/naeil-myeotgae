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

// 정보원 선택 에이전트의 계획 (backend/collectors/agent.py가 만든 것 그대로)
export type SourcePlan = {
  method?: string // "llm" = AI가 고름, 그 밖 = 거리 규칙
  model?: string
  weather?: { use: boolean; reason: string }
  academic?: { school: string; evidence: string; distance_m: number; reason: string }[]
  events?: { radius_m: number; evidence: string[]; reason: string } | null
  candidates?: { source: string; evidence: string; distance_m: number; reason: string }[]
}

// 주변 정보를 어디서 왜 무엇을 모았는지 (contracts.SourceReport)
export type SourceReport = {
  store_id: string
  generated_at: string
  plan: SourcePlan | null
  n_nearby: number | null
  signals: { signal: string; n_days: number; first_date: string; last_date: string; n_menus: number; source_url: string | null; note: string | null }[]
  articles: { title: string; source_url: string; first_date: string; last_date: string; published_at: string | null }[]
  notes: string[]
}

// 매장 목록의 한 줄 (GET /api/stores). can_edit: 내가 고칠 수 있는 매장인지 (시연 매장·시연 모드는 false)
export type StoreInfo = { store_id: string; name: string; prep_mode: string; can_edit: boolean }

// 로그인한 사람 (GET /api/auth/me). 서버 규칙은 backend/app/auth.py
export type User = { email: string; name: string; picture: string | null; is_admin: boolean }

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
  // google_client_id가 있으면 서버가 로그인을 쓴다 → 구글 로그인 버튼을 보여 준다
  config: () => call<{ demo_mode: boolean; google_client_id: string | null }>('/config'),
  me: () => call<User | null>('/auth/me'),
  loginGoogle: (credential: string) =>
    call<User>('/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential }),
    }),
  logout: () => call<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  stores: () => call<StoreInfo[]>('/stores'),
  forecast: (id: string) => call<Forecast>(`/stores/${id}/forecast`),
  backtest: (id: string) => call<Backtest>(`/stores/${id}/backtest`),
  sources: (id: string) => call<SourceReport>(`/stores/${id}/sources`),
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
