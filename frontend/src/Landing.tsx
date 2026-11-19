// 로그인 전 첫 화면 (공개 시연 사이트도 이 화면): 제품이 무엇을 해 주는지 한 쪽에 차례로.
//   맨 위 메뉴 → 파란 첫머리(인사·로그인) → 세 단계 안내 → 예시 ① 내일 준비표 ② 어떤 주변 정보를 썼나 ③ 얼마나 맞나
//   → 자주 묻는 질문 → 써 보기(로그인 또는 문의) → 맨 아래 안내(자료 보관, 만든 사람)
// 예시 매장 = 서버가 demo로 표시한 매장 (가상 매장). 로그인하면 이 화면 대신 Workspace.tsx가 나온다.
import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { AnalysisView } from './AnalysisView'
import { api, type LoginConfig } from './api'
import { AccountBox, LoginButtons } from './Auth'
import { BacktestView, Decisions } from './BacktestView'
import { ForecastView } from './ForecastView'
import { count } from './format'
import { SourcesView } from './SourcesView'
import { periodName, verdict } from './verdict'

const FIRST_EXAMPLE = 'sinchon-a' // 보여 줄 예시 매장 (주변 정보와 주의 안내가 다 있는 가상 매장). 없으면 목록의 첫 매장
const REAL_EXAMPLE = 'fr-bakery' // 공개된 실제 판매 기록으로 돌린 결과 (예시 3 아래에 요약을 보여 준다)
const MENUS_SHOWN = 8 // 예시 준비표에 처음 보여 줄 메뉴 수
const HOW = [
  { title: '판매 기록 올리기', text: '포스에서 내려받은 엑셀·CSV 파일과 가게 위치만 알려 주세요. 1분이면 됩니다.' },
  { title: 'AI가 주변을 살펴요', text: '날씨, 학교 일정, 근처 행사와 소식, 메뉴 검색량을 지도 위에서 모으고, 예측에 도움이 되는지 지난 기록으로 확인합니다.' },
  { title: '내일 준비표 완성', text: '메뉴마다 몇 개 준비하면 좋을지와 그 이유를 알려 드려요.' },
]
const NAV = [
  { href: '#example', text: '예시 보기' },
  { href: '#accuracy', text: '얼마나 맞나' },
  { href: '#faq', text: '자주 묻는 질문' },
]
// 자주 묻는 질문. 지금 실제로 되는 것만 적는다 (아직 없는 것은 없다고 적는다)
const FAQ = [
  {
    q: '판매 기록은 얼마나 있어야 하나요?',
    a: '최소 3주(21일)치가 필요해요. 5주가 넘으면 마지막 1주를 따로 떼어 한 번 더 확인하고, 기록이 길수록 날씨·행사 같은 주변 정보의 효과를 더 잘 가려냅니다.',
  },
  {
    q: '어떤 파일을 올리면 되나요?',
    a: '포스나 매출 프로그램에서 내려받은 엑셀(.xlsx)·CSV 파일이면 됩니다. 날짜, 메뉴 이름, 수량 열만 있으면 읽어요. 토스 포스·OKPOS의 열 이름과 "상품별 매출" 엑셀(달마다 시트가 나뉜 것 포함)을 알아봅니다.',
  },
  {
    q: '결과는 어디서 보나요?',
    a: '지금은 이 웹 화면에서 봅니다. 판매 기록을 올리면 1~2분 뒤에 내일 준비표가 나와요. 포스 자동 연동과 카카오톡으로 매일 받아 보기는 아직 없고, 다음 단계로 계획하고 있습니다.',
  },
  {
    q: '주변 정보는 무조건 예측에 들어가나요?',
    a: '아니요. 가게마다 지난 기록으로 확인해서, 넣었을 때 예측이 실제로 더 정확해진 정보만 씁니다. 도움이 안 되면 쓰지 않고, 왜 안 썼는지도 보여 드려요.',
  },
  {
    q: '예측이 틀리면요?',
    a: '예측은 숫자 하나가 아니라 범위로 보여 드리고, 가게마다 지난 기록에서 얼마나 맞았는지를 그대로 공개합니다. 폐기를 줄일지 품절을 줄일지(준비 기준)는 사장님이 고릅니다.',
  },
  {
    q: '메뉴가 바뀌면요?',
    a: '최근 14일 동안 팔리지 않은 메뉴는 준비표에서 자동으로 빠지고, 새 메뉴는 판매 기록이 쌓이면 들어옵니다.',
  },
  {
    q: '카페·베이커리가 아니어도 되나요?',
    a: '메뉴별 하루 판매 기록이 있으면 돌아가지만, 지금까지 확인한 곳은 카페와 베이커리입니다.',
  },
  {
    q: '가격은 얼마인가요?',
    a: '아직 정하지 않았습니다. 지금은 시연 단계입니다.',
  },
]

