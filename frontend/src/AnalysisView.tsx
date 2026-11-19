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
import { count as cnt, fmtDate, GROUP_LABELS, KIND_COLOR, pct1, rangeScore, won } from './format'

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

// 가져온 기간을 괄호로 (예전 기록에는 기간이 없다 → 빈 글자)
const span = (e: { first?: string; last?: string }) => (e.first && e.last ? ` (${e.first} ~ ${e.last})` : '')

// 들어온 정보 목록의 한 줄: 종류(색 이름표) + 내용
function line(e: ProgressEvent): { tag: string; color: string; text: string } | null {
  switch (e.kind) {
    case 'sales': return { tag: '판매 기록', color: KIND_COLOR.sales, text: `${e.days}일 · 메뉴 ${e.menus}개 (${e.first} ~ ${e.last})` }
    case 'places': return { tag: '주변 시설', color: KIND_COLOR.places, text: `${e.count}곳을 살펴봤어요` }
    case 'plan': return {
      tag: 'AI의 선택', color: KIND_COLOR.plan,
      text: `이 매장에 맞는 정보원을 골랐어요${e.radius_m ? ` · 행사는 반경 ${e.radius_m}m` : ''}${e.picks.length ? ` · 근거 시설 ${e.picks.length}곳` : ''}`,
    }
    case 'weather': return { tag: '날씨', color: KIND_COLOR.weather, text: `${e.days}일치 기록과 예보${span(e)}` }
    case 'academic': return {
      tag: '학교 일정', color: KIND_COLOR.academic,
      text: `${[e.exams && `시험 기간 ${e.exams}번`, e.vacations && `방학 ${e.vacations}번`, e.festivals && `축제 ${e.festivals}번`].filter(Boolean).join(' · ') || '시험·방학·축제'} · 모두 ${e.days}일${span(e)}`,
    }
    case 'event': return { tag: e.source === '뉴스·블로그' ? '소식 속 행사' : '근처 행사', color: e.source === '뉴스·블로그' ? KIND_COLOR.news : KIND_COLOR.event, text: `${e.title}${e.place ? ` · ${e.place}` : ''}` }
    case 'article': return { tag: '읽은 글', color: KIND_COLOR.article, text: e.title }
    case 'special': return {
      tag: '기념일', color: KIND_COLOR.special,
      text: `${e.name} (${e.date})${e.relevance ? ` · 우리 가게와의 연관도 ${e.relevance}/5` : ''}${e.menus?.length ? ` · 특히 ${e.menus.slice(0, 3).join(', ')}` : ''}`,
    }
    case 'trend_span': return { tag: '검색량', color: KIND_COLOR.trend, text: `메뉴 ${e.menus}개의 ${e.days}일치 검색량${span(e)}` }
    case 'trend': return { tag: '검색량', color: KIND_COLOR.trend, text: `${e.menu} · 요즘 일주일 ${e.pct > 0 ? '+' : ''}${e.pct}% (그 전 4주와 비교)` }
    case 'rating': return {
      tag: 'AI의 평가', color: KIND_COLOR.plan,
      text: `${e.title} · 규모 ${e.scale}/5 · 우리 가게와의 연관도 ${e.relevance}/5 · ${e.distance_m}m${e.menus.length ? ` · 특히 ${e.menus.slice(0, 3).join(', ')}` : ''}`,
    }
    case 'trial': return {
      tag: '시험', color: KIND_COLOR.plan,
      text: `${e.groups.length ? `판매 기록 + ${e.groups.map((g) => GROUP_LABELS[g] ?? g).join('·')}` : '판매 기록만'}으로 지난 날들을 맞혀 봤어요 → ${e.miss !== undefined ? `하루 ${cnt(e.miss)}개 틀림` : `오차율 ${pct1(e.wape)}`}`,
    }
    default: return null
  }
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="nm-rise rounded-3xl bg-white p-6 text-ink shadow-xl">
      <h3 className="text-sm font-semibold text-accent">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  )
}

