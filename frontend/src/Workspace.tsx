// 일하는 화면: 내 매장의 분석(내일 준비표 · 얼마나 맞나 · 주변 정보)과 매장 추가·관리.
// 로그인을 쓰는 서버에서는 로그인한 뒤에 나오고, 예시(시연) 매장은 보이지 않는다 → 내 매장만.
// 로그인을 안 쓰는 서버(혼자 쓰는 노트북)에서는 처음부터 이 화면이고 모든 매장이 보인다.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from './api'
import { AccountBox } from './Auth'
import { BacktestView } from './BacktestView'
import { ForecastView } from './ForecastView'
import { SourcesView } from './SourcesView'
import { StoresView } from './StoresView'
import { UploadView } from './UploadView'

type Tab = 'forecast' | 'backtest' | 'sources' | 'upload' | 'stores'

// clientId: 구글 로그인을 쓰는 서버면 그 값(= 계정 방식), 아니면 null
export function Workspace({ clientId }: { clientId: string | null }) {
  const account = !!clientId
  const all = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const stores = all.data?.filter((s) => !account || !s.demo) // 계정 방식이면 예시 매장을 뺀다
  const tabs: { id: Tab; label: string }[] = [
    { id: 'forecast', label: '내일 준비표' },
    { id: 'backtest', label: '얼마나 맞나' },
    { id: 'sources', label: '주변 정보' },
    { id: 'upload', label: account ? '매장 추가' : '데이터 올리기' },
    ...(account ? [{ id: 'stores' as const, label: '내 매장' }] : []),
  ]
  // 주소로도 고를 수 있다: ?store=sinchon-a&tab=backtest
  const params = new URLSearchParams(window.location.search)
  const [picked, setStoreId] = useState<string | null>(params.get('store'))
  const [chosenTab, setTab] = useState<Tab>(tabs.some((t) => t.id === params.get('tab')) ? (params.get('tab') as Tab) : 'forecast')
  const [uploadTarget, setUploadTarget] = useState<string | null>(null) // '내 매장'에서 고른, 판매 기록을 다시 올릴 매장

  // 고른 매장이 목록에 없으면 첫 매장. 매장이 하나도 없으면 매장 추가부터
  const listed = !stores || stores.some((s) => s.store_id === picked)
  const storeId = (picked && listed ? picked : stores?.[0]?.store_id) ?? null
  const store = stores?.find((s) => s.store_id === storeId)
  const empty = !!stores && !stores.length
  const tab: Tab = empty && chosenTab !== 'stores' ? 'upload' : chosenTab

  const openUpload = (target: string | null) => {
    setUploadTarget(target)
    setTab('upload')
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-ink/80 bg-sheet">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-x-8 gap-y-3 px-5 pt-5">
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
            <h1 className="text-xl font-extrabold tracking-tight">내일몇개</h1>
            <nav className="flex gap-5" aria-label="화면">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => (t.id === 'upload' ? openUpload(null) : setTab(t.id))}
                  aria-current={tab === t.id ? 'page' : undefined}
                  className={`border-b-2 pb-3 text-[15px] ${
                    tab === t.id ? 'border-ink font-semibold' : 'border-transparent text-muted hover:text-ink'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
          </div>
          <div className="mb-2.5 flex flex-wrap items-center gap-x-6 gap-y-2">
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
            {clientId && <AccountBox clientId={clientId} />}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-10">
        {all.error && (
          <p className="mb-8 border-l-4 border-up bg-sheet px-4 py-3 text-sm">
            백엔드에 연결하지 못했습니다. 프로젝트 맨 위 폴더에서{' '}
            <code className="bg-paper px-1">.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000</code>을 실행하세요.
          </p>
        )}
        {tab === 'forecast' && storeId && (
          <ForecastView storeId={storeId} prepMode={store?.prep_mode ?? '균형'} readOnly={store?.can_edit === false} />
        )}
        {tab === 'backtest' && storeId && <BacktestView storeId={storeId} />}
        {tab === 'sources' && storeId && <SourcesView storeId={storeId} />}
        {tab === 'upload' && (
          <UploadView
            key={uploadTarget ?? 'new'}
            onDone={(id) => setStoreId(id)}
            account={account}
            initialTarget={uploadTarget}
            first={account && empty}
          />
        )}
        {tab === 'stores' && (
          <StoresView
            onOpen={(id) => {
              setStoreId(id)
              setTab('forecast')
            }}
            onUpload={openUpload}
          />
        )}
      </main>
    </div>
  )
}
