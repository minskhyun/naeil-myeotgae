// 일하는 화면: 고른 매장의 분석 결과를 한눈에 (Dashboard.tsx: 요약 숫자 · 준비표 · 주의 안내 · 쓴 정보 · 정확도).
// 매장 추가와 매장 관리는 탭이 아니라 위에 뜨는 창(Modal)으로 연다.
// '분석 및 예측하기'를 누르면 창이 닫히고 '분석 중' 화면(AnalysisView)이 화면 전체에 뜬다: 찾은 정보가 지도 위에서 가게로 모인다.
// 로그인을 쓰는 서버에서는 로그인한 뒤에 나오고, 예시(시연) 매장은 보이지 않는다 → 내 매장만.
// 로그인을 안 쓰는 서버(혼자 쓰는 노트북)에서는 처음부터 이 화면이고 모든 매장이 보인다.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type LoginConfig } from './api'
import { AnalysisView } from './AnalysisView'
import { AccountBox } from './Auth'
import { Dashboard } from './Dashboard'
import { Modal } from './Modal'
import { StoresView } from './StoresView'
import { UploadView } from './UploadView'
import { useJob } from './useJob'

// 지금 떠 있는 창: 판매 기록 올리기(target = 다시 올릴 매장, null이면 새 매장) 또는 내 매장 관리
type Dialog = { kind: 'upload'; target: string | null } | { kind: 'stores' } | null

// login: 서버가 쓰는 로그인 방법(= 계정 방식). 로그인을 안 쓰는 서버면 null
export function Workspace({ login }: { login: LoginConfig | null }) {
  const account = !!login
  const all = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const stores = all.data?.filter((s) => !account || !s.demo) // 계정 방식이면 예시 매장을 뺀다
  // 주소로도 매장을 고르고 창을 열 수 있다: ?store=sinchon-a , ?open=add (매장 추가) , ?open=stores (매장 관리)
  const params = new URLSearchParams(window.location.search)
  const [picked, setStoreId] = useState(params.get('store'))
  const [dialog, setDialog] = useState<Dialog>(
    params.get('open') === 'add' ? { kind: 'upload', target: null } : params.get('open') === 'stores' && account ? { kind: 'stores' } : null,
  )
  // 준비표를 만드는 작업은 여기서 지켜본다 → 창을 닫아도 계속 이어지고, 끝나면 그 매장을 보여 준다
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob(jobId, (id) => setStoreId(id))
  const running = job?.status === 'running'
  const [watching, setWatching] = useState(false) // '분석 중' 화면을 보고 있는가 (닫아도 분석은 계속된다)
  const [replaying, setReplaying] = useState(params.get('open') === 'replay') // 지난 분석 과정을 다시 보는 중

  // 고른 매장이 목록에 없으면 첫 매장
  const listed = !stores || stores.some((s) => s.store_id === picked)
  const storeId = (picked && listed ? picked : stores?.[0]?.store_id) ?? null
  const store = stores?.find((s) => s.store_id === storeId)
  const empty = !!stores && !stores.length
  const addLabel = account ? '매장 추가' : '데이터 올리기'

  // 이 매장을 마지막으로 분석했을 때의 과정 (있으면 '분석 과정 다시 보기'를 보여 준다)
  const past = useQuery({ queryKey: ['progress', storeId], queryFn: () => api.progress(storeId!), enabled: !!storeId, retry: false }).data

  const openUpload = (target: string | null) => setDialog({ kind: 'upload', target })
  // 분석이 시작되면: 올리기 창을 닫고 분석 화면을 띄운다
  const started = (id: string) => {
    setJobId(id)
    setDialog(null)
    setWatching(true)
  }
  const close = () => setDialog(null)

  return (
    <div className="min-h-screen">
      <header className="bg-sheet shadow-sm">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-8 gap-y-3 px-5 py-3.5">
          <h1 className="text-xl font-extrabold tracking-tight">내일몇개</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {!!stores?.length && (
              <label className="flex items-center gap-2 text-sm text-muted">
                {account ? '내 매장' : '매장'}
                <select
                  value={storeId ?? ''}
                  onChange={(e) => setStoreId(e.target.value)}
                  className="rounded-full border border-rule bg-sheet px-3 py-1.5 text-ink focus:border-accent focus:outline-none"
                >
                  {stores.map((s) => (
                    <option key={s.store_id} value={s.store_id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button onClick={() => openUpload(null)} className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-ink/85">
              {addLabel}
            </button>
            {account && (
              <button onClick={() => setDialog({ kind: 'stores' })} className="rounded-full border border-rule bg-sheet px-4 py-2 text-sm font-semibold hover:bg-paper">
                매장 관리
              </button>
            )}
            {login && <AccountBox login={login} />}
          </div>
        </div>
      </header>

      {running && !watching && (
        <p className="bg-accent-soft px-5 py-2.5 text-center text-sm text-accent-deep">
          준비표를 만드는 중입니다…{' '}
          <button onClick={() => setWatching(true)} className="font-semibold underline underline-offset-4 hover:text-accent">
            진행 상황 보기
          </button>
        </p>
      )}

      <main className="mx-auto max-w-7xl px-5 py-8">
        {all.error && <p className="mb-8 border-l-4 border-up bg-sheet px-4 py-3 text-sm">매장 목록을 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}

        {empty && (
          <section className="mx-auto max-w-xl rounded-3xl bg-sheet px-8 py-12 text-center shadow-sm">
            <h2 className="text-3xl font-bold tracking-tight">{account ? '첫 매장을 추가해 주세요' : '아직 준비표가 없습니다'}</h2>
            <p className="mt-2 mb-5 text-muted">
              매장 이름, 위치, 닫는 시간을 적고 포스에서 내려받은 판매 기록 파일을 올리면 내일 준비표가 만들어집니다.
            </p>
            <button onClick={() => openUpload(null)} className="rounded-full bg-accent px-6 py-3 font-semibold text-white hover:bg-accent-deep">
              {addLabel}
            </button>
          </section>
        )}

        {storeId && (
          <Dashboard
            storeId={storeId}
            storeName={store?.name ?? storeId}
            prepMode={store?.prep_mode ?? '균형'}
            readOnly={store?.can_edit === false}
            onReplay={past?.length ? () => setReplaying(true) : undefined}
          />
        )}
      </main>

      {dialog?.kind === 'upload' && (
        <Modal label={addLabel} onClose={close}>
          <UploadView
            key={dialog.target ?? 'new'}
            onStarted={started}
            busy={running}
            account={account}
            initialTarget={dialog.target}
            first={account && empty}
          />
        </Modal>
      )}
      {watching && job && (
        <AnalysisView events={job.events} status={job.status} error={job.error} log={job.log} onClose={() => setWatching(false)} />
      )}
      {replaying && past && !watching && <AnalysisView events={past} status="done" replay onClose={() => setReplaying(false)} />}
      {dialog?.kind === 'stores' && (
        <Modal label="매장 관리" onClose={close}>
          <StoresView
            onOpen={(id) => {
              setStoreId(id)
              close()
            }}
            onUpload={openUpload}
          />
        </Modal>
      )}
    </div>
  )
}
