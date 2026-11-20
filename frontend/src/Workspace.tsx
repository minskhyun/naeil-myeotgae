// 분석 화면 ('/app'): 왼쪽 사이드바 + 오른쪽 내용. 탭은 셋이다.
//   대시보드   판매 기록 올리기(분석 시작) · 준비표 · 주의할 소식        (Dashboard.tsx의 DashboardTab)
//   분석       예측 정확도 · 판매 그래프 · 예측에 쓴 주변 정보            (Dashboard.tsx의 AnalysisTab)
//   매장 관리   매장 이름·주소·닫는 시간 고치기, 다시 올리기, 지우기       (StoresView.tsx, 로그인한 사람만)
// 첫 매장을 만들 때는 사이드바 없이 화면 전체에 매장 정보·판매 기록 올리기·분석 시작을 펼친다.
// 그다음부터 '매장 추가'는 위에 뜨는 창(Modal)으로 연다.
// '분석 및 예측하기'를 누르면 '분석 중' 화면(AnalysisView)이 화면 전체에 뜬다: 찾은 정보가 지도 위에서 가게로 모인다.
// 로그인을 쓰는 서버에서는 내 매장만 보인다. 로그인을 안 쓰는 서버(혼자 쓰는 노트북)에서는 모든 매장이 보이고 매장 관리 탭이 없다.
// 주소로도 고를 수 있다: ?tab=analysis · ?tab=stores · ?store=매장ID · ?open=add (매장 추가 창) · ?open=replay (분석 과정 다시 보기)
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type LoginConfig } from './api'
import { AnalysisView } from './AnalysisView'
import { AccountBox } from './Auth'
import { AnalysisTab, DashboardTab } from './Dashboard'
import { Modal } from './Modal'
import { Lines } from './Reveal'
import { StoresView } from './StoresView'
import { UploadView } from './UploadView'
import { useJob } from './useJob'

type Tab = 'dashboard' | 'analysis' | 'stores'
const TABS: { id: Tab; text: string; label: string }[] = [
  { id: 'dashboard', text: '대시보드', label: '준비표 · 주의할 소식' },
  { id: 'analysis', text: '분석', label: '정확도 · 그래프' },
  { id: 'stores', text: '매장 관리', label: '이름 · 주소' },
]

// 첫 매장을 만드는 순서 (화면 전체에 펼친 첫 화면의 왼쪽에 적는다)
const FIRST_STEPS = ['매장 이름과 위치를 적어요', '포스에서 내려받은 판매 기록 파일을 올려요', '분석을 누르면 몇 분 뒤 준비표가 나와요']

