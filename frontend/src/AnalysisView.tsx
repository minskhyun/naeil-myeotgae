// '분석 중' 화면: 실행 중에 서버가 알려 주는 것(ProgressEvent)을 하나씩 보여 준다.
//   지도(AnalysisMap) — 찾은 정보가 가게로 들어오는 모습
//   단계 표시 · 지금 하는 일 · 들어온 정보 목록
//   끝나면: 무엇을 모았고, 무엇을 썼고, 얼마나 맞고, 내일 무엇을 준비하면 되는지 정리
// 알림은 몇 건씩 한꺼번에 도착하므로, 여기서 하나씩 시간 간격을 두고 풀어 놓는다(shown) → 실시간으로 들어오는 것처럼 보인다.
// 다시 보기(replay)도 같은 화면이다: 저장된 알림 전부를 같은 속도로 풀어 놓는다.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AnalysisMap } from './AnalysisMap'
import type { Job, ProgressEvent } from './api'
import { CountUp } from './CountUp'
import { cleanTitle, count as cnt, fmtDate, GROUP_LABELS, KIND_COLOR, pct1 } from './format'
import { Logo } from './Logo'

const STEPS = [
  { id: 'ingest', label: '판매 기록' },
  { id: 'collect', label: '주변 정보' },
  { id: 'evaluate', label: '검증' },
  { id: 'predict', label: '내일 예측' },
] as const

// 알림 하나를 보여 준 뒤 다음 것까지 기다리는 시간(ms). 지도에서 벌어지는 일이 끝날 만큼.
// 알림이 한꺼번에 몰려와도 이 간격대로 하나씩 풀어 놓는다 → 서버가 잠깐 조용해도 화면은 계속 움직인다
const PAUSE: Record<string, number> = {
  step: 120, status: 260, store: 2000, sales: 500, places: 1500, plan: 1500, weather: 700, academic: 700,
  event: 700, article: 450, special: 400, trend_span: 700, trend: 450, rating: 600, trial: 500, decision: 650, scores: 500, forecast: 500,
}

// 들어온 정보 목록의 한 줄: 종류(색 이름표) + 내용. 한 줄에 들어갈 만큼 짧게 쓴다
function line(e: ProgressEvent): { tag: string; color: string; text: string } | null {
  switch (e.kind) {
    // 판매를 끝낸 메뉴가 있으면 '지금 파는 메뉴' 수를 적는다 (준비표의 메뉴 수와 같아야 한다)
    case 'sales':
      return {
        tag: '판매 기록',
        color: KIND_COLOR.sales,
        text: `${e.days}일 · ${e.active !== undefined && e.active < e.menus ? `지금 파는 메뉴 ${e.active}개` : `메뉴 ${e.menus}개`}`,
      }
    case 'places': return { tag: '주변 시설', color: KIND_COLOR.places, text: `${e.count}곳` }
    case 'plan': return {
      tag: 'AI의 선택', color: KIND_COLOR.plan,
      text: `이 매장에 맞는 정보원을 골랐어요${e.radius_m ? ` · 행사 반경 ${e.radius_m}m` : ''}`,
    }
    case 'weather': return { tag: '날씨', color: KIND_COLOR.weather, text: `${e.days}일치` }
    case 'academic': return {
      tag: '학교 일정', color: KIND_COLOR.academic,
      text: [e.exams && `시험 ${e.exams}번`, e.vacations && `방학 ${e.vacations}번`, e.festivals && `축제 ${e.festivals}번`].filter(Boolean).join(' · ') || `${e.days}일`,
    }
    case 'event': return { tag: e.source === '뉴스·블로그' ? '소식 속 행사' : '근처 행사', color: e.source === '뉴스·블로그' ? KIND_COLOR.news : KIND_COLOR.event, text: `${e.title}${e.place ? ` · ${e.place}` : ''}` }
    case 'article': return { tag: '읽은 글', color: KIND_COLOR.article, text: cleanTitle(e.title) }
    case 'special': return {
      tag: '기념일', color: KIND_COLOR.special,
      text: `${e.name}${e.relevance ? ` · 연관도 ${e.relevance}/5` : ''}`,
    }
    case 'trend_span': return { tag: '검색량', color: KIND_COLOR.trend, text: `메뉴 ${e.menus}개 · ${e.days}일치` }
    case 'trend': return { tag: '검색량', color: KIND_COLOR.trend, text: `${e.menu} ${e.pct > 0 ? '+' : ''}${e.pct}%` }
    case 'rating': return {
      tag: 'AI의 평가', color: KIND_COLOR.plan,
      text: `${e.title} · 규모 ${e.scale}/5 · 연관도 ${e.relevance}/5`,
    }
    case 'trial': return {
      tag: '검증', color: KIND_COLOR.plan,
      text: `${e.groups.length ? `판매 기록 + ${e.groups.map((g) => GROUP_LABELS[g] ?? g).join('·')}` : '판매 기록만'} → ${e.miss !== undefined ? `하루 오차 ${cnt(e.miss)}개` : `오차율 ${pct1(e.wape)}`}`,
    }
    default: return null
  }
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="nm-rise rounded-[32px] bg-white p-6">
      <h3 className="text-label text-ink-500">{title}</h3>
      <div className="mt-4">{children}</div>
    </section>
  )
}

