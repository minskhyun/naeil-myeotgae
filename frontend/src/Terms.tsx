// 이용약관 ('/terms'). 길게 읽는 글이라 화면마다 멈추지 않는다.
// ★ 여기 적은 내용은 서비스가 실제로 하는 일과 같아야 한다 (매장 수 제한은 backend/app/auth.py의 MAX_STORES, 삭제는 main.delete_my_store · delete_me).
// ★ 법률 검토를 받은 글이 아니다. 유료로 바꾸기 전에는 유료 약관 · 환불 정책이 따로 필요하다.
import { type ReactNode } from 'react'
import { PRIVACY_PATH } from './api'
import { SiteFooter, SiteHeader, type SiteProps } from './Site'

const EFFECTIVE = '2026년 11월 20일'

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-14">
      <h2 className="text-h2">{title}</h2>
      <div className="mt-5 space-y-4 leading-relaxed text-ink-700">{children}</div>
    </section>
  )
}

export function Terms({ login, contactUrl, canEnter, viewOnly }: SiteProps) {
  return (
    <div>
      <SiteHeader login={login} canEnter={canEnter} viewOnly={viewOnly} contactUrl={contactUrl} here="none" />
      <main className="mx-auto max-w-3xl px-5 pt-16 pb-28 md:px-10">
        <h1 className="text-title">이용약관</h1>
        <p className="mt-5 text-lg leading-8 text-ink-700">내일몇개(운영: 팀 PREDICTOR)를 쓰는 데 적용되는 약속입니다. 지금은 무료 시연 단계입니다.</p>
        <p className="mt-3 text-sm text-ink-500">시행일 {EFFECTIVE}</p>

        <Part title="1. 서비스가 하는 일">
          <p>올린 판매 기록과 가게 주변의 정보(날씨, 근처 학교 일정, 행사, 소식)를 바탕으로 다음 날 메뉴별 예상 판매량과 준비할 개수를 알려 드립니다.</p>
          <p>지금은 무료 시연 단계라서 기능이 바뀌거나 잠시 멈출 수 있습니다. 서비스를 끝내게 되면 이 화면과 첫 화면에 미리 알립니다.</p>
        </Part>

        <Part title="2. 예측은 참고용입니다">
          <p>
            예측은 지난 기록을 바탕으로 한 추정이며 <strong className="font-semibold text-ink-900">결과를 보장하지 않습니다.</strong> 얼마나 준비할지는 사장님이 정하며, 그
            결과(남은 재고, 품절 등)에 대해 내일몇개가 책임지지 않습니다.
          </p>
          <p>대신 가게마다 지난 기록에서 예측이 얼마나 맞았는지를 숨기지 않고 보여 드립니다.</p>
        </Part>

        <Part title="3. 계정과 매장">
          <ul className="list-disc space-y-2 pl-5">
            <li>구글 또는 카카오 계정으로 로그인합니다. 비밀번호는 받지 않습니다.</li>
            <li>한 계정에서 매장을 10개까지 만들 수 있습니다.</li>
            <li>언제든 매장 관리의 '내 계정'에서 탈퇴할 수 있고, 탈퇴하면 계정과 모든 매장의 자료가 지워집니다.</li>
          </ul>
        </Part>

        <Part title="4. 올린 자료의 권리와 쓰임">
          <ul className="list-disc space-y-2 pl-5">
            <li>올린 판매 기록의 권리는 올린 분(사장님)에게 있습니다.</li>
            <li>판매 기록은 그 가게의 예측을 만드는 데만 씁니다. 다른 가게에 보여 주지 않습니다.</li>
            <li>매장을 지우거나 탈퇴하면 그 자료를 서버에서 지웁니다.</li>
            <li>
              어떤 정보를 받고 어디로 보내는지는{' '}
              <a href={PRIVACY_PATH} className="font-semibold text-ink-900 underline underline-offset-4">
                개인정보처리방침
              </a>
              에 적었습니다.
            </li>
          </ul>
        </Part>

        <Part title="5. 하지 말아야 할 일">
          <ul className="list-disc space-y-2 pl-5">
            <li>내 것이 아닌 가게의 자료를 올리는 일</li>
            <li>가게 손님의 개인정보(전화번호, 회원 번호, 카드 정보 등)가 든 자료를 일부러 올리는 일</li>
            <li>서비스를 망가뜨리거나 다른 사람의 이용을 막는 일</li>
          </ul>
          <p>이런 일이 확인되면 이용을 막거나 자료를 지울 수 있습니다.</p>
        </Part>

        <Part title="6. 약관이 바뀌면">
          <p>이 화면에 바뀐 내용과 시행일을 적어 알립니다. 이용자에게 불리하게 바뀌는 내용은 시행 전에 미리 알립니다.</p>
        </Part>
      </main>
      <SiteFooter contactUrl={contactUrl} />
    </div>
  )
}
