// 소개 ('/about'): 어떻게 예측하고, 결과가 어떻게 나오고, 얼마나 맞는지를 한 곳에 정리한다.
//   네 단계 → 예측 방법 → 주변 정보를 고르는 기준 → AI가 하는 일 → 예시 매장의 실제 결과(준비표 · 쓴 정보 · 검증). 자주 묻는 질문은 고객지원(Support.tsx)에 있다
// 첫 화면(Landing.tsx)은 무엇을 해 주는지만 보여 주고, 방법과 검증은 여기에 모은다.
// 적는 내용은 코드가 실제로 하는 일과 같아야 한다 (숫자 기준은 ml/evaluate.py, ml/models.py, ml/features.py).
import { useState, type CSSProperties, type ReactNode } from 'react'
import { AnalysisView } from './AnalysisView'
import { BacktestView, Decisions } from './BacktestView'
import { ForecastView } from './ForecastView'
import { Lines, Reveal } from './Reveal'
import { useSnapScroll } from './scrub'
import { JoinBand, SiteFooter, SiteHeader, type SiteProps } from './Site'
import { useExample } from './example'
import { SourcesView } from './SourcesView'

const MENUS_SHOWN = 8 // 예시 준비표에 처음 보여 줄 메뉴 수

// 판매 기록이 준비표가 되기까지 (run.py의 네 단계)
const STEPS = [
  { title: '판매 기록 정리', text: '포스 파일을 날짜·메뉴·수량 표로 정리해요. AI 없이 규칙으로만 처리해요.' },
  { title: '주변 정보 모으기', text: '주소를 기준으로 날씨, 근처 학교 일정, 행사, 메뉴 검색량을 모아요.' },
  { title: '지난 날짜로 시험하기', text: '지난 날짜를 전날까지의 기록으로 맞혀 보며, 도움이 되는 정보만 골라요.' },
  { title: '다음 날 예측하기', text: '메뉴마다 예상 판매량, 범위, 준비할 개수를 드려요.' },
]

// 예측 방법의 핵심 세 가지 (ml/models.py, ml/predict.py)
const METHOD = [
  { title: '평소보다 몇 배 팔릴지를 배워요', text: '최근 28일 평균 대비 비율을 배워서, 많이 팔리는 메뉴와 적게 팔리는 메뉴를 함께 다뤄요.' },
  { title: '숫자 하나가 아니라 범위로 답해요', text: '실제 판매 10번 중 8번이 들어올 범위를 함께 보여 드려요.' },
  { title: '준비 개수는 사장님이 골라요', text: '폐기를 줄일지, 품절을 줄일지 고르시면 그에 맞는 개수를 드려요.' },
]

// 주변 정보를 쓸지 정하는 규칙 (ml/evaluate.py의 beats · pick_combo, ml/features.py의 시점 규칙)
const RULES = [
  { title: '오차가 3% 이상 줄어야', text: '그보다 작은 차이는 우연일 수 있어요.' },
  { title: '절반이 넘는 기간에서 나아져야', text: '한 기간에서만 좋았던 정보는 쓰지 않아요.' },
  { title: '다른 정보에 얹혀 가면 안 돼요', text: '하나씩 빼 보고, 빼면 나빠지는 정보만 남겨요.' },
  { title: '그때 몰랐던 정보는 쓰지 않아요', text: '전날 영업이 끝날 때까지 공개된 정보로만 예측해요. 지난 날짜 시험도 마찬가지예요.' },
]

const SIGNALS = [
  { name: '날씨', text: '기온(최근 평균과의 차이), 비' },
  { name: '학사일정·행사', text: '근처 학교의 시험·방학·축제, 주변 행사의 규모와 거리' },
  { name: '유행', text: '메뉴 이름의 검색량 변화' },
  { name: '기념일', text: '기념일 당일과 다가오는 정도' },
]

// AI(LLM)가 하는 일 (agent/, ml/alerts.py)
const AI_JOBS = [
  { title: '어디를 볼지 고르기', text: '주변 시설을 보고 살펴볼 학교와 행사 범위를 정해요.' },
  { title: '글에서 행사 찾기', text: '뉴스·블로그에서 행사 날짜와 장소를 뽑아요.' },
  { title: '우리 가게와의 관련 따지기', text: '행사·기념일이 우리 메뉴와 얼마나 관련 있는지 1~5로 매겨요. 이 점수도 검증을 통과해야 써요.' },
  { title: '주의할 소식 쓰기', text: '예측에 못 담은 일을 알려요. 인용이 원문에 없으면 버려요.' },
]

// 큰 구역 하나: 제목 · 설명 · 내용. id = 다른 화면에서 찾아오는 자리
function Block({ id, title, lead, children }: { id?: string; title: string; lead?: string; children: ReactNode }) {
  return (
    <section id={id} className="nm-screen mx-auto w-full max-w-content px-5 md:px-10">
      <div className="max-w-3xl">
        <Lines text={title} className="text-title" />
        {lead && (
          <Reveal as="p" className="mt-5 text-xl leading-8 text-ink-700">
            {lead}
          </Reveal>
        )}
      </div>
      <div className="mt-10">{children}</div>
    </section>
  )
}

// 제목과 설명이 든 칸들을 격자로
function Cards({ items, cols, numbered = false }: { items: { title: string; text: string }[]; cols: string; numbered?: boolean }) {
  return (
    <ol className={`grid gap-4 ${cols}`}>
      {items.map((it, i) => (
        <li key={it.title}>
          <Reveal lag={i * 0.1} className="h-full rounded-3xl bg-white px-7 py-8">
            {numbered && <span className="text-label text-ink-500">{i + 1}단계</span>}
            <h3 className={`text-h3 ${numbered ? 'mt-4' : ''}`}>{it.title}</h3>
            <p className="mt-3 leading-relaxed text-ink-700">{it.text}</p>
          </Reveal>
        </li>
      ))}
    </ol>
  )
}

