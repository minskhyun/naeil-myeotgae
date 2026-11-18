// 일하는 화면: 고른 매장의 분석을 한 쪽에 차례로 (내일 준비표 → 주변 정보 → 얼마나 맞나).
// 매장 추가와 매장 관리는 탭이 아니라 위에 뜨는 창(Modal)으로 연다.
// 로그인을 쓰는 서버에서는 로그인한 뒤에 나오고, 예시(시연) 매장은 보이지 않는다 → 내 매장만.
// 로그인을 안 쓰는 서버(혼자 쓰는 노트북)에서는 처음부터 이 화면이고 모든 매장이 보인다.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type LoginConfig } from './api'
import { AccountBox } from './Auth'
import { BacktestView } from './BacktestView'
import { ForecastView } from './ForecastView'
import { Modal } from './Modal'
import { SourcesView } from './SourcesView'
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

  // 고른 매장이 목록에 없으면 첫 매장
  const listed = !stores || stores.some((s) => s.store_id === picked)
  const storeId = (picked && listed ? picked : stores?.[0]?.store_id) ?? null
  const store = stores?.find((s) => s.store_id === storeId)
  const empty = !!stores && !stores.length
  const addLabel = account ? '매장 추가' : '데이터 올리기'

  const openUpload = (target: string | null) => {
    if (!running) setJobId(null) // 끝난 지난 작업의 기록은 지우고 새로 시작
    setDialog({ kind: 'upload', target })
  }
  const close = () => setDialog(null)

  return (
    <div className="min-h-screen">
      <header className="border-b border-ink/80 bg-sheet">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-8 gap-y-3 px-5 py-3.5">
          <h1 className="text-xl font-extrabold tracking-tight">내일몇개</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {!!stores?.length && (
              <label className="flex items-center gap-2 text-sm text-muted">
                {account ? '내 매장' : '매장'}
                <select
                  value={storeId ?? ''}
                  onChange={(e) => setStoreId(e.target.value)}
                  className="border border-rule bg-sheet px-2 py-1.5 text-ink focus:border-ink focus:outline-none"
                >
                  {stores.map((s) => (
                    <option key={s.store_id} value={s.store_id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button onClick={() => openUpload(null)} className="bg-accent px-3.5 py-1.5 text-sm font-semibold text-white hover:bg-accent/90">
              {addLabel}
            </button>
            {account && (
              <button onClick={() => setDialog({ kind: 'stores' })} className="border border-ink/80 bg-sheet px-3.5 py-1.5 text-sm hover:bg-paper">
                매장 관리
              </button>
            )}
            {login && <AccountBox login={login} />}
          </div>
        </div>
      </header>

      {running && !dialog && (
        <p className="border-b border-rule bg-accent-soft px-5 py-2 text-center text-sm">
          준비표를 만드는 중입니다…{' '}
          <button onClick={() => setDialog({ kind: 'upload', target: null })} className="underline underline-offset-4 hover:text-accent">
            진행 상황 보기
          </button>
        </p>
      )}

      <main className="mx-auto max-w-6xl px-5 py-10">
        {all.error && <p className="mb-8 border-l-4 border-up bg-sheet px-4 py-3 text-sm">매장 목록을 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}

        {empty && (
          <section className="max-w-xl">
            <h2 className="text-3xl font-bold tracking-tight">{account ? '첫 매장을 추가해 주세요' : '아직 준비표가 없습니다'}</h2>
            <p className="mt-2 mb-5 text-muted">
              매장 이름, 위치, 닫는 시간을 적고 포스에서 내려받은 판매 기록 파일을 올리면 내일 준비표가 만들어집니다.
            </p>
            <button onClick={() => openUpload(null)} className="bg-accent px-5 py-2.5 font-semibold text-white hover:bg-accent/90">
              {addLabel}
            </button>
          </section>
        )}

        {storeId && (
          <div className="space-y-14">
            <ForecastView storeId={storeId} prepMode={store?.prep_mode ?? '균형'} readOnly={store?.can_edit === false} />
            <section className="border-t border-ink/80 pt-10">
              <SourcesView storeId={storeId} />
            </section>
            <section className="border-t border-ink/80 pt-10">
              <BacktestView storeId={storeId} />
            </section>
          </div>
        )}
      </main>

      {dialog?.kind === 'upload' && (
        <Modal label={addLabel} onClose={close}>
          <UploadView
            key={dialog.target ?? 'new'}
            job={job}
            onStarted={setJobId}
            onClose={close}
            account={account}
            initialTarget={dialog.target}
            first={account && empty}
          />
        </Modal>
      )}
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