// 예시 한 부분: 가운데 제목 · 한 줄 설명 · 흰 카드에 담은 실제 화면. id = 맨 위 메뉴가 찾아오는 자리
function Part({ n, id, title, lead, children }: { n: number; id?: string; title: string; lead: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24">
      <div className="mx-auto max-w-3xl text-center">
        <span className="inline-block rounded-full bg-accent px-3 py-1 text-xs font-bold text-white">예시 {n}</span>
        <h2 className="mt-3 text-3xl font-extrabold tracking-tight">{title}</h2>
        <p className="mt-3 text-muted">{lead}</p>
      </div>
      <div className="mt-8 rounded-3xl bg-sheet p-5 shadow-sm sm:p-8">{children}</div>
    </section>
  )
}

// 공개된 실제 판매 기록(프랑스 빵집)으로 같은 방법을 돌린 결과 한 줄 요약. 가상 예시만으로는 "실제로도 되나"에 답이 안 되므로
function RealData() {
  const v = verdict(useQuery({ queryKey: ['backtest', REAL_EXAMPLE], queryFn: () => api.backtest(REAL_EXAMPLE), retry: false }).data)
  if (!v) return null
  return (
    <div className="mt-6 rounded-3xl bg-accent-soft px-6 py-6 sm:px-8">
      <p className="text-sm font-bold text-accent">실제 판매 기록으로도 확인했어요</p>
      <p className="mt-2 max-w-3xl leading-relaxed">
        공개된 프랑스 빵집의 실제 판매 기록에 같은 방법을 썼을 때, {periodName(v)} 동안 하루에 남거나 모자란 개수가{' '}
        <b>
          {count(v.baseShown)}개 → {count(v.mineShown)}개
        </b>
        로 줄었습니다({v.gain}% 적음).
        {v.mine.days_won != null && ` ${v.days}일 중 ${v.mine.days_won}일은 '지난주 같은 요일만큼' 준비하는 것보다 덜 틀렸어요.`} 위치를 알 수 없는 가게라
        주변 정보 없이 판매 기록만 쓴 결과입니다.{' '}
        <a href={`?store=${REAL_EXAMPLE}#example`} className="font-semibold text-accent underline underline-offset-4">
          이 가게의 결과 보기
        </a>
      </p>
    </div>
  )
}

