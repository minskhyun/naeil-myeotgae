import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from './api'
import { BacktestView } from './BacktestView'
import { ForecastView } from './ForecastView'
import { SourcesView } from './SourcesView'
import { UploadView } from './UploadView'

const TABS = [
  { id: 'forecast', label: '내일 준비표' },
  { id: 'backtest', label: '얼마나 맞나' },
  { id: 'sources', label: '주변 정보' },
  { id: 'upload', label: '데이터 올리기' },
] as const
type Tab = (typeof TABS)[number]['id']

export default function App() {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  // 시연 모드(클라우드 공개용)면 보기 전용: '데이터 올리기' 탭을 숨긴다
  const demo = useQuery({ queryKey: ['config'], queryFn: api.config }).data?.demo_mode ?? false
  const tabs = demo ? TABS.filter((t) => t.id !== 'upload') : TABS
  // 주소로도 고를 수 있다: ?store=sinchon-a&tab=backtest (시연 링크용)
  const params = new URLSearchParams(window.location.search)
  const [picked, setStoreId] = useState<string | null>(params.get('store'))
  const [chosenTab, setTab] = useState<Tab>(
    TABS.some((t) => t.id === params.get('tab')) ? (params.get('tab') as Tab) : 'forecast',
  )

  // 고른 매장이 없으면 첫 매장, 매장이 하나도 없으면 '데이터 올리기' 탭
  const storeId = picked ?? stores.data?.[0]?.store_id ?? null
  const tab: Tab = demo && chosenTab === 'upload' ? 'forecast' : stores.data && !stores.data.length ? 'upload' : chosenTab
  const store = stores.data?.find((s) => s.store_id === storeId)

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
                  onClick={() => setTab(t.id)}
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
          {!!stores.data?.length && (
            <label className="mb-2.5 flex items-center gap-2 text-sm text-muted">
              매장
              <select
                value={storeId ?? ''}
                onChange={(e) => setStoreId(e.target.value)}
                className="border border-rule bg-sheet px-2 py-1.5 text-ink focus:border-ink focus:outline-none"
              >
                {stores.data.map((s) => (
                  <option key={s.store_id} value={s.store_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-10">
        {stores.error && (
          <p className="mb-8 border-l-4 border-up bg-sheet px-4 py-3 text-sm">
            백엔드에 연결하지 못했습니다. 프로젝트 맨 위 폴더에서{' '}
            <code className="bg-paper px-1">.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000</code>을 실행하세요.
          </p>
        )}
        {tab === 'forecast' && storeId && <ForecastView storeId={storeId} prepMode={store?.prep_mode ?? '균형'} readOnly={demo} />}
        {tab === 'backtest' && storeId && <BacktestView storeId={storeId} />}
        {tab === 'sources' && storeId && <SourcesView storeId={storeId} />}
        {tab === 'upload' && <UploadView onDone={(id) => setStoreId(id)} />}
        {tab !== 'upload' && !storeId && !stores.isLoading && (
          <p className="text-muted">아직 준비표가 없습니다. '데이터 올리기'에서 시작하세요.</p>
        )}
        {demo && (
          <p className="mt-12 border-t border-rule pt-4 text-xs text-faint">
            시연용 화면입니다. 가상 매장과 공개 데이터(프랑스 빵집)로 미리 계산한 결과만 보여 주며, 파일 올리기와 설정 변경은 꺼져 있습니다.
          </p>
        )}
      </main>
    </div>
  )
}
