import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from './api'
import { AccountBox, GoogleButton } from './Auth'
import { BacktestView } from './BacktestView'
import { ForecastView } from './ForecastView'
import { SourcesView } from './SourcesView'
import { UploadView } from './UploadView'
import { useMe } from './useMe'

const TABS = [
  { id: 'forecast', label: '내일 준비표' },
  { id: 'backtest', label: '얼마나 맞나' },
  { id: 'sources', label: '주변 정보' },
  { id: 'upload', label: '데이터 올리기' },
] as const
type Tab = (typeof TABS)[number]['id']

export default function App() {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const config = useQuery({ queryKey: ['config'], queryFn: api.config }).data
  // 시연 모드(클라우드 공개용)면 보기 전용: '데이터 올리기' 탭을 숨긴다
  const demo = config?.demo_mode ?? false
  // 서버가 로그인을 쓰면(구글 클라이언트 ID가 있으면) 로그인 버튼을 보여 주고, 파일 올리기는 로그인한 사람만
  const clientId = config?.google_client_id ?? null
  const me = useMe(!!clientId).data ?? null
  const tabs = demo ? TABS.filter((t) => t.id !== 'upload') : TABS
  // 주소로도 고를 수 있다: ?store=sinchon-a&tab=backtest (시연 링크용)
  const params = new URLSearchParams(window.location.search)
  const [picked, setStoreId] = useState<string | null>(params.get('store'))
  const [chosenTab, setTab] = useState<Tab>(
    TABS.some((t) => t.id === params.get('tab')) ? (params.get('tab') as Tab) : 'forecast',
  )

  // 고른 매장이 목록에 없으면(없는 매장, 로그아웃해서 안 보이게 된 매장) 첫 매장. 매장이 하나도 없으면 '데이터 올리기' 탭
  const listed = !stores.data || stores.data.some((s) => s.store_id === picked)
  const storeId = (picked && listed ? picked : stores.data?.[0]?.store_id) ?? null
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
          <div className="mb-2.5 flex flex-wrap items-center gap-x-6 gap-y-2">
            {!!stores.data?.length && (
              <label className="flex items-center gap-2 text-sm text-muted">
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
            {clientId && <AccountBox clientId={clientId} />}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-10">
        {stores.error && (
          <p className="mb-8 border-l-4 border-up bg-sheet px-4 py-3 text-sm">
            백엔드에 연결하지 못했습니다. 프로젝트 맨 위 폴더에서{' '}
            <code className="bg-paper px-1">.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000</code>을 실행하세요.
          </p>
        )}
        {tab === 'forecast' && storeId && (
          <ForecastView storeId={storeId} prepMode={store?.prep_mode ?? '균형'} readOnly={demo || store?.can_edit === false} />
        )}
        {tab === 'backtest' && storeId && <BacktestView storeId={storeId} />}
        {tab === 'sources' && storeId && <SourcesView storeId={storeId} />}
        {tab === 'upload' &&
          (clientId && !me ? (
            <div className="max-w-xl">
              <p className="text-sm text-muted">데이터 올리기</p>
              <h2 className="mt-0.5 text-3xl font-bold tracking-tight">로그인하고 내 가게 준비표 만들기</h2>
              <p className="mt-2 mb-5 text-muted">
                올린 판매 기록과 결과는 로그인한 본인만 볼 수 있습니다. 구글 계정에서는 이름과 이메일만 받습니다.
              </p>
              <GoogleButton clientId={clientId} />
            </div>
          ) : (
            <UploadView onDone={(id) => setStoreId(id)} canDemo={!clientId || !!me?.is_admin} />
          ))}
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