export function AnalysisView({ events, status, error, log, onClose, replay = false }: {
  events: ProgressEvent[] // 지금까지 서버가 알려 준 것 전부
  status: Job['status']
  error?: string | null
  log?: string[]
  onClose: () => void
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
  const gain = scores ? Math.round((1 - scores.wape / scores.base_wape) * 100) : 0

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-gradient-to-b from-accent to-accent-deep text-white">
      <div className="mx-auto max-w-6xl px-5 py-6">
        <div className="flex items-center justify-between">
          <p className="text-lg font-extrabold tracking-tight">내일몇개</p>
          <button onClick={onClose} className="rounded-full bg-white/15 px-4 py-1.5 text-sm font-semibold hover:bg-white/25">
            {finished || failed || replay ? '닫기' : '화면 닫기 (분석은 계속돼요)'}
          </button>
        </div>

        <header className="mt-6 mb-6">
          <h2 className="text-3xl font-extrabold tracking-tight sm:text-4xl">
            {failed ? '분석을 마치지 못했어요' : finished ? '분석이 끝났어요!' : `${store?.name ?? '우리 가게'} 주변을 살펴보고 있어요`}
          </h2>
          <p className="mt-2 min-h-6 text-white/85">
            {failed
              ? error
              : finished
                ? '무엇을 모았고, 그중 무엇이 실제로 도움이 됐는지 아래에 정리했어요.'
                : (<>
                    {find('status')?.text ?? '시작하는 중'}<span className="nm-blink">…</span>
                    {status === 'running' && seconds >= 5 && (
                      <span className="ml-3 text-sm text-white/60">{seconds >= 60 ? `${Math.floor(seconds / 60)}분 ` : ''}{seconds % 60}초째 · 보통 2~3분 걸려요</span>
                    )}
                  </>)}
          </p>
          <ol className="mt-5 flex flex-wrap gap-2">
            {STEPS.map((s, i) => {
              const state = stepState(s.id)
              return (
                <li key={s.id} className={`flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold ${
                  state === 'done' ? 'bg-white text-accent' : state === 'now' ? 'bg-white/25' : 'bg-white/10 text-white/60'}`}>
                  <span className="text-xs opacity-80">STEP {i + 1}</span>
                  {s.label}
                  {state === 'done' && <span aria-hidden="true">✓</span>}
                  {state === 'now' && <span className="nm-blink h-2 w-2 rounded-full bg-white" />}
                </li>
              )
            })}
          </ol>
        </header>

        <div className="grid gap-5 lg:grid-cols-[1.65fr_1fr]">
          <div className="relative h-[26rem] min-w-0 overflow-hidden rounded-3xl bg-white shadow-2xl sm:h-[32rem]">
            {hasMap ? (
              <AnalysisMap events={seen} />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 bg-accent-soft px-8 text-center text-ink">
                <span className="nm-blink h-5 w-5 rounded-full bg-accent" />
                <p className="font-semibold">{store ? '매장 위치를 적지 않아 판매 기록만으로 분석해요' : '매장 위치를 찾고 있어요'}</p>
                {store && <p className="text-sm text-muted">위치를 적으면 날씨·근처 행사·소식을 지도에서 모으는 모습을 볼 수 있어요.</p>}
              </div>
            )}
            {hasMap && (
              <ul className="pointer-events-none absolute bottom-3 left-3 z-[500] flex flex-wrap gap-1.5 text-xs font-semibold text-ink">
                {count.places > 0 && <li className="rounded-full bg-white/95 px-3 py-1 shadow">주변 시설 {count.places}</li>}
                {count.weather > 0 && <li className="rounded-full bg-white/95 px-3 py-1 shadow">날씨 {count.weather}일</li>}
                {count.events > 0 && <li className="rounded-full bg-white/95 px-3 py-1 shadow">행사 {count.events}</li>}
                {count.articles > 0 && <li className="rounded-full bg-white/95 px-3 py-1 shadow">읽은 글 {count.articles}</li>}
                {count.trends > 0 && <li className="rounded-full bg-white/95 px-3 py-1 shadow">검색량 {count.trends}</li>}
              </ul>
            )}
          </div>

          <section className="flex h-[26rem] min-w-0 flex-col rounded-3xl bg-white p-5 text-ink shadow-2xl sm:h-[32rem]">
            <h3 className="text-sm font-semibold text-accent">우리 가게로 들어온 정보 {feed.length > 0 && `· ${feed.length}건`}</h3>
            <ul className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
              {feed.length === 0 && <li className="text-sm text-muted">곧 여기에 하나씩 나타나요.</li>}
              {feed.map((f, i) => (
                <li key={feed.length - i} className="nm-rise flex items-start gap-2 rounded-2xl bg-paper px-3 py-2 text-sm">
                  <span className="mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-bold text-white" style={{ background: f.color }}>{f.tag}</span>
                  <span className="min-w-0 [overflow-wrap:anywhere]">{f.text}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {failed && log && log.length > 0 && (
          <pre className="mt-5 overflow-x-auto rounded-3xl bg-white/10 p-5 font-mono text-xs leading-relaxed">{log.slice(-8).join('\n')}</pre>
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
                {!hasMap && <li className="text-muted">판매 기록만 사용</li>}
              </ul>
            </Card>
            <Card title="예측에 쓴 정보">
              <ul className="space-y-1.5 text-sm">
                {decisions.map((d) => (
                  <li key={d.group} className="flex items-center justify-between gap-2" title={d.reason}>
                    <span>{GROUP_LABELS[d.group] ?? d.group}</span>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${d.adopted ? 'bg-accent text-white' : 'bg-paper text-faint'}`}>
                      {d.adopted ? '씀' : '안 씀'}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">지난 기록으로 시험해 실제로 더 정확해진 정보만 써요.</p>
            </Card>
            <Card title="얼마나 맞나">
              {scores?.miss !== undefined && scores.base_miss !== undefined ? (
                <>
                  <p className="text-4xl font-extrabold tracking-tight tabular-nums">
                    하루 <CountUp to={Math.max(0, scores.base_miss - scores.miss)} />개
                  </p>
                  <p className="mt-1 text-sm">
                    '지난주 같은 요일만큼' 준비할 때보다 덜 틀린 개수{gain > 0 && ` (${gain}% 적음)`}
                  </p>
                  <p className="mt-3 text-xs text-muted">
                    남거나 모자란 개수 하루 {cnt(scores.base_miss)}개 → {cnt(scores.miss)}개
                    {scores.saved_amount !== undefined && scores.saved_amount > 0 && ` · 판매가로 하루 약 ${won(scores.saved_amount)}`}
                    {' '}· 예상 범위 정확도 {pct1(rangeScore(scores.coverage))}
                    {scores.test_days ? ` · 마지막 ${scores.test_days}일로 시험` : ''}
                  </p>
                </>
              ) : scores ? (
                <>
                  <p className="text-4xl font-extrabold tracking-tight tabular-nums">
                    <CountUp to={scores.wape * 100} format={(v) => v.toFixed(1)} />%
                  </p>
                  <p className="mt-1 text-sm">
                    오차율 (평균 오차 ÷ 평균 판매량){gain > 0 && ` · '지난주 같은 요일만큼'보다 ${gain}% 적음`}
                  </p>
                  <p className="mt-3 text-xs text-muted">
                    예상 범위 정확도 {pct1(rangeScore(scores.coverage))} (100%가 만점 · 실제 판매의 {pct1(scores.coverage)}가 범위 안, 목표 80%)
                    {scores.test_days ? ` · 마지막 ${scores.test_days}일로 시험` : ''}
                  </p>
                </>
              ) : (
                <p className="text-sm text-muted">기록이 짧아 최종 시험 없이 검증 기간 결과만 있어요.</p>
              )}
            </Card>
            <Card title={forecast ? `${fmtDate(forecast.date)} 준비` : '내일 준비'}>
              <ul className="space-y-1.5 text-sm">
                {forecast?.top.slice(0, 4).map((r) => (
                  <li key={r.menu} className="flex items-baseline justify-between gap-2">
                    <span className="truncate">{r.menu}</span>
                    <b className="text-base text-accent tabular-nums">{r.prep ?? r.pred}개</b>
                  </li>
                ))}
              </ul>
              {forecast && forecast.menus > 4 && <p className="mt-2 text-xs text-muted">외 {forecast.menus - 4}개 메뉴</p>}
              {!!forecast?.warnings.length && <p className="mt-2 text-xs font-semibold text-warn">주의할 소식 {forecast.warnings.length}건</p>}
            </Card>
          </div>
        )}

        {(finished || failed) && (
          <div className="mt-8 flex justify-center pb-6">
            <button onClick={onClose} className="rounded-full bg-white px-8 py-3 text-base font-bold text-ink shadow-xl hover:bg-paper">
              {failed ? '닫기' : replay ? '닫기' : '준비표 보기'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