export function AnalysisView({ events, status, error, log, onClose, replay = false, onDone, doneLabel }: {
  events: ProgressEvent[] // 지금까지 서버가 알려 준 것 전부
  status: Job['status']
  error?: string | null
  log?: string[]
  onClose: () => void
  onDone?: () => void // 끝났을 때 맨 아래의 큰 버튼을 누르면 (없으면 그냥 닫는다)
  doneLabel?: string // 그 버튼의 이름 (예: '분석 페이지로 가기')
  replay?: boolean // 지난 분석을 다시 보는 중
}) {
  const [shown, setShown] = useState(0) // 화면에 풀어 놓은 알림 수
  const [seconds, setSeconds] = useState(0) // 시작한 지 몇 초 (기다리는 동안에도 화면이 살아 있게)
  useEffect(() => {
    if (status !== 'running') return
    const timer = window.setInterval(() => setSeconds((n) => n + 1), 1000)
    return () => window.clearInterval(timer)
  }, [status])
  const seen = useMemo(() => events.slice(0, shown), [events, shown])

  useEffect(() => {
    if (shown >= events.length) return
    const backlog = events.length - shown
    const wait = (PAUSE[events[shown].kind] ?? 300) * (backlog > 90 ? 0.3 : backlog > 45 ? 0.6 : 1) // 아주 많이 밀렸을 때만 빨리 감는다
    const timer = window.setTimeout(() => setShown((n) => n + 1), wait)
    return () => window.clearTimeout(timer)
  }, [events, shown])

  // 지금까지 본 알림에서 화면에 쓸 것을 뽑는다
  const find = <K extends ProgressEvent['kind']>(kind: K) =>
    [...seen].reverse().find((e) => e.kind === kind) as Extract<ProgressEvent, { kind: K }> | undefined
  const all = <K extends ProgressEvent['kind']>(kind: K) => seen.filter((e) => e.kind === kind) as Extract<ProgressEvent, { kind: K }>[]
  const store = find('store')
  const hasMap = !!store?.lat
  const steps = all('step')
  const stepState = (id: string) =>
    steps.some((s) => s.step === id && s.status === 'done') ? 'done' : steps.some((s) => s.step === id) ? 'now' : 'todo'
  const feed = seen.map(line).filter((x) => x !== null).reverse()
  const caughtUp = shown >= events.length
  const finished = status === 'done' && caughtUp
  const failed = status === 'error' && caughtUp
  const scores = find('scores')
  const forecast = find('forecast')
  const decisions = all('decision')
  const count = {
    places: find('places')?.count ?? 0,
    weather: find('weather')?.days ?? 0,
    events: all('event').length,
    articles: all('article').length,
    trends: all('trend').length,
  }
  // 화면에 적는 개수(반올림한 값)끼리 계산해 '78개 → 50개, 36% 적음'이 서로 맞게 한다. 개수가 없는 예전 기록은 비율로
  const gain = !scores
    ? 0
    : scores.miss !== undefined && scores.base_miss
      ? Math.round((1 - Math.round(scores.miss) / Math.round(scores.base_miss)) * 100)
      : Math.round((1 - scores.wape / scores.base_wape) * 100)

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-page text-ink-900">
      {/* 맨 위에 번지는 옅은 주황빛 (밝은 바탕이 밋밋하지 않게) */}
      <div className="nm-glow pointer-events-none absolute inset-x-0 top-0 h-[32rem]" aria-hidden />
      <div className="relative mx-auto flex min-h-full max-w-content flex-col px-5 py-5 md:px-10 lg:h-full">
        <div className="flex items-center justify-between">
          <Logo />
          <button onClick={onClose} className="inline-flex h-11 items-center rounded-full bg-white px-5 text-sm font-semibold transition-colors duration-150 hover:bg-pill">
            {finished || failed || replay ? '닫기' : '화면 닫기 (분석은 계속돼요)'}
          </button>
        </div>

        <header className="mt-5 mb-6">
          <p className="flex items-center gap-2.5 text-label text-ink-500">
            {!finished && !failed && <span className="nm-blink h-2.5 w-2.5 rounded-full bg-point" />}
            {failed ? '분석 중단' : finished ? '분석 완료' : '분석 중'}
          </p>
          <h2 className="mt-3 text-h1">
            {failed ? '분석을 마치지 못했어요' : finished ? '분석이 끝났어요' : `${store?.name ?? '우리 가게'} 주변을 살펴보고 있어요`}
          </h2>
          <p className="mt-2 min-h-7 text-lg text-ink-700">
            {failed
              ? error
              : finished
                ? '무엇을 모았고, 그중 무엇이 실제로 도움이 됐는지 아래에 정리했어요.'
                : (<>
                    {find('status')?.text ?? '시작하는 중'}<span className="nm-blink">…</span>
                    {status === 'running' && seconds >= 5 && (
                      <span className="ml-3 text-sm text-ink-500">{seconds >= 60 ? `${Math.floor(seconds / 60)}분 ` : ''}{seconds % 60}초째 · 보통 2~3분 걸려요</span>
                    )}
                  </>)}
          </p>
          <ol className="mt-5 flex flex-wrap gap-2">
            {STEPS.map((s, i) => {
              const state = stepState(s.id)
              return (
                <li key={s.id} className={`flex h-11 items-center gap-2.5 rounded-full px-5 font-medium ${
                  state === 'done' ? 'bg-ink-900 text-white' : state === 'now' ? 'bg-white text-ink-900' : 'bg-pill text-ink-500'}`}>
                  <span className="text-xs tabular-nums opacity-70">{String(i + 1).padStart(2, '0')}</span>
                  {s.label}
                  {state === 'done' && <span aria-hidden="true">✓</span>}
                  {state === 'now' && <span className="nm-blink h-2 w-2 rounded-full bg-point" />}
                </li>
              )
            })}
          </ol>
        </header>

        {/* 지도와 목록: 남는 높이를 채운다. 화면이 낮으면 이 칸은 22rem에서 더 줄지 않고(lg:min-h) 아래 칸들이 밀려나 화면이 스크롤된다.
            (전에는 0까지 줄 수 있어서, 전체 화면을 풀어 창이 낮아지면 아래의 결과 칸들이 지도 위로 겹쳤다) */}
        <div className="grid flex-1 gap-5 lg:min-h-[22rem] lg:shrink-0 lg:grid-cols-[1.65fr_1fr] lg:grid-rows-[minmax(0,1fr)]">
          <div className="relative h-[26rem] min-w-0 overflow-hidden rounded-[32px] bg-white lg:h-full lg:min-h-60">
            {hasMap ? (
              <AnalysisMap events={seen} />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 bg-surface px-8 text-center text-ink-900">
                <span className="nm-blink h-5 w-5 rounded-full bg-ink-900" />
                <p className="font-semibold">{store ? '매장 위치를 적지 않아 판매 기록만으로 분석해요' : '매장 위치를 찾고 있어요'}</p>
                {store && <p className="text-sm text-ink-700">위치를 적으면 날씨·근처 행사·소식을 지도에서 모으는 모습을 볼 수 있어요.</p>}
              </div>
            )}
            {hasMap && (
              <ul className="pointer-events-none absolute bottom-5 left-5 z-[500] flex flex-wrap gap-1.5 text-xs font-semibold text-ink-900">
                {count.places > 0 && <li className="tag border border-line bg-white text-ink-900">주변 시설 {count.places}</li>}
                {count.weather > 0 && <li className="tag border border-line bg-white text-ink-900">날씨 {count.weather}일</li>}
                {count.events > 0 && <li className="tag border border-line bg-white text-ink-900">행사 {count.events}</li>}
                {count.articles > 0 && <li className="tag border border-line bg-white text-ink-900">읽은 글 {count.articles}</li>}
                {count.trends > 0 && <li className="tag border border-line bg-white text-ink-900">검색량 {count.trends}</li>}
              </ul>
            )}
          </div>

          <section className="flex h-[26rem] min-w-0 flex-col rounded-[32px] bg-white p-6 lg:h-full lg:min-h-60">
            <h3 className="text-label text-ink-500">우리 가게로 들어온 정보 {feed.length > 0 && `· ${feed.length}건`}</h3>
            <ul className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
              {feed.length === 0 && <li className="text-sm text-ink-700">곧 여기에 하나씩 나타나요.</li>}
              {feed.map((f, i) => (
                <li key={feed.length - i} className="nm-rise flex items-start gap-2 rounded-2xl bg-page px-3 py-2.5 text-sm">
                  <span className="tag mt-0.5 shrink-0 gap-1.5 bg-white text-ink-900"><i className="h-2 w-2 rounded-full" style={{ background: f.color }} />{f.tag}</span>
                  <span className="min-w-0 [overflow-wrap:anywhere]">{f.text}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {failed && log && log.length > 0 && (
          <pre className="mt-5 overflow-x-auto rounded-[32px] bg-white p-6 text-xs leading-relaxed text-ink-700">{log.slice(-8).join('\n')}</pre>
        )}

        {finished && (
          <div className="mt-5 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            <Card title="모은 정보">
              <ul className="space-y-1.5 text-sm">
                {count.places > 0 && <li>주변 시설 <b>{count.places}곳</b></li>}
                {count.weather > 0 && <li>날씨 <b>{count.weather}일</b></li>}
                {count.events > 0 && <li>근처 행사 <b>{count.events}건</b></li>}
                {count.articles > 0 && <li>읽은 소식 <b>{count.articles}건</b></li>}
                {count.trends > 0 && <li>메뉴 검색량 <b>{count.trends}개</b></li>}
                {!hasMap && <li className="text-ink-700">판매 기록만 사용</li>}
              </ul>
            </Card>
            <Card title="예측에 쓴 정보">
              <ul className="space-y-1.5 text-sm">
                {decisions.map((d) => (
                  <li key={d.group} className="flex items-center justify-between gap-2" title={d.reason}>
                    <span>{GROUP_LABELS[d.group] ?? d.group}</span>
                    <span className={`tag ${d.adopted ? 'bg-ink-900 text-white' : 'bg-surface text-ink-500'}`}>
                      {d.adopted ? '씀' : '안 씀'}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="얼마나 맞나">
              {scores ? (
                <>
                  <p className="text-sm text-ink-700">지난주 그대로 준비할 때보다</p>
                  <p className={`mt-1 text-h1 tabular-nums ${gain > 0 ? 'text-point' : ''}`}>
                    {gain > 0 ? (
                      <>
                        오차
                        <br />
                        <CountUp to={gain} />% 감소
                      </>
                    ) : (
                      '비슷해요'
                    )}
                  </p>
                  {scores.miss !== undefined && scores.base_miss !== undefined && (
                    <p className="mt-3 text-sm text-ink-700">
                      하루 오차 {cnt(scores.base_miss)}개 → <b className="text-ink-900">{cnt(scores.miss)}개</b>
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-ink-700">검증 결과가 아직 없어요.</p>
              )}
            </Card>
            <Card title={forecast ? `${fmtDate(forecast.date)} 준비` : '내일 준비'}>
              <ul className="space-y-1.5 text-sm">
                {forecast?.top.slice(0, 4).map((r) => (
                  <li key={r.menu} className="flex items-baseline justify-between gap-2">
                    <span className="truncate">{r.menu}</span>
                    <b className="text-base text-ink-900 tabular-nums">{r.prep ?? r.pred}개</b>
                  </li>
                ))}
              </ul>
              {forecast && forecast.menus > 4 && <p className="mt-2 text-xs text-ink-700">외 {forecast.menus - 4}개 메뉴</p>}
              {!!forecast?.warnings.length && <p className="mt-2 text-xs font-semibold text-ink-700">주의할 소식 {forecast.warnings.length}건</p>}
            </Card>
          </div>
        )}

        {(finished || failed) && (
          <div className="mt-5 flex justify-center pb-1">
            <button onClick={failed || !onDone ? onClose : onDone} className="btn-pill group bg-ink-900 text-white hover:bg-ink-hover">
              {failed ? '닫기' : onDone && doneLabel ? doneLabel : replay ? '닫기' : '준비표 보기'}
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-ink-900 transition-transform duration-200 group-hover:translate-x-1" aria-hidden>
                →
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
