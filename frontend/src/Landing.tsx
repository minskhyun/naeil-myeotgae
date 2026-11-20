// 첫 화면 ('/'): 제품이 무엇을 해 주는지를 큰 문장과 실제 화면 조각으로 차례로 보여 준다.
//   첫머리(왼쪽에 한 문장, 오른쪽 바탕에 지도 장면) → 01 주변 소식을 모으고 → 02 메뉴마다 알려 주고(작은 기능 넷) → 03 남길 일·모자랄 일을 줄이고
//   → 숫자로 본 결과 → 더 알아보기(소개로) → 내 가게로 해 보기
// 한 화면에 한 내용: 구역(Screen) 하나가 화면 하나를 채우고, 스크롤은 구역마다 멈춘다 (index.css의 nm-screen · nm-snap).
// 어떻게 예측하는지, 어떻게 검증했는지는 여기서 길게 설명하지 않는다: 소개(About.tsx)에 있다. 여기서는 숫자 몇 개만.
// 화면 조각은 그림이 아니라 예시 매장의 실제 결과로 그린다 (준비표·주의할 소식 등 분석 화면과 같은 부품).
// 모양: 옅은 회색 바탕 위의 흰 칸, 왼쪽에 붙인 큰 제목, 화살표가 달린 알약 버튼. (제목 위의 작은 영어 이름표는 쓰지 않는다)
// 움직임: 구역이 화면에 들어오면 제목이 줄마다 흐릿했다가 또렷해지며 떠오르고(Lines), 칸들이 차례로 떠오르고(Reveal),
//   첫머리의 지도는 천천히 나타나고, 숫자는 0에서 올라간다.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { AnalysisMap } from './AnalysisMap'
import { ABOUT_PATH, api, APP_PATH, PREP_MODES, SUPPORT_PATH, type ProgressEvent } from './api'
import { LoginButton } from './Auth'
import { useExample } from './example'
import { ForecastTable, Notice, PrepToggle } from './ForecastView'
import { cleanTitle, count, dayPrefix, fmtDate, pct1, shortReason } from './format'
import { CountWhenSeen, Lines, Reveal } from './Reveal'
import { ArrowLink, JoinBand, SiteFooter, SiteHeader, type SiteProps } from './Site'
import { useSnapScroll } from './scrub'
import { periodName, verdict } from './verdict'

// 첫머리의 지도: 예시 매장의 분석 기록으로 '지도에서 정보를 모으는 장면'을 되풀이해 보여 준다 (만질 수 없다).
//   가게와 주변 시설·AI가 고른 곳을 차례로 찍은 뒤, 날씨·학교 일정·소식 같은 정보가 가장자리에서 가게로 계속 들어온다.
const MAP_FIRST: ProgressEvent['kind'][] = ['store', 'places', 'plan', 'event']
const MAP_LOOP: ProgressEvent['kind'][] = ['sales', 'weather', 'academic', 'special', 'trend_span', 'article']
function CollectMap({ events }: { events: ProgressEvent[] }) {
  const first = useMemo(() => MAP_FIRST.flatMap((k) => events.filter((e) => e.kind === k)), [events])
  const loop = useMemo(() => events.filter((e) => MAP_LOOP.includes(e.kind)), [events])
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
  return <AnalysisMap events={shown} ambient storeX={0.6} storeY={0.52} />
}

// 화면 하나를 채우는 구역 (스크롤이 여기서 멈춘다). id = 다른 곳에서 찾아오는 자리
function Screen({ id, className = '', children }: { id?: string; className?: string; children: ReactNode }) {
  return (
    <section id={id} className={`nm-screen mx-auto w-full max-w-content px-5 md:px-10 ${className}`}>
      {children}
    </section>
  )
}

// 큰 구역의 머리: 왼쪽에 큰 제목 · 설명, 오른쪽에 세로선으로 나눈 짧은 항목들
function Chapter({ title, lead, points }: { title: string; lead?: string; points?: { name: string; text: string }[] }) {
  return (
    <div className="grid items-end gap-10 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
      <div>
        <Lines text={title} className="text-title" />
        {lead && (
          <Reveal as="p" lag={0.2} className="mt-6 max-w-xl text-xl leading-8 text-ink-700">
            {lead}
          </Reveal>
        )}
      </div>
      {points && (
        <ul className="grid grid-cols-3">
          {points.map((p, i) => (
            <Reveal as="li" key={p.name} lag={0.15 + i * 0.12} className="border-l border-line px-5 py-1">
              <p className="font-semibold">{p.name}</p>
              <p className="mt-1.5 leading-relaxed text-ink-500">{p.text}</p>
            </Reveal>
          ))}
        </ul>
      )}
    </div>
  )
}

