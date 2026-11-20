// 소개 ('/about'): 어떻게 예측하고, 결과가 어떻게 나오고, 얼마나 맞는지를 한 곳에 정리한다.
//   네 단계 → 예측 방법 → 주변 정보를 고르는 기준 → AI가 하는 일 → 예시 매장의 실제 결과(준비표 · 쓴 정보 · 검증). 자주 묻는 질문은 고객지원(Support.tsx)에 있다
// 첫 화면(Landing.tsx)은 무엇을 해 주는지만 보여 주고, 방법과 검증은 여기에 모은다.
// 적는 내용은 코드가 실제로 하는 일과 같아야 한다 (숫자 기준은 ml/evaluate.py, ml/models.py, ml/features.py).
import { useState, type CSSProperties, type ReactNode } from 'react'
import { Picture } from './AboutArt'
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
  { art: 'tidy', title: '판매 기록 정리', text: '포스에서 내려받은 파일을 읽어 날짜·메뉴·수량 표로 만들어요. 합계 줄, 취소, 금액권처럼 메뉴가 아닌 줄은 뺍니다. 이 단계는 규칙으로만 처리하고 AI를 쓰지 않아요.' },
  { art: 'gather', title: '주변 정보 모으기', text: '가게 주소로 위치를 찾고, 그 주변의 날씨, 근처 학교의 시험·방학·축제, 행사, 기념일, 메뉴 이름의 검색량을 모아요.' },
  { art: 'rehearse', title: '지난 날짜로 시험하기', text: '지난 날짜를 그 전날까지의 기록만 보고 맞혀 봅니다. 여기서 어떤 주변 정보가 이 가게에 실제로 도움이 되는지 가려내요.' },
  { art: 'tomorrow', title: '다음 날 예측하기', text: '전체 기록으로 다시 배운 뒤, 다음 날 메뉴마다 예상 판매량과 범위, 준비할 개수를 냅니다.' },
]

// 예측 방법의 핵심 세 가지 (ml/models.py, ml/predict.py)
const METHOD = [
  { art: 'ratio', title: '평소보다 몇 배 팔릴지를 배워요', text: '맞히는 값은 개수가 아니라 평소(최근 28일 평균) 대비 비율이에요. 하루 60개 팔리는 메뉴와 3개 팔리는 메뉴를 한 모델이 같은 단위로 배웁니다. 어제·지난주 판매, 요일, 공휴일, 가게 전체의 최근 흐름이 재료예요.' },
  { art: 'range', title: '숫자 하나가 아니라 범위로 답해요', text: '예상 판매량 둘레에 판매 개수가 퍼지는 모양(확률 분포)을 그려, 실제 판매 10번 중 8번이 들어올 범위를 함께 보여 드려요. 얼마나 넓게 퍼지는지는 가게마다 지난 기록에서 잽니다.' },
  { art: 'prep', title: '준비 개수는 사장님이 골라요', text: '폐기를 줄이려면 조금 적게, 품절을 줄이려면 넉넉하게. 같은 분포에서 기준에 맞는 지점을 꺼내 준비 개수로 드려요.' },
]

// 주변 정보를 쓸지 정하는 규칙 (ml/evaluate.py의 beats · pick_combo, ml/features.py의 시점 규칙)
const RULES = [
  { art: 'gain', title: '오차가 3% 이상 줄어야', text: '그 정보를 넣었을 때 전체 오차가 3% 이상 줄지 않으면 쓰지 않아요. 그보다 작은 차이는 우연과 구분되지 않습니다.' },
  { art: 'folds', title: '절반이 넘는 기간에서 나아져야', text: '시험한 기간을 여럿으로 나눠, 그중 절반이 넘는 기간에서 나아져야 해요. 한 기간에서만 좋았던 정보는 쓰지 않습니다.' },
  { art: 'alone', title: '다른 정보에 얹혀 가면 안 돼요', text: '여러 정보를 함께 쓸 때는 하나씩 빼 보고, 뺐을 때 매번 나빠지는 조합만 씁니다.' },
  { art: 'cutoff', title: '그때 몰랐던 정보는 쓰지 않아요', text: '어느 날의 예측은 그 전날 영업이 끝난 시각까지 공개된 정보로만 만들어요. 지난 날짜를 시험할 때도 같은 규칙을 지킵니다.' },
]

