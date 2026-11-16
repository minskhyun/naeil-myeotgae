import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from './api'
import { BacktestView } from './BacktestView'
import { ForecastView } from './ForecastView'
import { UploadView } from './UploadView'

const TABS = [
  { id: 'forecast', label: '내일 예측' },
  { id: 'backtest', label: '얼마나 맞나' },
  { id: 'upload', label: '데이터 올리기' },
] as const
type Tab = (typeof TABS)[number]['id']

export default function App() {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  // 주소로도 고를 수 있다: ?store=sinchon-a&tab=backtest (시연 링크용)
  const params = new URLSearchParams(window.location.search)
  const [picked, setStoreId] = useState<string | null>(params.get('store'))
  const [chosenTab, setTab] = useState<Tab>(
    TABS.some((t) => t.id === params.get('tab')) ? (params.get('tab') as Tab) : 'forecast',
  )

  // 고른 매장이 없으면 첫 매장, 매장이 하나도 없으면 '데이터 올리기' 탭
  const storeId = picked ?? stores.data?.[0]?.store_id ?? null
  const tab: Tab = stores.data && !stores.data.length ? 'upload' : chosenTab
  const store = stores.data?.find((s) => s.store_id === storeId)

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4">
          <div>
            <h1 className="text-xl font-bold text-stone-900">
              내일몇개 <span className="font-normal text-stone-400">· 내일 몇 개 만들지</span>
            </h1>
          </div>
          {!!stores.data?.length && (
            <select
              value={storeId ?? ''}
              onChange={(e) => setStoreId(e.target.value)}
              className="rounded-xl border border-stone-300 bg-white px-3 py-2 text-sm"
            >
              {stores.data.map((s) => (
                <option key={s.store_id} value={s.store_id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 px-4">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`border-b-2 px-4 py-2.5 text-sm font-medium transition ${
                tab === t.id ? 'border-orange-500 text-orange-600' : 'border-transparent text-stone-500 hover:text-stone-800'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        {stores.error && (
          <p className="mb-6 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">
            백엔드에 연결하지 못했습니다. 프로젝트 맨 위 폴더에서 <code>uvicorn backend.app.main:app --port 8000</code>을 실행하세요.
          </p>
        )}
        {tab === 'forecast' && storeId && <ForecastView storeId={storeId} prepMode={store?.prep_mode ?? '균형'} />}
        {tab === 'backtest' && storeId && <BacktestView storeId={storeId} />}
        {tab === 'upload' && (
          <UploadView
            onDone={(id) => {
              setStoreId(id)
            }}
          />
        )}
        {tab !== 'upload' && !storeId && !stores.isLoading && (
          <p className="text-stone-500">아직 예측 결과가 없습니다. '데이터 올리기'에서 시작하세요.</p>
        )}
      </main>
    </div>
  )
}