// 작은 기능 하나: 한쪽에는 짧은 글, 다른 쪽에는 흰 판 위의 실제 화면 조각. flip = 글과 화면의 자리를 바꾼다, wide = 화면 쪽을 더 넓게
function Feature({ title, text, flip = false, wide = false, children }: { title: string; text: string; flip?: boolean; wide?: boolean; children: ReactNode }) {
  const cols = wide ? 'md:grid-cols-[0.6fr_1.4fr]' : flip ? 'md:grid-cols-[1.2fr_0.8fr]' : 'md:grid-cols-[0.8fr_1.2fr]'
  return (
    <div className={`grid items-center gap-8 md:gap-16 ${cols}`}>
      <div className={flip ? 'md:order-2' : ''}>
        <Lines as="h3" text={title} className="text-h1" />
        <Reveal as="p" lag={0.2} className="mt-5 text-xl leading-8 text-ink-700">
          {text}
        </Reveal>
      </div>
      <Reveal lag={0.1} className="min-w-0 rounded-[32px] bg-white p-4 sm:p-8">
        {children}
      </Reveal>
    </div>
  )
}

// 큰 숫자 한 칸 (화면에 들어오면 0에서 올라간다)
function Stat({ children, label, lag = 0 }: { children: ReactNode; label: string; lag?: number }) {
  return (
    <Reveal lag={lag} className="rounded-[32px] bg-white px-8 py-12">
      <p className="whitespace-nowrap text-display tabular-nums">{children}</p>
      <p className="mt-4 text-lg text-ink-700">{label}</p>
    </Reveal>
  )
}