// 살펴보는 정보: 분야 넷, 그 안의 묶음 여덟 (ml/features.py의 SIGNAL_FAMILIES · SIGNAL_GROUPS). 쓸지 말지는 묶음마다 따로 정한다
const FAMILIES = [
  { name: '날씨', parts: ['기온', '비'], text: '기온은 최근 평균과의 차이로 봐요.' },
  { name: '학사일정·행사', parts: ['시험기간', '방학', '학교 축제', '근처 행사'], text: '근처 학교의 일정과, 주변 행사의 규모·거리.' },
  { name: '유행', parts: ['검색량'], text: '메뉴 이름의 검색량 변화.' },
  { name: '기념일', parts: ['기념일'], text: '당일과 다가오는 정도.' },
]
// 고르는 순서 (ml/evaluate.py의 choose_signals)
const PICKING = [
  { title: '먼저 분야끼리 견줘요', text: '자료가 있는 분야의 조합을 모두 넣어 보고, 위의 조건을 채우는 조합 가운데 오차가 가장 작은 것을 골라요.' },
  { title: '그다음 분야 안을 들여다봐요', text: '분야 안의 정보를 하나씩 넣어 보며 조건을 넘는 것만 더해요. 같은 학사일정이라도 방학은 듣고 시험기간은 안 듣는 가게라면 방학만 씁니다.' },
]

