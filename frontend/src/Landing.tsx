// 로그인 전 첫 화면 (공개 시연 사이트도 이 화면): 예시 매장으로 제품이 무엇을 보여 주는지 한 쪽에 차례로.
//   ① 내일 준비표  ② 어떤 주변 정보를 썼나  ③ 얼마나 맞나
// 예시 매장 = 서버가 demo로 표시한 매장 (가상 매장, 공개 데이터). 로그인하면 이 화면 대신 Workspace.tsx가 나온다.
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, type LoginConfig } from './api'
import { AccountBox, LoginButtons } from './Auth'
import { BacktestView, Decisions } from './BacktestView'
import { ForecastView } from './ForecastView'
import { SourcesView } from './SourcesView'

const FIRST_EXAMPLE = 'sinchon-a' // 보여 줄 예시 매장 (주변 정보와 주의 안내가 다 있는 가상 매장). 없으면 목록의 첫 매장
const MENUS_SHOWN = 8 // 예시 준비표에 처음 보여 줄 메뉴 수
// 예시 한 부분: 번호 · 무엇을 보여 주는지 한 줄 · 실제 화면
function Part({ id, n, title, lead, children }: { id: string; n: number; title: string; lead: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-6 border-t border-ink/80 pt-8">
      <p className="text-sm font-semibold text-accent">예시 {n}</p>
      <h2 className="mt-1 text-2xl font-bold tracking-tight">{title}</h2>
      <p className="mt-2 max-w-3xl text-muted">{lead}</p>
      <div className="mt-8">{children}</div>
    </section>
  )
}

// login: 서버가 쓰는 로그인 방법(구글·카카오). 보기 전용 시연 사이트면 null (로그인 버튼 없음)
export function Landing({ login }: { login: LoginConfig | null }) {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const examples = stores.data?.filter((s) => s.demo) ?? []
  // 화면에는 가상 매장 하나만 보여 준다. 주소에 ?store=fr-bakery 를 붙이면 다른 예시 매장(공개 실데이터)을 볼 수 있다 (발표용)
  const params = new URLSearchParams(window.location.search)
  const picked = params.get('store')
  const loginFailed = params.get('login_error') // 카카오 로그인이 실패·취소되면 서버가 ?login_error=kakao 로 돌려보낸다
  const store =
    examples.find((s) => s.store_id === picked) ?? examples.find((s) => s.store_id === FIRST_EXAMPLE) ?? examples[0]

  return (
    <div className="min-h-screen">
      <header className="border-b border-ink/80 bg-sheet">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-8 gap-y-3 px-5 py-4">
          <h1 className="text-xl font-extrabold tracking-tight">내일몇개</h1>
          {login && <AccountBox login={login} />}
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-14 px-5 py-12">
        <section>
          <p className="text-sm text-muted">카페·베이커리를 위한 내일 판매 예측</p>
          <h2 className="mt-1 text-4xl font-extrabold tracking-tight sm:text-5xl">내일 몇 개 만들까요?</h2>
          <p className="mt-4 max-w-2xl text-lg leading-relaxed text-muted">
            포스 판매 기록에 날씨·주변 행사·메뉴 유행을 더해, 내일 메뉴별로 얼마나 팔릴지와 몇 개 준비하면 좋을지 알려 드립니다.
          </p>
          {loginFailed && (
            <p className="mt-5 max-w-2xl border-l-4 border-up bg-sheet px-4 py-3 text-sm">
              로그인을 마치지 못했습니다. 다시 시도해 주세요.
            </p>
          )}
          {login && (
            <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
              <LoginButtons login={login} />
              <span className="text-sm text-muted">로그인하면 내 가게 판매 기록으로 준비표를 만들 수 있습니다.</span>
            </div>
          )}
        </section>

        {stores.error && <p className="border-l-4 border-up bg-sheet px-4 py-3 text-sm">예시를 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}
        {stores.data && !store && <p className="text-muted">보여 줄 예시 매장이 아직 없습니다.</p>}

        {store && (
          <>
            <p className="text-sm text-muted">아래는 가상으로 만든 예시 매장의 화면입니다.</p>

            <Part id="forecast" n={1} title="내일 메뉴별로 몇 개 준비할지"
              lead="메뉴마다 내일 예상 판매량과 예상 범위, 준비 권장량을 보여 주고, 날씨나 행사 때문에 평소와 달라진 이유를 함께 적습니다.">
              <ForecastView storeId={store.store_id} prepMode={store.prep_mode} readOnly limit={MENUS_SHOWN} />
            </Part>

            <Part id="sources" n={2} title="어떤 주변 정보를 썼나"
              lead="매장 주변을 살펴 날씨·학교 일정·행사·메뉴 검색량을 모읍니다. 그중 과거 기록으로 확인해 예측을 실제로 더 정확하게 만든 정보만 씁니다.">
              <div className="space-y-10">
                <Decisions storeId={store.store_id} />
                <SourcesView storeId={store.store_id} brief />
              </div>
            </Part>

            <Part id="backtest" n={3} title="얼마나 맞나"
              lead="지난 기록에서 그날그날 전날까지의 자료만 보고 예측한 뒤 실제 판매와 비교한 결과입니다. 가게마다 따로 확인해 그대로 보여 줍니다.">
              <BacktestView storeId={store.store_id} hideDecisions />
            </Part>
          </>
        )}

        {login ? (
          <section className="border-t border-ink/80 pt-8">
            <h2 className="text-2xl font-bold tracking-tight">내 가게로 해 보기</h2>
            <p className="mt-2 mb-5 max-w-2xl text-muted">
              로그인한 뒤 매장 이름, 위치, 닫는 시간을 적고 포스에서 내려받은 판매 기록 파일을 올리면 됩니다. 올린 자료와 결과는 본인만 볼 수 있습니다.
            </p>
            <LoginButtons login={login} />
          </section>
        ) : (
          <p className="border-t border-rule pt-4 text-xs text-faint">
            시연용 화면입니다. 가상 매장으로 미리 계산한 결과만 보여 주며, 파일 올리기와 설정 변경은 꺼져 있습니다.
          </p>
        )}
      </main>
    </div>
  )
}