export function Landing({ login, contactUrl, canEnter }: SiteProps) {
  useSnapScroll()
  const { stores, store, past } = useExample()
  const id = store?.store_id
  const forecast = useQuery({ queryKey: ['forecast', id], queryFn: () => api.forecast(id!), enabled: !!id }).data
  const backtest = useQuery({ queryKey: ['backtest', id], queryFn: () => api.backtest(id!), enabled: !!id }).data
  const [mode, setMode] = useState<string>(PREP_MODES[1]) // '준비 기준' 조각에서 눌러 본 기준 (처음에는 균형)
  const loginFailed = new URLSearchParams(window.location.search).get('login_error') // 카카오 로그인이 실패·취소되면 서버가 붙여 보낸다
  const calm = useMemo(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false, [])
  const hasMap = !calm && !!past?.some((e) => e.kind === 'store' && e.lat)

  const v = verdict(backtest)
  const rows = forecast?.rows ?? []
  const date = rows[0]?.date
  // 평소와 가장 많이 달라진 메뉴 몇 개 (이유가 붙은 것)
  const moved = rows
    .filter((r) => r.reasons.length)
    .sort((a, b) => Math.abs(b.reasons[0].effect_pct) - Math.abs(a.reasons[0].effect_pct))
    .slice(0, 5)
  const total = (m: string) => rows.reduce((sum, r) => sum + (r.prep_by_mode?.[m] ?? r.prep_qty ?? 0), 0)
  // 01의 화면 조각에 적을 '모은 정보' (예시 매장의 분석 기록에서)
  const got = <K extends ProgressEvent['kind']>(kind: K) => (past ?? []).filter((e) => e.kind === kind) as Extract<ProgressEvent, { kind: K }>[]
  const school = got('academic')[0]
  const terms = school ? (school.exams ?? 0) + (school.vacations ?? 0) + (school.festivals ?? 0) : 0
  const gathered = [
    { label: '날씨', value: got('weather')[0] ? `${count(got('weather')[0].days)}일` : null },
    { label: '주변 시설', value: got('places')[0] ? `${count(got('places')[0].count)}곳` : null },
    { label: '시험·방학·축제', value: terms ? `${terms}번` : school ? `${count(school.days)}일` : null },
    { label: '근처 행사', value: got('event').length ? `${got('event').length}건` : null },
    { label: '읽은 글', value: got('article').length ? `${got('article').length}건` : null },
    { label: '검색량을 본 메뉴', value: got('trend_span')[0] ? `${got('trend_span')[0].menus}개` : null },
    { label: '기념일', value: got('special').length ? `${got('special').length}개` : null },
  ].filter((g) => g.value)
  // AI가 '우리 가게와 얼마나 관련 있나'를 따진 행사 몇 개 (관련이 큰 것부터)
  const rated = [...got('rating')]
    .sort((x, y) => y.relevance * y.scale - x.relevance * x.scale)
    .filter((r, i, all) => all.findIndex((x) => x.title === r.title) === i) // 같은 행사가 두 번 모였으면 한 번만
    .slice(0, 4)

  return (
    <div>
      <SiteHeader login={login} canEnter={canEnter} contactUrl={contactUrl} here="home" />

      {/* 1. 첫머리: 왼쪽에 한 문장과 버튼 (화면을 열면 줄마다 떠오른다), 오른쪽 바탕에는 가게 주변의 정보를 모으는 지도 장면.
             지도는 칸으로 나누지 않는다: 가장자리가 바탕색으로 풀려 글 옆에 스며들고, 넓은 화면에서는 머리말 밑까지 올라간다.
             좁은 화면에서는 글 아래에 놓인다. */}
      <section className="nm-screen relative">
        {hasMap && (
          <div className="nm-hero-map relative isolate order-last mt-12 h-[340px] lg:absolute lg:-top-16 lg:right-0 lg:bottom-0 lg:mt-0 lg:h-auto lg:w-[58%]">
            <CollectMap events={past!} />
            <div className="nm-hero-veil pointer-events-none absolute inset-0 z-[900]" />
            <p className="absolute right-32 bottom-6 z-[900] rounded-full bg-white px-4 py-2 text-sm font-medium text-ink-700">
              가게 주변의 정보를 모으는 모습 (예시 매장)
            </p>
          </div>
        )}
        <div className="relative z-10 mx-auto w-full max-w-content px-5 md:px-10">
          <div className="lg:max-w-[620px]">
            <h1 className="nm-enter text-hero">
              <span style={{ '--i': 0 } as CSSProperties}>내일 몇 개 만들지,</span>
              <span style={{ '--i': 1 } as CSSProperties}>감 대신 기록으로</span>
            </h1>
            <div className="nm-enter">
              <p className="mt-7 max-w-xl text-xl leading-8 text-ink-700" style={{ '--i': 3 } as CSSProperties}>
                판매 기록만 올리면 날씨와 가게 주변 소식까지 살펴, 내일 메뉴별로 몇 개 준비하면 좋을지 알려 드려요.
              </p>
              <div className="mt-10 flex flex-wrap items-center gap-3" style={{ '--i': 4 } as CSSProperties}>
                {canEnter ? (
                  <ArrowLink href={APP_PATH} dark>
                    분석하러 가기
                  </ArrowLink>
                ) : (
                  <ArrowLink href="#features" dark>
                    어떤 서비스인가요
                  </ArrowLink>
                )}
                <ArrowLink href={ABOUT_PATH}>어떻게 예측하나요</ArrowLink>
              </div>
            </div>
            {loginFailed && (
              <p className="mt-6 w-fit rounded-lg bg-down-soft px-4 py-2 text-sm font-medium text-down">로그인을 마치지 못했어요. 다시 시도해 주세요.</p>
            )}
            {login && !canEnter && (
              <div className="mt-8 flex flex-col items-start gap-3">
                <LoginButton login={login} label="로그인하고 시작하기" />
                <span className="text-sm text-ink-500">로그인하면 내 가게 판매 기록으로 준비표를 만들 수 있어요.</span>
              </div>
            )}
            {stores.error && <p className="mt-8 text-sm text-down">예시를 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}
          </div>
        </div>
      </section>

      {/* 2. 01 모으기 */}
      <Screen id="features">
        <Chapter
          title={'가게 주변 소식을\n한곳에 모아서 보여 주고'}
          lead="가게 위치만 알려 주시면 AI가 주변을 찾아서 읽어요."
          points={[
            { name: '날씨', text: '기온과 비, 내일 예보까지' },
            { name: '학교 일정', text: '근처 대학의 시험·방학·축제' },
            { name: '행사와 소식', text: '주변 행사, 뉴스와 블로그 글' },
          ]}
        />
        {!!gathered.length && (
          <Reveal lag={0.25} className="mt-10 rounded-[32px] bg-white p-5 sm:p-7">
            {/* 칸은 있는 만큼만 그리고, 폭을 나눠 가득 채운다 (모은 정보가 적은 매장에서도 비어 보이지 않게) */}
            <ul className="flex flex-wrap gap-3">
              {gathered.map((g) => (
                <li key={g.label} className="flex-1 basis-28 rounded-2xl bg-page px-3 py-5 text-center">
                  <p className="text-h2 tabular-nums">{g.value}</p>
                  <p className="mt-1.5 text-sm text-ink-700">{g.label}</p>
                </li>
              ))}
            </ul>
            {(!!got('article').length || !!rated.length) && (
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {!!got('article').length && (
                  <div className="min-w-0 rounded-2xl bg-page px-6 py-4">
                    <p className="text-label text-ink-500">읽은 글</p>
                    <ul className="mt-1 divide-y divide-line">
                      {got('article')
                        .slice(0, 3)
                        .map((a) => (
                          <li key={a.url} className="flex items-center justify-between gap-4 py-3">
                            <span className="min-w-0 truncate">{cleanTitle(a.title)}</span>
                            <a href={a.url} target="_blank" rel="noreferrer" className="shrink-0 text-sm text-ink-500 underline underline-offset-4 hover:text-ink-900">
                              원문
                            </a>
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
                {!!rated.length && (
                  <div className="min-w-0 rounded-2xl bg-page px-6 py-4">
                    <p className="text-label text-ink-500">AI가 따져 본 근처 행사</p>
                    <ul className="mt-1 divide-y divide-line">
                      {rated.slice(0, 3).map((r) => (
                        <li key={r.title} className="flex items-center justify-between gap-4 py-3" title={r.reason}>
                          <span className="min-w-0 truncate">{r.title}</span>
                          <span className="shrink-0 text-sm text-ink-500 tabular-nums">
                            연관도 {r.relevance}/5 · {count(r.distance_m)}m
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            <p className="mt-4 text-center text-sm text-ink-500">예시 매장(신촌, 판매 기록은 가상)을 분석할 때 실제로 모은 것입니다.</p>
          </Reveal>
        )}
      </Screen>

      {/* 4. 02 예측하기: 큰 문장 한 화면, 그다음 작은 기능 넷이 한 화면씩 */}
      <Screen>
        <Chapter
          title={'얼마나 팔릴지, 몇 개 준비할지\n메뉴마다 알려 줘요'}
          lead="숫자 하나가 아니라, 얼마나 팔릴지의 범위와 준비할 개수를 함께 보여 드려요."
          points={[
            { name: '예상 판매량', text: '메뉴마다 몇 개 팔릴지' },
            { name: '예상 범위', text: '열 번 중 여덟 번이 드는 폭' },
            { name: '준비 개수', text: '고른 기준에 맞춘 개수' },
          ]}
        />
      </Screen>
      {!!rows.length && id && (
        <>
          <Screen>
            <Feature wide title={"한 장으로 끝나는\n'준비표'"} text="메뉴마다 준비할 개수와 예상 범위를 한 장에 담았어요. 최근 4주의 판매와 나란히 볼 수 있어요.">
              <ForecastTable rows={rows} limit={4} compact storeId={id} />
            </Feature>
          </Screen>

          {!!moved.length && (
            <Screen>
              <Feature flip title={"평소와 왜 다른지 알려 주는\n'평소 대비'"} text="추운 날에는 따뜻한 음료가 늘고 아이스는 줄어요. 숫자가 달라진 이유를 메뉴마다 적어 드려요.">
                <ul className="divide-y divide-line px-2">
                  {moved.map((r) => (
                    <li key={r.menu} className="flex items-center justify-between gap-4 py-5">
                      <span className="min-w-0 truncate text-lg font-medium">{r.menu}</span>
                      <span className="flex shrink-0 items-center gap-3">
                        {r.reasons.slice(0, 2).map((x) => (
                          <span key={x.signal} className={`tag ${x.effect_pct < 0 ? 'bg-down-soft text-down' : 'bg-up-soft text-up'}`}>
                            {shortReason(x)}
                          </span>
                        ))}
                        <b className="w-14 text-right text-h3 tabular-nums">{count(r.pred)}개</b>
                      </span>
                    </li>
                  ))}
                </ul>
              </Feature>
            </Screen>
          )}

          <Screen>
            <Feature title={"남길지 모자랄지 고르는\n'준비 기준'"} text="폐기를 줄일지 품절을 줄일지는 사장님이 정해요. 고르는 대로 준비 개수가 바뀝니다. 눌러 보세요.">
              <div className="px-2 py-4">
                <PrepToggle storeId={id} prepMode={mode} readOnly onPick={setMode} />
                <p className="mt-8 text-center text-ink-700">{date ? `${dayPrefix(date)}준비할 개수` : '준비할 개수'}</p>
                <p className="mt-1 text-center text-display tabular-nums">
                  {count(total(mode))}
                  <span className="ml-1 text-[28px] font-normal tracking-normal text-ink-500">개</span>
                </p>
              </div>
            </Feature>
          </Screen>

          {!!forecast?.warnings.length && (
            <Screen>
              <Feature flip title={"놓치기 쉬운 일을 챙겨 주는\n'주의할 소식'"} text="숫자에 담지 못한 일은 AI가 글로 알려 드려요. 근거가 된 원문도 함께 붙여요.">
                <div className="space-y-3">
                  {forecast.warnings.slice(0, 2).map((w, i) => (
                    <Notice key={i} w={w} />
                  ))}
                </div>
              </Feature>
            </Screen>
          )}
        </>
      )}

      {/* 5. 03 준비하기 */}
      <Screen>
        <Chapter title={'남길 일은 줄이고\n모자랄 일은 막아 드려요'} />
        <div className="mt-12 grid gap-5 md:grid-cols-2">
          <Reveal lag={0.2} className="rounded-[32px] bg-white px-8 py-12">
            <span className="tag bg-down-soft text-down">폐기</span>
            <h3 className="mt-5 text-h1">덜 팔릴 날은 미리 줄이고</h3>
            <p className="mt-4 text-xl leading-8 text-ink-700">비가 오거나 방학이 시작되면 평소만큼 팔리지 않아요. 그런 날을 먼저 알려 드려요.</p>
          </Reveal>
          <Reveal lag={0.35} className="rounded-[32px] bg-white px-8 py-12">
            <span className="tag bg-up-soft text-up">품절</span>
            <h3 className="mt-5 text-h1">더 팔릴 날은 넉넉하게</h3>
            <p className="mt-4 text-xl leading-8 text-ink-700">근처에 행사가 있거나 날이 추워 따뜻한 음료가 늘 때, 모자라지 않게 준비할 수 있어요.</p>
          </Reveal>
        </div>
      </Screen>

      {/* 6. 숫자 몇 개 (검증은 여기서 길게 말하지 않는다 → 소개) */}
      {v && (
        <Screen>
          <Chapter title={'지난주 그대로 준비할 때보다\n정확도가 올라가요'} />
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            <Stat lag={0.2} label="정확도 향상 (남거나 모자라는 개수가 줄어든 비율)">
              <span className="text-point">
                <CountWhenSeen to={Math.max(v.gain, 0)} />%
              </span>
            </Stat>
            <Stat lag={0.3} label="하루에 남거나 모자라는 개수 (모든 메뉴 합)">
              {count(v.baseShown)} → <CountWhenSeen to={v.mineShown} />
            </Stat>
            <Stat lag={0.4} label="실제 판매가 예상 범위 안에 든 비율">
              <CountWhenSeen to={v.mine.coverage_80} format={pct1} />
            </Stat>
          </div>
          <Reveal lag={0.5} className="mt-10 flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-2xl text-sm leading-relaxed text-ink-500">
              예시 매장(판매 기록은 가상)의 {periodName(v)} 기준{date ? ` · ${fmtDate(date)} 예측까지` : ''}. 지난 날짜를 전날까지의 기록만 보고 맞혀 본 결과입니다.
            </p>
            <ArrowLink href={`${ABOUT_PATH}#example`}>평가 방법 보기</ArrowLink>
          </Reveal>
        </Screen>
      )}

      {/* 7. 더 알아보기 */}
      <Screen>
        <Lines text="더 알아보기" className="text-title" />
        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {[
            { href: `${ABOUT_PATH}#how`, title: '판매 기록이 준비표가 되기까지' },
            { href: `${ABOUT_PATH}#example`, title: '예시 매장의 준비표와 검증 결과' },
            { href: `${SUPPORT_PATH}#faq`, title: '어떤 파일을 올리면 되나요' },
          ].map((c, i) => (
            <Reveal key={c.href} lag={0.15 + i * 0.12}>
              <a href={c.href} className="group block h-full rounded-[32px] bg-white px-8 py-10">
                <p className="text-h2">{c.title}</p>
                <span className="mt-8 flex h-10 w-10 items-center justify-center rounded-full bg-ink-900 text-white transition-transform duration-200 group-hover:translate-x-1.5" aria-hidden>
                  →
                </span>
              </a>
            </Reveal>
          ))}
        </div>
      </Screen>

      {/* 8. 마무리: 내 가게로 해 보기 + 바닥글 */}
      <section className="nm-screen !justify-start !py-0">
        <JoinBand login={login} canEnter={canEnter} contactUrl={contactUrl} title={'내일 준비,\n이제 기록으로 하세요'} fill />
        <SiteFooter contactUrl={contactUrl} />
      </section>
    </div>
  )
}