// login: 서버가 쓰는 로그인 방법(= 계정 방식). 로그인을 안 쓰는 서버면 null
export function Workspace({ login }: { login: LoginConfig | null }) {
  const account = !!login
  const all = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const stores = all.data?.filter((s) => !account || !s.demo) // 준비표가 있는 매장들. 계정 방식이면 예시 매장을 뺀다
  const mine = useQuery({ queryKey: ['myStores'], queryFn: api.myStores, enabled: account }).data // 내가 만든 매장 (준비표가 없는 것도)
  const params = new URLSearchParams(window.location.search)
  const [picked, setStoreId] = useState(params.get('store'))
  const asked = params.get('tab') ?? (params.get('open') === 'stores' ? 'stores' : null)
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.id === asked) ? (asked as Tab) : 'dashboard')
  const [adding, setAdding] = useState<{ target: string | null } | null>(params.get('open') === 'add' ? { target: null } : null) // 올리기 창 (target = 다시 올릴 매장, null이면 새 매장)
  // 준비표를 만드는 작업은 여기서 지켜본다 → 창을 닫아도 계속 이어지고, 끝나면 그 매장의 대시보드를 보여 준다
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob(jobId, (id) => {
    setStoreId(id)
    setTab('dashboard')
  })
  const running = job?.status === 'running'
  const [watching, setWatching] = useState(false) // '분석 중' 화면을 보고 있는가 (닫아도 분석은 계속된다)
  const [replaying, setReplaying] = useState(params.get('open') === 'replay') // 지난 분석 과정을 다시 보는 중

  // 고른 매장이 목록에 없으면 첫 매장
  const listed = !stores || stores.some((s) => s.store_id === picked)
  const storeId = (picked && listed ? picked : stores?.[0]?.store_id) ?? null
  const store = stores?.find((s) => s.store_id === storeId)
  // 아직 매장을 하나도 만들지 않았는가 (계정 방식: 내가 만든 매장이 없다, 아니면: 준비표가 하나도 없다)
  const loaded = !!stores && (!account || !!mine)
  const first = loaded && (account ? !mine!.length : !stores.length)
  const tabs = TABS.filter((t) => t.id !== 'stores' || account)
  const showing: Tab = !storeId && account ? 'stores' : tab // 준비표가 있는 매장이 아직 없으면 매장 관리부터

  // 이 매장을 마지막으로 분석했을 때의 과정 (있으면 '분석 과정 다시 보기'를 보여 준다)
  const past = useQuery({ queryKey: ['progress', storeId], queryFn: () => api.progress(storeId!), enabled: !!storeId, retry: false }).data

  // 분석이 시작되면: 올리기 창을 닫고 분석 화면을 띄운다
  const started = (id: string) => {
    setJobId(id)
    setAdding(null)
    setWatching(true)
  }
  const overlays = (
    <>
      {watching && job && <AnalysisView events={job.events} status={job.status} error={job.error} log={job.log} onClose={() => setWatching(false)} />}
      {replaying && past && !watching && <AnalysisView events={past} status="done" replay onClose={() => setReplaying(false)} />}
    </>
  )
  const logo = (
    <a href="/" className="text-xl font-[800] tracking-[-0.05em]" aria-label="내일몇개 첫 화면" title="첫 화면으로">
      내일몇개
    </a>
  )

  // ---------------------------------------------------------------- 첫 매장: 사이드바 없이 화면 전체에
  if (first && !running) {
    return (
      <div className="min-h-screen">
        <header className="mx-auto flex min-h-16 max-w-content items-center justify-between gap-6 px-5 py-2 md:px-10">
          {logo}
          {login && <AccountBox login={login} />}
        </header>
        <main className="mx-auto grid max-w-content gap-12 px-5 pt-10 pb-24 md:px-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16 lg:pt-20">
          <div className="lg:sticky lg:top-24 lg:self-start">
            <p className="font-mono text-ink-500">Start</p>
            <h1 className="nm-enter mt-5 text-title">
              <span>첫 매장을</span>
              <span style={{ animationDelay: '220ms' }}>만들어 볼까요</span>
            </h1>
            <p className="mt-6 text-xl leading-8 text-ink-700">판매 기록 파일 하나면 돼요. 날씨와 주변 소식은 가게 위치로 저희가 찾아 붙여요.</p>
            <ol className="mt-10 space-y-4">
              {FIRST_STEPS.map((text, i) => (
                <li key={text} className="flex items-center gap-4 text-lg">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white font-mono text-sm text-ink-700">{i + 1}</span>
                  {text}
                </li>
              ))}
            </ol>
          </div>
          <div className="rounded-[32px] bg-white p-6 sm:p-10">
            <UploadView onStarted={started} busy={running} account={account} first bare />
          </div>
        </main>
        {overlays}
      </div>
    )
  }

  // ---------------------------------------------------------------- 사이드바 + 탭
  return (
    <div className="min-h-screen md:flex">
      <aside className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-3 bg-white px-5 py-3 md:sticky md:top-0 md:h-screen md:w-64 md:flex-col md:flex-nowrap md:items-stretch md:gap-0 md:px-5 md:py-7">
        <div className="md:px-3">{logo}</div>

        {!!stores?.length && (
          <label className="block md:mt-8">
            <span className="hidden px-3 text-label text-ink-500 md:block">{account ? '내 매장' : '매장'}</span>
            <select
              value={storeId ?? ''}
              onChange={(e) => setStoreId(e.target.value)}
              className="h-11 w-full max-w-56 rounded-xl bg-page px-3 font-medium text-ink-900 focus:outline-none md:mt-2 md:max-w-none"
              aria-label="매장 고르기"
            >
              {stores.map((s) => (
                <option key={s.store_id} value={s.store_id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}

        <nav className="flex gap-1 md:mt-8 md:flex-col" aria-label="분석 화면의 탭">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              aria-current={showing === t.id ? 'page' : undefined}
              className={`rounded-xl px-3 py-2.5 text-left transition-colors duration-150 ${showing === t.id ? 'bg-page font-semibold text-ink-900' : 'text-ink-700 hover:bg-page'}`}
            >
              <span className="block">{t.text}</span>
              <span className="hidden text-sm font-normal text-ink-500 md:block">{t.label}</span>
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3 md:mt-auto md:ml-0 md:flex-col md:items-stretch md:gap-4">
          <button onClick={() => setAdding({ target: null })} className="btn-md btn-primary">
            {account ? '매장 추가' : '데이터 올리기'}
          </button>
          {login && (
            <div className="md:px-3">
              <AccountBox login={login} />
            </div>
          )}
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        {running && !watching && (
          <p className="bg-ink-900 px-5 py-2.5 text-center text-sm text-white">
            준비표를 만드는 중입니다…{' '}
            <button onClick={() => setWatching(true)} className="font-semibold underline underline-offset-4 hover:text-white/80">
              진행 상황 보기
            </button>
          </p>
        )}
        <main className="mx-auto max-w-[1180px] px-5 py-8 md:px-10 md:py-12">
          {all.error && <p className="mb-8 rounded-2xl bg-white px-5 py-4 text-sm text-down">매장 목록을 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}

          {showing === 'stores' && account && (
            <StoresView
              onOpen={(id) => {
                setStoreId(id)
                setTab('dashboard')
              }}
              onUpload={(target) => setAdding({ target })}
            />
          )}
          {showing !== 'stores' && !storeId && loaded && (
            <div className="rounded-[32px] bg-white p-8">
              <Lines as="h2" text={'아직 준비표가 없어요'} className="text-h1" />
              <p className="mt-4 text-lg text-ink-700">판매 기록 파일을 올리면 몇 분 뒤 준비표가 만들어집니다.</p>
              <button onClick={() => setAdding({ target: null })} className="btn-xl btn-primary mt-8">
                판매 기록 올리기
              </button>
            </div>
          )}
          {showing === 'dashboard' && storeId && (
            <DashboardTab
              storeId={storeId}
              storeName={store?.name ?? storeId}
              prepMode={store?.prep_mode ?? '균형'}
              readOnly={store?.can_edit === false}
              onUpload={store?.can_edit === false ? undefined : () => setAdding({ target: account ? storeId : null })}
            />
          )}
          {showing === 'analysis' && storeId && (
            <AnalysisTab storeId={storeId} storeName={store?.name ?? storeId} onReplay={past?.length ? () => setReplaying(true) : undefined} />
          )}
        </main>
      </div>

      {adding && (
        <Modal label={account ? '매장 추가' : '데이터 올리기'} onClose={() => setAdding(null)}>
          <UploadView key={adding.target ?? 'new'} onStarted={started} busy={running} account={account} initialTarget={adding.target} />
        </Modal>
      )}
      {overlays}
    </div>
  )
}
