// 첫 화면(Landing.tsx)과 소개(About.tsx)가 함께 쓰는 틀: 맨 위 머리말, 맨 아래의 '내 가게로 해 보기' 띠, 바닥글.
import { useEffect, useRef, type ReactNode } from 'react'
import { ABOUT_PATH, APP_PATH, type LoginConfig } from './api'
import { AccountBox, LoginButtons } from './Auth'
import { watchScroll } from './scrub'

// 이 화면들에 공통으로 넘기는 것
//   login       서버가 쓰는 로그인 방법. 보기 전용 시연 사이트면 null
//   canEnter    분석 화면에 들어갈 수 있는 사람인가 (로그인했거나, 로그인을 안 쓰는 서버) → '분석하러 가기' 버튼
//   contactUrl  '사전 신청·문의' 버튼이 여는 주소 (서버 설정). 없으면 버튼을 보여 주지 않는다
export type SiteProps = { login: LoginConfig | null; canEnter: boolean; contactUrl: string | null }

// 화살표가 달린 알약 버튼. dark = 잉크색 바탕(가장 중요한 버튼), onDark = 어두운 띠 위에 놓는 흰 버튼, 둘 다 아니면 회색 바탕
export function ArrowLink({ href, children, dark = false, onDark = false }: { href: string; children: ReactNode; dark?: boolean; onDark?: boolean }) {
  const tone = dark ? 'bg-ink-900 text-white hover:bg-ink-hover' : onDark ? 'bg-white text-ink-900 hover:bg-pill' : 'bg-pill text-ink-900 hover:bg-line'
  return (
    <a href={href} className={`btn-pill group ${tone}`}>
      {children}
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-full transition-transform duration-200 group-hover:translate-x-1 ${dark ? 'bg-white text-ink-900' : 'bg-ink-900 text-white'}`}
        aria-hidden
      >
        →
      </span>
    </a>
  )
}

function ContactLink({ url, className }: { url: string; className: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer" className={className}>
      사전 신청·문의
    </a>
  )
}

// 머리말: 맨 위에서는 바탕 없이 화면과 이어지고, 스크롤하면 흰 바탕과 선이 생긴다. here = 지금 보는 화면
export function SiteHeader({ login, canEnter, contactUrl, here }: SiteProps & { here: 'home' | 'about' }) {
  const bar = useRef<HTMLElement>(null)
  useEffect(() => watchScroll(() => bar.current?.toggleAttribute('data-scrolled', window.scrollY >= 8)), [])
  const tab = (path: string, text: string, on: boolean) => (
    <a href={path} className={on ? 'font-semibold text-ink-900' : 'hover:text-ink-900'} aria-current={on ? 'page' : undefined}>
      {text}
    </a>
  )
  return (
    <header ref={bar} className="sticky top-0 z-30 border-b border-transparent bg-transparent transition-colors duration-300 data-scrolled:border-line data-scrolled:bg-page">
      <div className="mx-auto flex min-h-16 max-w-content flex-wrap items-center justify-between gap-x-8 gap-y-2 px-5 py-2 md:px-10">
        <div className="flex items-center gap-x-8">
          <a href="/" className="text-xl font-[800] tracking-[-0.05em]" aria-label="내일몇개 첫 화면">
            내일몇개
          </a>
          <nav className="flex items-center gap-x-6 text-base text-ink-700">
            {tab('/', '홈', here === 'home')}
            {tab(ABOUT_PATH, '소개', here === 'about')}
          </nav>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {canEnter && (
            <a href={APP_PATH} className="btn-md btn-primary">
              분석하러 가기
            </a>
          )}
          {login ? <AccountBox login={login} /> : !canEnter && contactUrl && <ContactLink url={contactUrl} className="btn-md btn-primary" />}
        </div>
      </div>
    </header>
  )
}

// 맨 아래의 어두운 띠: 들어갈 수 있으면 '분석하러 가기', 아니면 로그인(또는 문의)
export function JoinBand({ login, canEnter, contactUrl, title = '내 가게로 해 보기' }: SiteProps & { title?: string }) {
  return (
    <section className="bg-ink-900 text-white">
      <div className="mx-auto max-w-content px-5 py-28 text-center md:px-10">
        <h2 className="whitespace-pre-line text-title">{title}</h2>
        {canEnter ? (
          <div className="mt-10 flex justify-center">
            <ArrowLink href={APP_PATH} onDark>
              분석하러 가기
            </ArrowLink>
          </div>
        ) : login ? (
          <>
            <p className="mx-auto mt-4 mb-8 max-w-xl text-lg text-white/75">로그인하고 판매 기록 파일을 올리면 됩니다. 올린 자료는 본인만 볼 수 있어요.</p>
            <div className="flex justify-center">
              <LoginButtons login={login} />
            </div>
          </>
        ) : (
          <>
            <p className="mx-auto mt-4 max-w-xl text-lg text-white/75">
              {contactUrl ? '내 가게 판매 기록으로 써 보고 싶다면 신청해 주세요.' : '지금은 예시 매장만 볼 수 있는 시연용 화면입니다.'}
            </p>
            {contactUrl && (
              <div className="mt-8 flex justify-center">
                <ContactLink url={contactUrl} className="btn-xl bg-white text-ink-900 hover:bg-surface" />
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

export function SiteFooter({ contactUrl }: { contactUrl: string | null }) {
  return (
    <footer className="border-t border-line bg-page">
      <div className="mx-auto grid max-w-content gap-8 px-5 py-12 text-sm text-ink-700 md:grid-cols-[1fr_1.6fr] md:px-10">
        <div>
          <p className="text-base font-[800] tracking-[-0.05em] text-ink-900">내일몇개</p>
          <p className="mt-2 leading-relaxed">팀 PREDICTOR · 2026 연세 캠퍼스타운 AI 스타트업 해커톤 출품작</p>
          {contactUrl && <ContactLink url={contactUrl} className="mt-3 inline-block font-medium text-ink-900 underline underline-offset-4" />}
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
  )
}
