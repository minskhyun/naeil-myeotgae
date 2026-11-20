// 고객지원 ('/support'): 처음 쓰는 법 → 자주 묻는 질문 → 문의. 도움이 필요할 때 여기 한 곳만 보면 되게 모았다.
// 한 화면에 한 내용 (index.css의 nm-screen · nm-snap). 적는 내용은 지금 실제로 되는 것만.
import { type CSSProperties, type ReactNode } from 'react'
import { PRIVACY_PATH, TERMS_PATH } from './api'
import { FAQ } from './example'
import { Lines, Reveal } from './Reveal'
import { useSnapScroll } from './scrub'
import { ArrowLink, JoinBand, SiteFooter, SiteHeader, type SiteProps } from './Site'

// 첫 준비표를 받기까지
const GUIDE = [
  { title: '로그인하고 매장 만들기', text: '구글이나 카카오 계정으로 로그인한 뒤, 매장 이름과 주소, 닫는 시간을 적어요. 주소는 날씨와 근처 소식을 찾는 데 씁니다.' },
  { title: '판매 기록 파일 올리기', text: '포스나 매출 프로그램에서 날짜·메뉴·수량이 든 엑셀이나 CSV를 내려받아 올려요. 3주치 이상이 필요합니다.' },
  { title: '준비표 확인하기', text: '몇 분 뒤 내일 메뉴별 준비 개수가 나와요. 폐기를 줄일지 품절을 줄일지는 준비 기준에서 고릅니다.' },
]

// 판매 기록을 다룰 때 알아 둘 것
const TIPS = [
  { title: '필요한 열만 보관해요', text: '올린 파일에서 날짜·메뉴·수량·시각·금액 열만 남기고 나머지는 저장하지 않아요. 손님 전화번호나 카드 정보가 든 열은 서버에 남지 않습니다.' },
  { title: '하루치는 직접 적어도 돼요', text: '파일을 다시 내려받지 않아도, 대시보드의 판매 입력에서 그날 판매 수량을 적으면 그 기록까지 넣어 다시 예측합니다.' },
  { title: '새 파일이 기준이에요', text: '나중에 그 날짜가 든 새 파일을 올리면 직접 적은 것 대신 파일의 기록을 씁니다. 같은 판매가 두 번 세어지지 않아요.' },
]

function Screen({ id, title, lead, children }: { id?: string; title: string; lead?: string; children: ReactNode }) {
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

function Cards({ items, numbered = false }: { items: { title: string; text: string }[]; numbered?: boolean }) {
  return (
    <ol className="grid gap-4 md:grid-cols-3">
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

export function Support({ login, contactUrl, canEnter }: SiteProps) {
  useSnapScroll()
  return (
    <div>
      <SiteHeader login={login} canEnter={canEnter} contactUrl={contactUrl} here="support" />

      <section className="nm-screen mx-auto w-full max-w-content px-5 md:px-10">
        <h1 className="nm-enter text-hero">
          <span style={{ '--i': 0 } as CSSProperties}>무엇을</span>
          <span style={{ '--i': 1 } as CSSProperties}>도와드릴까요</span>
        </h1>
        <div className="nm-enter">
          <p className="mt-6 max-w-2xl text-xl leading-8 text-ink-700" style={{ '--i': 3 } as CSSProperties}>
            처음 쓰는 법과 자주 묻는 질문을 모았어요. 여기에 없는 것은 문의로 알려 주세요.
          </p>
          <div className="mt-10 flex flex-wrap gap-3" style={{ '--i': 4 } as CSSProperties}>
            <ArrowLink href="#guide" dark>
              처음 쓰는 법
            </ArrowLink>
            <ArrowLink href="#faq">자주 묻는 질문</ArrowLink>
            <ArrowLink href="#contact">문의하기</ArrowLink>
          </div>
        </div>
      </section>

      <main>
        <Screen id="guide" title="첫 준비표까지 세 단계" lead="판매 기록 파일과 가게 주소만 있으면 돼요.">
          <Cards items={GUIDE} numbered />
        </Screen>

        <Screen title="판매 기록을 다룰 때">
          <Cards items={TIPS} />
        </Screen>

        <Screen id="faq" title="자주 묻는 질문">
          <Reveal className="divide-y divide-line rounded-3xl bg-white px-6 sm:px-8">
            {FAQ.map((f) => (
              <details key={f.q} className="group py-4">
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
        </Screen>

        <Screen id="contact" title="문의하기" lead="쓰다가 막히는 곳, 잘못 나온 숫자, 바라는 기능을 알려 주세요.">
          <Reveal className="flex flex-wrap items-center gap-4">
            {contactUrl ? (
              <ArrowLink href={contactUrl} dark>
                문의 남기기
              </ArrowLink>
            ) : (
              <p className="rounded-2xl bg-white px-6 py-5 text-ink-700">문의 창구를 준비하고 있어요. 지금은 시연 단계입니다.</p>
            )}
            <ArrowLink href={PRIVACY_PATH}>개인정보처리방침</ArrowLink>
            <ArrowLink href={TERMS_PATH}>이용약관</ArrowLink>
          </Reveal>
        </Screen>
      </main>

      <section className="nm-screen !justify-start !py-0">
        <JoinBand login={login} canEnter={canEnter} contactUrl={contactUrl} fill />
        <SiteFooter contactUrl={contactUrl} />
      </section>
    </div>
  )
}
