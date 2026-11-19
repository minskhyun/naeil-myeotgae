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
// demo: 누구나 보는 예시 매장인지 → 로그인 전 첫 화면(Landing.tsx)에만 보여 준다
export type StoreInfo = { store_id: string; name: string; prep_mode: string; can_edit: boolean; demo: boolean }

// 로그인한 사람 (GET /api/auth/me). 서버 규칙은 backend/app/auth.py
// provider: 어느 로그인인지. 카카오는 이메일 제공에 동의하지 않으면 email이 없다
export type User = { provider: 'google' | 'kakao'; email: string | null; name: string; picture: string | null; is_admin: boolean }

// 이 서버가 쓰는 로그인 방법 (GET /api/config에서 만든다). 하나도 없으면 로그인을 안 쓰는 서버
export type LoginConfig = { google: string | null; kakao: boolean } // google = 구글 클라이언트 ID

// '내 매장' 목록의 한 줄 (GET /api/my/stores). 아직 준비표가 없는 매장도 나온다
export type MyStore = {
  store_id: string
  name: string
  address: string | null
  close_time: string
  created_at: string | null
  updated_at: string | null // 마지막으로 준비표를 만든 때
  ready: boolean // 준비표가 있는지
  running: boolean // 지금 계산 중인지
  mine: boolean // 내가 만든 매장인지 (관리자는 남의 매장도 본다)
}

// 실행 중에 서버가 알려 주는 것 한 건 (ml/progress.py가 내보낸다) → '분석 중' 화면(AnalysisView.tsx)이 지도와 목록에 그린다
export type ProgressEvent =
  | { kind: 'step'; step: 'ingest' | 'collect' | 'evaluate' | 'predict'; status: 'start' | 'done'; note?: string }
  | { kind: 'status'; text: string } // 지금 하는 일 한 줄
  | { kind: 'store'; name: string; address?: string; lat?: number; lon?: number }
  | { kind: 'sales'; days: number; menus: number; first: string; last: string }
  | { kind: 'places'; count: number; places: { name: string; group: string; lat: number; lon: number; distance_m: number }[] }
  | { kind: 'plan'; method?: string; model?: string; radius_m?: number; reason?: string; picks: { what: string; name: string; lat: number; lon: number; reason?: string }[] }
  | { kind: 'weather'; days: number; first?: string; last?: string } // first~last = 가져온 기간 (판매 기록 기간 전체)
  | { kind: 'academic'; days: number; first?: string; last?: string; exams?: number; vacations?: number; festivals?: number }
  | { kind: 'event'; title: string; place?: string; lat: number; lon: number; start: string; end: string; source: string; url?: string }
  | { kind: 'article'; title: string; url: string }
  | { kind: 'special'; date: string; name: string; relevance?: number; menus?: string[]; reason?: string } // relevance·menus = AI가 매긴 연관도
  | { kind: 'trend_span'; menus: number; days: number; first: string; last: string } // 검색량을 가져온 기간
  | { kind: 'trend'; menu: string; pct: number } // 예측 날짜 기준: 최근 7일이 그 전 4주보다 몇 % 늘었나
  | { kind: 'rating'; title: string; scale: number; relevance: number; distance_m: number; menus: string[]; reason: string } // AI가 매긴 행사의 규모·연관도
  | { kind: 'trial'; groups: string[]; wape: number } // 검증 중: 이 정보 묶음을 넣어 시험했더니 오차가 이만큼
  | { kind: 'decision'; group: string; adopted: boolean; reason: string }
  | { kind: 'scores'; model: string; wape: number; base_wape: number; coverage: number; test_days?: number }
  | { kind: 'forecast'; date: string; menus: number; top: { menu: string; prep: number | null; pred: number }[]; warnings: string[] }

// 실행 작업 (예측 돌리기). 화면은 useJob.ts로 상태를 물어본다
export type Job = {
  job_id: string
  store_id: string
  status: 'running' | 'done' | 'error'
  log: string[]
  events: ProgressEvent[] // 실행 중에 찾은 것 한 건씩
  error: string | null
}

export const PREP_MODES = ['폐기 줄이기', '균형', '품절 줄이기'] as const

const JSON_BODY = { 'Content-Type': 'application/json' }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `요청 실패 (${res.status})`)
  }
  return res.json()
}

export const api = {
  // google_client_id가 있으면 구글 로그인 버튼을, kakao_login이면 카카오 로그인 버튼을 보여 준다
  config: () => call<{ demo_mode: boolean; google_client_id: string | null; kakao_login: boolean }>('/config'),
  me: () => call<User | null>('/auth/me'),
  loginGoogle: (credential: string) =>
    call<User>('/auth/google', { method: 'POST', headers: JSON_BODY, body: JSON.stringify({ credential }) }),
  logout: () => call<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  // 내 매장 관리 (로그인한 사람만). 매장 ID는 서버가 지어 준다
  myStores: () => call<MyStore[]>('/my/stores'),
  createStore: (name: string, closeTime: string) =>
    call<MyStore>('/my/stores', { method: 'POST', headers: JSON_BODY, body: JSON.stringify({ name, close_time: closeTime }) }),
  renameStore: (id: string, name: string) =>
    call<MyStore>(`/my/stores/${id}`, { method: 'PATCH', headers: JSON_BODY, body: JSON.stringify({ name }) }),
  deleteStore: (id: string) => call<{ ok: boolean }>(`/my/stores/${id}`, { method: 'DELETE' }),
  stores: () => call<StoreInfo[]>('/stores'),
  forecast: (id: string) => call<Forecast>(`/stores/${id}/forecast`),
  backtest: (id: string) => call<Backtest>(`/stores/${id}/backtest`),
  sources: (id: string) => call<SourceReport>(`/stores/${id}/sources`),
  progress: (id: string) => call<ProgressEvent[]>(`/stores/${id}/progress`), // 마지막 분석 때 알린 것 (다시 보기)
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