// 예시 결과의 한 부분: 제목 · 한 줄 설명 · 실제 화면
function Part({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <section className="nm-screen mx-auto w-full max-w-content px-5 md:px-10">
      <Reveal>
        <h3 className="text-h2">{title}</h3>
        <p className="mt-2 text-lg text-ink-700">{lead}</p>
      </Reveal>
      <Reveal className="mt-6 rounded-[32px] bg-white p-5 sm:p-8">{children}</Reveal>
    </section>
  )
}

export function About({ login, contactUrl, canEnter }: SiteProps) {
  useSnapScroll()
  const { stores, store, past } = useExample()
  // 예시 매장을 분석했을 때의 과정(녹화본)을 지도 장면으로 다시 본다. 주소로는 ?open=replay
  const [replaying, setReplaying] = useState(new URLSearchParams(window.location.search).get('open') === 'replay')
  const virtual = !!store?.name.includes('가상') // 판매 기록을 가상으로 만든 예시인가 (주변 정보는 실제 주소로 모은 것)

  return (
    <div>
      {replaying && past && <AnalysisView events={past} status="done" replay onClose={() => setReplaying(false)} />}
      <SiteHeader login={login} canEnter={canEnter} contactUrl={contactUrl} here="about" />

      <section className="nm-screen mx-auto w-full max-w-content px-5 md:px-10">
        <h1 className="nm-enter text-hero">
          <span style={{ '--i': 0 } as CSSProperties}>판매 기록이</span>
          <span style={{ '--i': 1 } as CSSProperties}>준비표가 되기까지</span>
        </h1>
        <p className="mt-6 max-w-2xl text-xl leading-8 text-ink-700">
          어떻게 예측하고 얼마나 맞는지, 숨김없이 보여 드려요.
        </p>
      </section>

      <main>
        <Block id="how" title="네 단계로 준비표를 만들어요" lead="필요한 건 판매 기록 파일과 가게 주소뿐이에요.">
          <Cards items={STEPS} cols="md:grid-cols-2 lg:grid-cols-4" numbered />
        </Block>

        <Block title="이렇게 예측해요">
          <Cards items={METHOD} cols="md:grid-cols-3" />
        </Block>

        <Block title={'주변 정보는\n도움이 될 때만 써요'} lead="가게마다 지난 기록으로 확인해, 네 조건을 모두 채운 정보만 써요.">
          <Cards items={RULES} cols="md:grid-cols-2" />
        </Block>

        <Block title="이런 정보를 살펴봐요" lead="묶음마다 따로 쓸지 정해요.">
          <Reveal className="rounded-3xl bg-white px-7 py-2">
            <ul className="divide-y divide-line">
              {SIGNALS.map((s) => (
                <li key={s.name} className="flex flex-wrap items-baseline gap-x-6 gap-y-1 py-4">
                  <span className="w-32 shrink-0 font-semibold">{s.name}</span>
                  <span className="text-ink-700">{s.text}</span>
                </li>
              ))}
            </ul>
          </Reveal>
        </Block>

        <Block title="AI는 이런 일을 해요" lead="AI는 판매 숫자를 만들지 않아요. 글을 읽고 정리하는 일만 해요.">
          <Cards items={AI_JOBS} cols="md:grid-cols-2" />
        </Block>

        <Block id="example" title="예시 매장의 실제 결과" lead="위 과정을 예시 매장에 그대로 돌린 결과예요.">
          {stores.error && <p className="text-sm text-down">예시를 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}
          {stores.data && !store && <p className="text-ink-700">보여 줄 예시 매장이 아직 없습니다.</p>}
          {store && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                {virtual && (
                  <p className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-ink-700">
                    판매 기록은 가상, 날씨·학교 일정·행사·기사는 실제 신촌 자료예요
                  </p>
                )}
                {!!past?.length && (
                  <button onClick={() => setReplaying(true)} className="btn-md btn-secondary">
                    AI가 분석하는 과정 보기
                  </button>
                )}
              </div>
            </>
          )}
        </Block>
        {store && (
            <>
              <Part title="메뉴별로 몇 개 준비할지" lead="메뉴를 누르면 달라진 이유와 그래프가 펼쳐져요.">
                <ForecastView storeId={store.store_id} prepMode={store.prep_mode} readOnly limit={MENUS_SHOWN} />
              </Part>

              <Part title="어떤 주변 정보를 썼나" lead="예측이 실제로 더 정확해진 정보만 써요.">
                <div className="space-y-10">
                  <Decisions storeId={store.store_id} />
                  <details>
                    <summary className="cursor-pointer text-sm font-semibold underline-offset-4 hover:underline">AI가 고른 정보원 자세히 보기</summary>
                    <div className="mt-8">
                      <SourcesView storeId={store.store_id} brief />
                    </div>
                  </details>
                </div>
              </Part>

              <Part title="얼마나 맞나" lead="지난 날짜를 전날까지의 기록으로 맞혀 실제와 비교했어요.">
                <BacktestView storeId={store.store_id} hideDecisions />
              </Part>
            </>
          )}
      </main>

      <section className="nm-screen !justify-start !py-0">
        <JoinBand login={login} canEnter={canEnter} contactUrl={contactUrl} fill />
        <SiteFooter contactUrl={contactUrl} />
      </section>
    </div>
  )
}
