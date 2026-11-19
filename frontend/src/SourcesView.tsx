import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, type SourcePlan } from './api'
import { fmtDate, fmtTime, SCHOOL_LABELS, SIGNAL_LABELS } from './format'

const ARTICLES_SHOWN = 15 // 행사·뉴스는 처음에 이만큼만 보여 준다

// "2026-11-12" → "11.12",  기간은 "11.12–11.15"
const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}.${Number(iso.slice(8, 10))}`
const period = (a: string, b: string) => (a === b ? shortDate(a) : `${shortDate(a)}–${shortDate(b)}`)
// 해까지: "2025.9.27 – 2026.11.20" (같은 해면 뒤쪽 해는 생략)
const longPeriod = (a: string, b: string) =>
  `${a.slice(0, 4)}.${shortDate(a)} – ${a.slice(0, 4) === b.slice(0, 4) ? '' : `${b.slice(0, 4)}.`}${shortDate(b)}`
// 출처 주소에서 사이트 이름만. 사이트 안 주소("/sample-news/…")는 그대로
const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}
// 가상 매장의 자리 채움 주소(example.com)는 열어도 내용이 없으므로 링크로 만들지 않는다
const isPlaceholder = (url: string) => host(url) === 'example.com'
// 모은 정보를 보여 줄 순서 = 이름표(SIGNAL_LABELS)에 적힌 순서
const order = (signal: string) => {
  const i = Object.keys(SIGNAL_LABELS).indexOf(signal)
  return i < 0 ? 99 : i
}

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="text-lg font-semibold">{title}</h3>
      {sub && <p className="mt-1 text-sm text-ink-700">{sub}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

// 고른 정보원 한 줄: 무엇을 · 근거(주변 시설) · 이유
function Choice({ what, evidence, reason }: { what: string; evidence?: string; reason: string }) {
  return (
    <li className="grid gap-x-4 gap-y-1 py-3 sm:grid-cols-[11rem_1fr]">
      <span className="font-semibold">{what}</span>
      <span className="text-sm leading-relaxed">
        {reason}
        {evidence && <span className="mt-1 block text-ink-700">근거가 된 주변 시설 — {evidence}</span>}
      </span>
    </li>
  )
}

// AI(정보원 선택 에이전트)가 이 매장에 고른 정보원과 이유
// brief: 첫 화면의 예시용 — 고른 정보원만 보이고, 아직 수집기가 없는 후보는 접어 둔다
function Plan({ plan, nNearby, brief = false }: { plan: SourcePlan; nNearby: number | null; brief?: boolean }) {
  const byRule = plan.method !== 'llm'
  return (
    <>
      <p className="text-sm text-ink-700">
        매장 주변 시설{nNearby ? ` ${nNearby}곳` : ''}을 보고{' '}
        {byRule ? '거리 규칙으로 정했습니다.' : 'AI가 골랐고, 고른 근거가 실제 주변 시설 목록에 있는지 코드가 다시 확인했습니다.'}
      </p>
      <ul className="mt-2 divide-y divide-line border-y border-line">
        {plan.weather?.use && <Choice what="날씨" reason={plan.weather.reason} />}
        {plan.academic?.map((a) => (
          <Choice key={a.school} what={`${SCHOOL_LABELS[a.school] ?? a.school} 학사일정`}
            evidence={`${a.evidence} (${a.distance_m}m)`} reason={a.reason} />
        ))}
        {plan.events && (
          <Choice what={`근처 행사 (반경 ${plan.events.radius_m}m)`} evidence={plan.events.evidence.join(', ')} reason={plan.events.reason} />
        )}
      </ul>
      {!!plan.candidates?.length && (
        <details className="mt-5" open={!brief}>
          <summary className="cursor-pointer text-sm font-semibold underline-offset-4 hover:underline">
            AI가 중요하다고 봤지만 아직 가져올 방법이 없는 정보원 {plan.candidates.length}개
          </summary>
          <ul className="mt-1 divide-y divide-line text-sm">
            {plan.candidates.map((c) => (
              <li key={c.source} className="grid gap-x-4 gap-y-0.5 py-2 text-ink-700 sm:grid-cols-[11rem_1fr]">
                <span className="text-ink-900">{c.source}</span>
                <span>
                  {c.reason} <span className="text-ink-500">({c.evidence}, {c.distance_m}m)</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

// brief: 첫 화면의 예시용 — 고른 정보원과 모은 정보까지만 (찾은 글 목록·수집 기록은 뺀다)
export function SourcesView({ storeId, brief = false }: { storeId: string; brief?: boolean }) {
  const { data, error, isLoading } = useQuery({ queryKey: ['sources', storeId], queryFn: () => api.sources(storeId) })
  const [showAll, setShowAll] = useState(false)
  if (isLoading) return <p className="text-ink-700">불러오는 중…</p>
  if (error || !data) return <p className="text-ink-700">이 매장은 주변 정보 수집 기록이 없습니다. '데이터 올리기'에서 다시 실행하면 생깁니다.</p>

  const signals = [...data.signals].sort((a, b) => order(a.signal) - order(b.signal))
  const articles = showAll ? data.articles : data.articles.slice(0, ARTICLES_SHOWN)

  return (
    <div className="space-y-10">
      <header>
        <p className="text-sm text-ink-700">주변 정보</p>
        <h2 className="mt-1 max-w-3xl text-h2">
          이 매장을 위해 어떤 정보를, 왜 모았나
        </h2>
        <p className="mt-3 max-w-3xl text-sm text-ink-700">
          모은 정보가 모두 예측에 쓰이는 것은 아닙니다. 과거 기록으로 확인해 예측을 실제로 더 정확하게 만든 정보만 쓰며, 그 결과는 '얼마나 맞나'에 있습니다.
        </p>
      </header>

      <Section title="AI가 고른 정보원">
        {data.plan ? (
          <Plan plan={data.plan} nNearby={data.n_nearby} brief={brief} />
        ) : (
          <p className="text-sm text-ink-700">정보원 선택 기록이 없습니다 (매장 주소 없이 실행했거나 주변 시설을 조회하지 못한 경우).</p>
        )}
      </Section>

      {brief && !!data.notes.length && (
        <p className="rounded-2xl bg-tag-sand px-4 py-3 text-sm text-ink-900">{data.notes[0]} 위의 정보원 선택은 실제 신촌 주소로 AI를 돌린 결과입니다.</p>
      )}
      <Section title="모은 정보" sub="정보마다 며칠치를 어디서 가져왔는지입니다.">
        {signals.length ? (
          <ul className="divide-y divide-line border-y border-line">
            {signals.map((s) => (
              <li key={s.signal} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 py-3 text-sm sm:grid-cols-[8rem_9rem_13rem_1fr]">
                <span className="font-semibold">{SIGNAL_LABELS[s.signal] ?? s.signal}</span>
                <span className="text-right tabular-nums sm:text-left">
                  {s.n_days}일{s.n_menus > 0 && ` · 메뉴 ${s.n_menus}개`}
                </span>
                <span className="text-ink-700 tabular-nums">{longPeriod(s.first_date, s.last_date)}</span>
                <span className="col-span-2 text-ink-700 sm:col-span-1">
                  {s.source_url && isPlaceholder(s.source_url) && '가상으로 만든 자료'}
                  {s.source_url && !isPlaceholder(s.source_url) && (
                    <a href={s.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-ink-900">
                      {host(s.source_url)}
                    </a>
                  )}
                  {s.note && <span className="block text-ink-700">{s.note}</span>}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-700">모은 정보가 없습니다. 판매 기록만으로 예측했습니다.</p>
        )}
      </Section>

      {!brief && !!data.articles.length && (
        <Section title={`찾은 행사·뉴스 ${data.articles.length}건`}
          sub="AI가 글에서 날짜와 장소를 뽑았고, 근거 문장이 원문에 그대로 있고 매장에서 가까운 것만 남겼습니다. 최근 날짜부터입니다.">
          <ul className="divide-y divide-line border-y border-line">
            {articles.map((a) => (
              <li key={a.source_url + a.title} className="grid grid-cols-[6.5rem_1fr] gap-3 py-2.5 text-sm">
                <span className="text-ink-700 tabular-nums" title={fmtDate(a.first_date)}>{period(a.first_date, a.last_date)}</span>
                <a href={a.source_url} target="_blank" rel="noreferrer" className="hover:underline hover:underline-offset-2">
                  {a.title} <span className="whitespace-nowrap text-ink-500">{host(a.source_url)}</span>
                </a>
              </li>
            ))}
          </ul>
          {data.articles.length > ARTICLES_SHOWN && (
            <button onClick={() => setShowAll(!showAll)} className="mt-3 text-sm underline underline-offset-4 hover:text-ink-900">
              {showAll ? '접기' : `나머지 ${data.articles.length - ARTICLES_SHOWN}건 더 보기`}
            </button>
          )}
        </Section>
      )}

      {!brief && !!data.notes.length && (
        <Section title="수집 기록">
          <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink-700">
            {data.notes.map((n, i) => (
              <li key={i} className="break-words">{n}</li>
            ))}
          </ul>
        </Section>
      )}
      <p className="text-xs text-ink-500">{fmtTime(data.generated_at)}에 수집</p>
    </div>
  )
}
