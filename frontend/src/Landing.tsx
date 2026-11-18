// 로그인 전 첫 화면 (공개 시연 사이트도 이 화면): 제품이 무엇을 해 주는지 한 쪽에 차례로.
//   파란 첫머리(인사·로그인) → 세 단계 안내 → 예시 ① 내일 준비표 ② 어떤 주변 정보를 썼나 ③ 얼마나 맞나
// 예시 매장 = 서버가 demo로 표시한 매장 (가상 매장). 로그인하면 이 화면 대신 Workspace.tsx가 나온다.
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, type LoginConfig } from './api'
import { AccountBox, LoginButtons } from './Auth'
import { BacktestView, Decisions } from './BacktestView'
import { ForecastView } from './ForecastView'
import { SourcesView } from './SourcesView'

const FIRST_EXAMPLE = 'sinchon-a' // 보여 줄 예시 매장 (주변 정보와 주의 안내가 다 있는 가상 매장). 없으면 목록의 첫 매장
const MENUS_SHOWN = 8 // 예시 준비표에 처음 보여 줄 메뉴 수
const HOW = [
  { title: '판매 기록 올리기', text: '포스에서 내려받은 파일과 가게 위치만 알려 주세요.' },
  { title: 'AI가 주변을 살펴요', text: '날씨, 학교 일정, 근처 행사와 소식, 메뉴 검색량을 지도 위에서 모읍니다.' },
  { title: '내일 준비표 완성', text: '메뉴마다 몇 개 준비하면 좋을지와 그 이유를 알려 드려요.' },
]

// 예시 한 부분: 가운데 제목 · 한 줄 설명 · 흰 카드에 담은 실제 화면
function Part({ n, title, lead, children }: { n: number; title: string; lead: string; children: ReactNode }) {
  return (
    <section>
      <div className="mx-auto max-w-3xl text-center">
        <span className="inline-block rounded-full bg-accent px-3 py-1 text-xs font-bold text-white">예시 {n}</span>
        <h2 className="mt-3 text-3xl font-extrabold tracking-tight">{title}</h2>
        <p className="mt-3 text-muted">{lead}</p>
      </div>
      <div className="mt-8 rounded-3xl bg-sheet p-5 shadow-sm sm:p-8">{children}</div>
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
      <header className="bg-sheet">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-8 gap-y-3 px-5 py-4">
          <h1 className="text-xl font-extrabold tracking-tight">내일몇개</h1>
          {login && <AccountBox login={login} />}
        </div>
      </header>

      <section className="bg-gradient-to-b from-accent to-accent-deep text-white">
        <div className="mx-auto max-w-6xl px-5 py-20 text-center sm:py-28">
          <p className="font-semibold text-white/80">카페·베이커리를 위한 내일 판매 예측</p>
          <h2 className="mt-3 text-5xl font-extrabold tracking-tight sm:text-6xl">내일 몇 개 만들까요?</h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-white/90">
            판매 기록에 날씨·주변 행사·메뉴 유행을 더해, 내일 메뉴별로 얼마나 팔릴지와 몇 개 준비하면 좋을지 알려 드려요.
          </p>
          {loginFailed && (
            <p className="mx-auto mt-6 max-w-md rounded-full bg-white/15 px-5 py-2 text-sm font-semibold">
              로그인을 마치지 못했어요. 다시 시도해 주세요.
            </p>
          )}
          {login && (
            <div className="mt-8 flex flex-col items-center gap-3">
              <LoginButtons login={login} />
              <span className="text-sm text-white/80">로그인하면 내 가게 판매 기록으로 준비표를 만들 수 있어요.</span>
            </div>
          )}
        </div>
      </section>

      <main className="mx-auto max-w-6xl space-y-24 px-5 py-20">
        <section>
          <div className="text-center">
            <h2 className="text-3xl font-extrabold tracking-tight">세 단계면 내일 준비표 완성!</h2>
            <p className="mt-3 text-muted">어려운 설정은 없어요. 주변 정보는 저희가 찾습니다.</p>
          </div>
          <ol className="mt-10 grid gap-5 md:grid-cols-3">
            {HOW.map((h, i) => (
              <li key={h.title} className="rounded-3xl bg-sheet px-6 py-10 text-center shadow-sm">
                <span className="inline-block rounded-full bg-accent px-3 py-1 text-xs font-bold text-white">STEP {i + 1}</span>
                <h3 className="mt-4 text-xl font-bold">{h.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{h.text}</p>
              </li>
            ))}
          </ol>
        </section>

        {stores.error && <p className="rounded-2xl bg-sheet px-5 py-4 text-sm text-up">예시를 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}
        {stores.data && !store && <p className="text-center text-muted">보여 줄 예시 매장이 아직 없습니다.</p>}

        {store && (
          <>
            <Part n={1} title="내일 메뉴별로 몇 개 준비할지"
              lead="메뉴마다 내일 예상 판매량과 예상 범위, 준비 권장량을 보여 주고, 날씨나 행사 때문에 평소와 달라진 이유를 함께 적어요. 아래는 가상으로 만든 예시 매장입니다.">
              <ForecastView storeId={store.store_id} prepMode={store.prep_mode} readOnly limit={MENUS_SHOWN} />
            </Part>

            <Part n={2} title="어떤 주변 정보를 썼나"
              lead="매장 주변을 살펴 날씨·학교 일정·행사·메뉴 검색량을 모읍니다. 그중 지난 기록으로 확인해 예측을 실제로 더 정확하게 만든 정보만 써요.">
              <div className="space-y-10">
                <Decisions storeId={store.store_id} />
                <SourcesView storeId={store.store_id} brief />
              </div>
            </Part>

            <Part n={3} title="얼마나 맞나"
              lead="지난 기록에서 그날그날 전날까지의 자료만 보고 예측한 뒤 실제 판매와 비교한 결과예요. 가게마다 따로 확인해 그대로 보여 드립니다.">
              <BacktestView storeId={store.store_id} hideDecisions />
            </Part>
          </>
        )}
      </main>

      {login ? (
        <section className="bg-ink text-white">
          <div className="mx-auto max-w-6xl px-5 py-20 text-center">
            <h2 className="text-3xl font-extrabold tracking-tight">내 가게로 해 보기</h2>
            <p className="mx-auto mt-3 mb-7 max-w-xl text-white/75">
              로그인한 뒤 매장 이름, 위치, 닫는 시간을 적고 판매 기록 파일을 올리면 됩니다. 올린 자료와 결과는 본인만 볼 수 있어요.
            </p>
            <div className="flex justify-center">
              <LoginButtons login={login} />
            </div>
          </div>
        </section>
      ) : (
        <p className="mx-auto max-w-6xl px-5 pb-10 text-xs text-faint">
          시연용 화면입니다. 가상 매장으로 미리 계산한 결과만 보여 주며, 파일 올리기와 설정 변경은 꺼져 있습니다.
        </p>
      )}
    </div>
  )
}
