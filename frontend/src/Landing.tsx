// 로그인 전 첫 화면 (공개 시연 사이트도 이 화면): 제품이 무엇을 해 주는지 한 쪽에 차례로.
//   맨 위 메뉴 → 흰 첫머리(인사·로그인) → 세 단계 안내 → 예시 ① 내일 준비표 ② 어떤 주변 정보를 썼나 ③ 얼마나 맞나
//   → 자주 묻는 질문 → 써 보기(로그인 또는 문의) → 맨 아래 안내(자료 보관, 만든 사람)
// 예시 매장 = 서버가 demo로 표시한 매장 (가상 매장). 로그인하면 이 화면 대신 Workspace.tsx가 나온다.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AnalysisMap } from './AnalysisMap'
import { AnalysisView } from './AnalysisView'
import { api, type LoginConfig, type ProgressEvent } from './api'
import { AccountBox, LoginButtons } from './Auth'
import { BacktestView, Decisions } from './BacktestView'
import { ForecastView } from './ForecastView'
import { Reveal } from './Reveal'
import { SourcesView } from './SourcesView'

const FIRST_EXAMPLE = 'sinchon-a' // 보여 줄 예시 매장 (주변 정보와 주의 안내가 다 있는 가상 매장). 없으면 목록의 첫 매장
const MENUS_SHOWN = 8 // 예시 준비표에 처음 보여 줄 메뉴 수
const HOW = [
  { title: '판매 기록 올리기', text: '포스에서 내려받은 파일과 가게 위치만 있으면 돼요.' },
  { title: 'AI가 주변을 살펴요', text: '날씨·학교 일정·근처 행사를 모아, 도움이 되는 것만 골라요.' },
  { title: '내일 준비표 완성', text: '메뉴마다 몇 개 준비할지와 그 이유를 알려 드려요.' },
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

// 첫머리의 배경: 예시 매장의 분석 기록으로 '지도에서 정보를 모으는 장면'을 되풀이해 보여 준다 (만질 수 없는 배경).
//   가게와 주변 시설·AI가 고른 곳을 차례로 찍은 뒤, 날씨·학교 일정·소식 같은 정보가 가장자리에서 가게로 계속 들어온다.
const HERO_FIRST: ProgressEvent['kind'][] = ['store', 'places', 'plan', 'event']
const HERO_LOOP: ProgressEvent['kind'][] = ['sales', 'weather', 'academic', 'special', 'trend_span', 'article']
function HeroMap({ events }: { events: ProgressEvent[] }) {
  const first = useMemo(() => HERO_FIRST.flatMap((k) => events.filter((e) => e.kind === k)), [events])
  const loop = useMemo(() => events.filter((e) => HERO_LOOP.includes(e.kind)), [events])
  const [n, setN] = useState(1) // 지금까지 지도에 넘긴 알림 수 (처음에 가게 하나)
  useEffect(() => {
    if (!loop.length && n >= first.length) return
    const timer = window.setTimeout(() => setN((v) => v + 1), n < first.length ? 900 : 1700)
    return () => window.clearTimeout(timer)
  }, [n, first.length, loop.length])
  const shown = useMemo(
    () => [...first.slice(0, n), ...Array.from({ length: Math.max(0, n - first.length) }, (_, i) => loop[i % loop.length])],
    [first, loop, n],
  )
  return <AnalysisMap events={shown} ambient />
}

// 예시 한 부분: 가운데 제목 · 한 줄 설명 · 흰 카드에 담은 실제 화면. id = 맨 위 메뉴가 찾아오는 자리
function Part({ n, id, title, lead, children }: { n: number; id?: string; title: string; lead: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24">
      <Reveal className="mx-auto max-w-3xl text-center">
        <span className="tag bg-surface text-ink-700">예시 {n}</span>
        <h2 className="mt-3 text-h1">{title}</h2>
        <p className="mt-3 text-body-lg text-ink-700">{lead}</p>
      </Reveal>
      <Reveal className="mt-10 rounded-3xl border border-line bg-white p-5 sm:p-8">{children}</Reveal>
    </section>
  )
}

// login: 서버가 쓰는 로그인 방법(구글·카카오). 보기 전용 시연 사이트면 null (로그인 버튼 없음)
// contactUrl: '사전 신청·문의' 버튼이 여는 주소 (서버 설정). 없으면 버튼을 보여 주지 않는다
export function Landing({ login, contactUrl = null }: { login: LoginConfig | null; contactUrl?: string | null }) {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const examples = stores.data?.filter((s) => s.demo) ?? []
  // 화면에는 가상 매장 하나만 보여 준다 (주소에 ?store=매장ID 를 붙이면 다른 예시 매장. 화면에서 그리로 가는 길은 두지 않는다)
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
  // 첫머리 배경 지도: 매장 위치가 있는 분석 기록이 있을 때만. 움직임을 줄이도록 설정한 사람에게는 보여 주지 않는다
  const calm = useMemo(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false, [])
  const heroMap = !calm && !replaying && past?.some((e) => e.kind === 'store' && e.lat)
  // 주요 버튼은 잉크 배경 + 흰 글자. 어두운 띠 위(onDark)에서는 흰 버튼
  const contact = (onDark = false) =>
    contactUrl && (
      <a href={contactUrl} target="_blank" rel="noreferrer" className={onDark ? 'btn-xl bg-white text-ink-900 hover:bg-surface' : 'btn-md btn-primary'}>
        사전 신청·문의
      </a>
    )

  return (
    <div className="min-h-screen">
      {replaying && past && <AnalysisView events={past} status="done" replay onClose={() => setReplaying(false)} />}
      <header className="sticky top-0 z-30 border-b border-line bg-white">
        <div className="mx-auto flex min-h-16 max-w-content flex-wrap items-center justify-between gap-x-8 gap-y-2 px-5 py-2 md:px-10">
          <h1 className="text-xl font-[800] tracking-[-0.05em]">내일몇개</h1>
          <nav className="flex flex-wrap items-center gap-x-6 gap-y-1 text-base text-ink-700">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} className="hover:text-ink-900">
                {n.text}
              </a>
            ))}
            {login ? <AccountBox login={login} /> : contact()}
          </nav>
        </div>
      </header>

      {/* 첫머리: 뒤에는 지도에서 정보를 모으는 장면(넓은 화면만), 앞에는 흰 판 위의 인사말. 가게 표시는 판 아래쪽에 보인다 */}
      <section className="relative overflow-hidden border-b border-line bg-white">
        {heroMap && (
          <div className="nm-fade absolute inset-0 isolate hidden md:block" aria-hidden>
            <HeroMap events={past!} />
            <div className="nm-hero-veil absolute inset-0 z-[900]" />
          </div>
        )}
        <div className={`pointer-events-none relative mx-auto max-w-content px-5 pt-16 text-center md:px-10 md:pt-24 ${heroMap ? 'pb-16 md:pb-60' : 'pb-16 md:pb-24'}`}>
          <div className="pointer-events-auto mx-auto max-w-4xl px-5 py-10 md:px-12 md:py-14">
          <p className="text-body-lg text-ink-700">카페·베이커리를 위한 내일 판매 예측</p>
          <h2 className="mt-3 text-hero">내일 몇 개 만들까요?</h2>
          <p className="mx-auto mt-6 max-w-2xl text-xl leading-8 text-ink-700">
            판매 기록에 날씨·학교 일정·근처 행사를 더해, 내일 메뉴별로 몇 개 준비하면 좋을지 알려 드려요.
          </p>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <a href="#example" className="btn-xl btn-primary">
              예시 보기
            </a>
            {!!past?.length && (
              <button onClick={() => setReplaying(true)} className="btn-xl btn-secondary">
                AI가 분석하는 과정 보기
              </button>
            )}
          </div>
          {loginFailed && (
            <p className="mx-auto mt-6 w-fit rounded-lg bg-down-soft px-4 py-2 text-sm font-medium text-down">
              로그인을 마치지 못했어요. 다시 시도해 주세요.
            </p>
          )}
          {login && (
            <div className="mt-8 flex flex-col items-center gap-3">
              <LoginButtons login={login} />
              <span className="text-sm text-ink-500">로그인하면 내 가게 판매 기록으로 준비표를 만들 수 있어요.</span>
            </div>
          )}
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-content space-y-32 px-5 py-24 md:px-10">
        <section>
          <Reveal className="text-center">
            <h2 className="text-h1">세 단계면 내일 준비표가 완성됩니다</h2>
          </Reveal>
          <ol className="mt-12 grid gap-5 md:grid-cols-3">
            {HOW.map((h, i) => (
              <li key={h.title}>
                <Reveal delay={i * 140} className="h-full rounded-2xl bg-surface px-6 py-12 text-center">
                  <span className="tag bg-white text-ink-700">STEP {i + 1}</span>
                  <h3 className="mt-4 text-2xl font-semibold tracking-tight">{h.title}</h3>
                  <p className="mt-3 text-base leading-relaxed text-ink-700">{h.text}</p>
                </Reveal>
              </li>
            ))}
          </ol>
        </section>

        {stores.error && <p className="rounded-2xl bg-white px-5 py-4 text-sm text-down">예시를 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}
        {stores.data && !store && <p className="text-center text-ink-700">보여 줄 예시 매장이 아직 없습니다.</p>}

        {store && (
          <>
            <div className="space-y-10">
              {virtual && (
                <p className="mx-auto w-fit rounded-md bg-surface px-3 py-1.5 text-sm font-medium text-ink-700">
                  아래는 가상으로 만든 예시 매장입니다
                </p>
              )}
              <Part n={1} id="example" title="내일 메뉴별로 몇 개 준비할지"
                lead="메뉴마다 준비할 개수와 평소와 달라진 이유를 보여 줘요. 메뉴를 누르면 그래프가 펼쳐집니다.">
                <ForecastView storeId={store.store_id} prepMode={store.prep_mode} readOnly limit={MENUS_SHOWN} />
              </Part>
            </div>

            <Part n={2} title="어떤 주변 정보를 썼나"
              lead="모은 정보 중에서 예측이 실제로 더 정확해진 것만 써요.">
              <div className="space-y-10">
                <Decisions storeId={store.store_id}
                  noDataText={virtual ? '이 예시에서는 모으지 않음' : undefined} />
                <details>
                  <summary className="cursor-pointer text-sm font-semibold underline-offset-4 hover:underline">
                    AI가 고른 정보원 자세히 보기
                  </summary>
                  <div className="mt-8">
                    <SourcesView storeId={store.store_id} brief />
                  </div>
                </details>
              </div>
            </Part>

            <Part n={3} id="accuracy" title="얼마나 맞나"
              lead="지난 날짜를 전날까지의 기록만 보고 맞혀 본 뒤, 실제 판매와 비교했어요.">
              <BacktestView storeId={store.store_id} hideDecisions />
            </Part>
          </>
        )}

        <section id="faq" className="scroll-mt-24">
          <Reveal>
            <h2 className="text-center text-h1">자주 묻는 질문</h2>
          </Reveal>
          <Reveal className="mx-auto mt-10 max-w-3xl divide-y divide-line rounded-2xl border border-line bg-white px-6 sm:px-8">
            {FAQ.map((f) => (
              <details key={f.q} className="group py-5">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold">
                  {f.q}
                  <span className="text-ink-500 transition-transform group-open:rotate-180" aria-hidden>
                    ▾
                  </span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-ink-700">{f.a}</p>
              </details>
            ))}
          </Reveal>
        </section>
      </main>

      <section className="bg-ink-900 text-white">
        <div className="mx-auto max-w-content px-5 py-24 text-center md:px-10">
          <h2 className="text-h1">내 가게로 해 보기</h2>
          {login ? (
            <>
              <p className="mx-auto mt-3 mb-7 max-w-xl text-white/75">
                로그인하고 판매 기록 파일을 올리면 됩니다. 올린 자료는 본인만 볼 수 있어요.
              </p>
              <div className="flex justify-center">
                <LoginButtons login={login} />
              </div>
            </>
          ) : (
            <>
              <p className="mx-auto mt-3 max-w-xl text-white/75">
                {contactUrl ? '내 가게 판매 기록으로 써 보고 싶다면 신청해 주세요.' : '지금은 예시 매장만 볼 수 있는 시연용 화면입니다.'}
              </p>
              {contactUrl && <div className="mt-7 flex justify-center">{contact(true)}</div>}
            </>
          )}
        </div>
      </section>

      <footer className="border-t border-line bg-white">
        <div className="mx-auto grid max-w-content gap-8 px-5 py-12 text-sm text-ink-700 md:grid-cols-[1fr_1.6fr] md:px-10">
          <div>
            <p className="text-base font-[800] tracking-[-0.05em] text-ink-900">내일몇개</p>
            <p className="mt-2 leading-relaxed">
              팀 PREDICTOR · 2026 연세 캠퍼스타운 AI 스타트업 해커톤 출품작
            </p>
            {contactUrl && (
              <a href={contactUrl} target="_blank" rel="noreferrer" className="mt-3 inline-block font-medium text-ink-900 underline underline-offset-4">
                사전 신청·문의
              </a>
            )}
          </div>
          <div>
            <p className="font-semibold text-ink-900">올린 자료를 어떻게 다루나요</p>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 leading-relaxed">
              <li>올린 판매 기록과 결과는 본인만 볼 수 있습니다.</li>
              <li>매장을 지우면 판매 기록, 결과, 올린 파일이 서버에서 함께 지워집니다.</li>
              <li>주변 정보를 읽는 데 외부 AI(Anthropic Claude)를 쓰며, 가게 이름·위치와 메뉴 이름, 예측 숫자가 전달됩니다.</li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  )
}