// login: 서버가 쓰는 로그인 방법(구글·카카오). 보기 전용 시연 사이트면 null (로그인 버튼 없음)
// contactUrl: '사전 신청·문의' 버튼이 여는 주소 (서버 설정). 없으면 버튼을 보여 주지 않는다
export function Landing({ login, contactUrl = null }: { login: LoginConfig | null; contactUrl?: string | null }) {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const examples = stores.data?.filter((s) => s.demo) ?? []
  // 화면에는 가상 매장 하나만 보여 준다. 주소에 ?store=fr-bakery 를 붙이면 다른 예시 매장(공개 실데이터)을 볼 수 있다
  const params = new URLSearchParams(window.location.search)
  const picked = params.get('store')
  const loginFailed = params.get('login_error') // 카카오 로그인이 실패·취소되면 서버가 ?login_error=kakao 로 돌려보낸다
  const store =
    examples.find((s) => s.store_id === picked) ?? examples.find((s) => s.store_id === FIRST_EXAMPLE) ?? examples[0]
  const virtual = !!store?.name.includes('가상') // 판매 기록도 주변 정보도 가상으로 만든 예시인가
  // 예시 매장을 분석했을 때의 과정 (녹화본). 있으면 '분석 과정 보기' 단추로 지도 장면을 재생한다. 주소로는 ?open=replay
  const past = useQuery({
    queryKey: ['progress', store?.store_id],
    queryFn: () => api.progress(store!.store_id),
    enabled: !!store,
    retry: false,
  }).data
  const [replaying, setReplaying] = useState(params.get('open') === 'replay')
  const contact = contactUrl && (
    <a href={contactUrl} target="_blank" rel="noreferrer" className="rounded-full bg-accent px-6 py-2.5 text-sm font-bold text-white shadow hover:bg-accent-deep">
      사전 신청·문의
    </a>
  )

  return (
    <div className="min-h-screen">
      {replaying && past && <AnalysisView events={past} status="done" replay onClose={() => setReplaying(false)} />}
      <header className="sticky top-0 z-30 bg-sheet/95 shadow-sm backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-8 gap-y-2 px-5 py-3.5">
          <h1 className="text-xl font-extrabold tracking-tight">내일몇개</h1>
          <nav className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm font-semibold text-muted">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} className="hover:text-ink">
                {n.text}
              </a>
            ))}
            {login ? <AccountBox login={login} /> : contact}
          </nav>
        </div>
      </header>

      <section className="bg-gradient-to-b from-accent to-accent-deep text-white">
        <div className="mx-auto max-w-6xl px-5 py-20 text-center sm:py-28">
          <p className="font-semibold text-white/80">카페·베이커리를 위한 내일 판매 예측</p>
          <h2 className="mt-3 text-5xl font-extrabold tracking-tight sm:text-6xl">내일 몇 개 만들까요?</h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-white/90">
            판매 기록에 날씨·학교 일정·근처 행사 같은 주변 정보를 더해, 내일 메뉴별로 얼마나 팔릴지와 몇 개 준비하면 좋을지 알려 드려요. 주변
            정보는 우리 가게에서 실제로 도움이 된 것만 씁니다.
          </p>
          {!!past?.length && (
            <div className="mt-8">
              <button onClick={() => setReplaying(true)} className="rounded-full bg-white px-7 py-3 text-base font-bold text-ink shadow-xl hover:bg-paper">
                AI가 분석하는 과정 보기
              </button>
              <p className="mt-2 text-sm text-white/75">예시 매장을 분석했을 때의 녹화본이에요.</p>
            </div>
          )}
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
            <div className="space-y-10">
              {virtual && (
                <p className="mx-auto max-w-3xl rounded-2xl bg-warn-soft px-5 py-4 text-center text-sm leading-relaxed text-warn">
                  아래 예시는 <b>가상으로 만든 매장</b>입니다. 판매 기록도 날씨·학사일정·행사도 가상이라, 숫자는 화면이 무엇을 보여 주는지의 예시이지
                  성능을 주장하는 것이 아닙니다.
                </p>
              )}
              <Part n={1} id="example" title="내일 메뉴별로 몇 개 준비할지"
                lead="메뉴마다 내일 예상 판매량과 예상 범위, 준비 권장량을 보여 주고, 날씨나 행사 때문에 평소와 달라진 이유를 함께 적어요. 메뉴를 누르면 최근 4주 그래프가 펼쳐집니다.">
                <ForecastView storeId={store.store_id} prepMode={store.prep_mode} readOnly limit={MENUS_SHOWN} />
              </Part>
            </div>

            <Part n={2} title="어떤 주변 정보를 썼나"
              lead="매장 주변을 살펴 날씨·학교 일정·행사 같은 정보를 모읍니다. 그중 지난 기록으로 확인해 예측을 실제로 더 정확하게 만든 정보만 써요.">
              <div className="space-y-10">
                <Decisions storeId={store.store_id}
                  noDataText={virtual ? '이 가상 예시에서는 모으지 않은 정보입니다. 실제 매장에서는 모아서 같은 방식으로 확인합니다.' : undefined} />
                <details>
                  <summary className="cursor-pointer text-sm font-semibold underline-offset-4 hover:underline">
                    AI가 어떤 정보원을 왜 골랐는지, 무엇을 모았는지 자세히 보기
                  </summary>
                  <div className="mt-8">
                    <SourcesView storeId={store.store_id} brief />
                  </div>
                </details>
              </div>
            </Part>

            <div>
              <Part n={3} id="accuracy" title="얼마나 맞나"
                lead="지난 기록에서 그날그날 전날까지의 자료만 보고 예측한 뒤 실제 판매와 비교한 결과예요. 가게마다 따로 확인해 그대로 보여 드립니다.">
                <BacktestView storeId={store.store_id} hideDecisions />
              </Part>
              {store.store_id !== REAL_EXAMPLE && <RealData />}
            </div>
          </>
        )}

        <section id="faq" className="scroll-mt-24">
          <h2 className="text-center text-3xl font-extrabold tracking-tight">자주 묻는 질문</h2>
          <div className="mx-auto mt-8 max-w-3xl divide-y divide-rule rounded-3xl bg-sheet px-6 shadow-sm sm:px-8">
            {FAQ.map((f) => (
              <details key={f.q} className="group py-5">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold">
                  {f.q}
                  <span className="text-faint transition-transform group-open:rotate-180" aria-hidden>
                    ▾
                  </span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-muted">{f.a}</p>
              </details>
            ))}
          </div>
        </section>
      </main>

      <section className="bg-ink text-white">
        <div className="mx-auto max-w-6xl px-5 py-20 text-center">
          <h2 className="text-3xl font-extrabold tracking-tight">내 가게로 해 보기</h2>
          {login ? (
            <>
              <p className="mx-auto mt-3 mb-7 max-w-xl text-white/75">
                로그인한 뒤 매장 이름, 위치, 닫는 시간을 적고 판매 기록 파일을 올리면 됩니다. 올린 자료와 결과는 본인만 볼 수 있어요.
              </p>
              <div className="flex justify-center">
                <LoginButtons login={login} />
              </div>
            </>
          ) : (
            <>
              <p className="mx-auto mt-3 max-w-xl text-white/75">
                지금 보시는 것은 시연용 화면이라 예시 매장의 결과만 보여 주고, 파일 올리기는 꺼져 있습니다.
                {contactUrl ? ' 내 가게 판매 기록으로 써 보고 싶다면 신청해 주세요.' : ''}
              </p>
              {contact && <div className="mt-7 flex justify-center">{contact}</div>}
            </>
          )}
        </div>
      </section>

      <footer className="bg-sheet">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-12 text-sm text-muted md:grid-cols-[1fr_1.6fr]">
          <div>
            <p className="text-base font-extrabold text-ink">내일몇개</p>
            <p className="mt-2 leading-relaxed">
              팀 PREDICTOR가 만든 시연 단계의 서비스입니다. 2026 연세 캠퍼스타운 AI 스타트업 해커톤 출품작입니다.
            </p>
            {contactUrl && (
              <a href={contactUrl} target="_blank" rel="noreferrer" className="mt-3 inline-block font-semibold text-accent underline underline-offset-4">
                사전 신청·문의
              </a>
            )}
          </div>
          <div>
            <p className="font-semibold text-ink">올린 자료를 어떻게 다루나요</p>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 leading-relaxed">
              <li>올린 판매 기록과 그 결과는 로그인한 본인만 볼 수 있습니다.</li>
              <li>'매장 관리'에서 매장을 지우면 판매 기록, 결과, 올린 파일이 서버에서 함께 지워집니다.</li>
              <li>
                주변 정보를 고르고 소식을 읽는 데 외부 AI 서비스(Anthropic의 Claude)를 씁니다. 이때 가게 이름·위치, 메뉴 이름, 내일 예측 숫자가
                전달됩니다.
              </li>
              <li>이 화면의 예시는 가상으로 만든 매장과 공개된 판매 기록으로 만든 것입니다.</li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  )
}