// AI(LLM)가 하는 일 (agent/, ml/alerts.py)
const AI_JOBS = [
  { art: 'choose', title: '어디를 볼지 고르기', text: '가게 주변 시설을 보고, 이 가게에 영향을 줄 만한 학교와 행사 범위를 정해요.' },
  { art: 'read', title: '글에서 행사 찾기', text: '뉴스와 블로그 글을 읽고 행사의 날짜와 장소를 뽑아요.' },
  { art: 'rate', title: '우리 가게와의 관련 따지기', text: '행사와 기념일이 이 가게, 이 메뉴와 얼마나 관련 있는지 1~5로 매겨요. 이 점수도 위의 검증을 통과해야 예측에 쓰입니다.' },
  { art: 'notice', title: '주의할 소식 쓰기', text: '예측에 담지 못한 일을 문장으로 알려요. 근거로 인용한 문장이 원문에 실제로 없으면 버립니다.' },
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

// 그림 · 제목 · 설명이 든 칸들을 격자로. 그림(AboutArt.tsx)은 칸의 위에 두고, side면 왼쪽에 둔다 (칸이 낮아야 하는 화면)
function Cards({ items, cols, numbered = false, side = false }: { items: { art: string; title: string; text: string }[]; cols: string; numbered?: boolean; side?: boolean }) {
  return (
    <ol className={`grid gap-4 ${cols}`}>
      {items.map((it, i) => (
        <li key={it.title}>
          <Reveal lag={i * 0.1} className={`h-full rounded-3xl bg-white ${side ? 'flex items-center gap-6 px-6 py-6' : 'px-7 py-7'}`}>
            <div className={`shrink-0 rounded-2xl bg-page ${side ? 'h-24 w-36 p-2' : 'h-36 w-full p-3'}`}>
              <Picture name={it.art} />
            </div>
            <div className={side ? 'min-w-0' : 'mt-6'}>
              {numbered && <span className="text-label text-ink-500">{i + 1}단계</span>}
              <h3 className={`text-h3 ${numbered ? 'mt-2' : ''}`}>{it.title}</h3>
              <p className={`leading-relaxed text-ink-700 ${side ? 'mt-1.5 text-sm' : 'mt-3'}`}>{it.text}</p>
            </div>
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
          내일몇개가 어떻게 예측하는지, 주변 정보를 어떤 기준으로 쓰는지, 얼마나 맞는지를 숨김없이 적었어요.
        </p>
      </section>

      <main>
        <Block id="how" title="네 단계로 준비표를 만들어요" lead="사장님이 주시는 것은 판매 기록 파일과 가게 주소 둘뿐이에요.">
          <Cards items={STEPS} cols="md:grid-cols-2 lg:grid-cols-4" numbered />
        </Block>

        <Block title="이렇게 예측해요">
          <Cards items={METHOD} cols="md:grid-cols-3" />
        </Block>

        <Block title={'주변 정보는\n도움이 될 때만 써요'} lead="날씨가 중요한 가게도 있고 아닌 가게도 있어요. 그래서 가게마다 지난 기록으로 확인해, 아래 조건을 모두 채운 정보만 예측에 넣습니다.">
          <Cards items={RULES} cols="md:grid-cols-2" side />
        </Block>

        <Block title="이런 정보를 살펴봐요" lead="여덟 가지 정보를 네 분야로 묶어 두고, 쓸지 말지는 하나하나 따로 정해요.">
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-[1fr_1.6fr_1fr_1fr]">
            {FAMILIES.map((f, i) => (
              <li key={f.name}>
                <Reveal lag={i * 0.1} className="h-full rounded-3xl bg-white px-6 py-6">
                  <h3 className="text-h3">{f.name}</h3>
                  <ul className="mt-4 flex flex-wrap gap-2">
                    {f.parts.map((part) => (
                      <li key={part} className="rounded-full bg-page px-3.5 py-1.5 text-sm font-medium">
                        {part}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-4 text-sm leading-relaxed text-ink-700">{f.text}</p>
                </Reveal>
              </li>
            ))}
          </ul>
          <ol className="mt-4 grid gap-4 md:grid-cols-2">
            {PICKING.map((it, i) => (
              <li key={it.title}>
                <Reveal lag={0.3 + i * 0.1} className="flex h-full items-start gap-5 rounded-3xl bg-white px-6 py-6">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink-900 font-semibold text-white">{i + 1}</span>
                  <div>
                    <h3 className="text-h3">{it.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-700">{it.text}</p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ol>
        </Block>

        <Block title="AI는 이런 일을 해요" lead="AI(대형 언어 모델)는 판매 숫자를 만들지 않아요. 글을 읽고 정리하는 일을 맡습니다.">
          <Cards items={AI_JOBS} cols="md:grid-cols-2" side />
        </Block>

        <Block id="example" title="예시 매장의 실제 결과" lead="위의 과정을 예시 매장에 그대로 돌린 결과예요. 분석 화면과 같은 화면입니다.">
          {stores.error && <p className="text-sm text-down">예시를 불러오지 못했습니다. 백엔드가 켜져 있는지 확인해 주세요.</p>}
          {stores.data && !store && <p className="text-ink-700">보여 줄 예시 매장이 아직 없습니다.</p>}
          {store && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                {virtual && (
                  <p className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-ink-700">
                    예시 매장의 판매 기록은 가상이고, 날씨·학교 일정·행사·기사는 실제 신촌의 것입니다
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
              <Part title="메뉴별로 몇 개 준비할지" lead="메뉴마다 준비할 개수와 평소와 달라진 이유를 보여 줘요. 메뉴를 누르면 그래프가 펼쳐집니다.">
                <ForecastView storeId={store.store_id} prepMode={store.prep_mode} readOnly limit={MENUS_SHOWN} />
              </Part>

              <Part title="어떤 주변 정보를 썼나" lead="모은 정보 중에서 예측이 실제로 더 정확해진 것만 써요.">
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

              <Part title="얼마나 맞나" lead="지난 날짜를 전날까지의 기록만 보고 맞혀 본 뒤, 실제 판매와 비교했어요.">
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
