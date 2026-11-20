// 개인정보처리방침 ('/privacy'). 길게 읽는 글이라 화면마다 멈추지 않는다 (useSnapScroll을 쓰지 않는다).
// ★ 여기 적은 내용은 코드가 실제로 하는 일과 같아야 한다. 아래가 바뀌면 이 글도 고친다.
//   - 저장하는 계정 정보: backend/app/auth.py의 users 표 (provider, subject, email, name, picture), 로그인 유지 SESSION_DAYS
//   - 올린 파일·직접 적은 판매: backend/app/main.py의 UPLOADS (필요한 열만 남긴 pos.csv: _keep_upload), 매장을 지우거나(delete_my_store) 탈퇴하면(delete_me) 지운다
//   - 외부 AI로 보내는 것: ml/llm.py (제공자), agent/relevance.py · agent/events.py · ml/alerts.py (보내는 내용)
//   - 그 밖의 외부 요청: agent/geocode.py · agent/naver.py · backend/collectors
// ★ 정식으로 공개하기 전에 개인정보 보호책임자의 이름과 연락처를 채워야 한다 (지금은 팀 이름과 문의 창구만 적었다).
import { type ReactNode } from 'react'
import { SUPPORT_PATH } from './api'
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

// 표: 첫 줄은 머리글. 좁은 화면에서는 옆으로 밀어 본다
function Table({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-3xl bg-white px-6 py-2">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead>
          <tr className="border-b border-line text-ink-500">
            {head.map((h) => (
              <th key={h} className="py-3 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r[0]} className="align-top">
              {r.map((cell, i) => (
                <td key={i} className={`py-3 pr-4 ${i === 0 ? 'font-semibold text-ink-900' : ''}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Privacy({ login, contactUrl, canEnter }: SiteProps) {
  return (
    <div>
      <SiteHeader login={login} canEnter={canEnter} contactUrl={contactUrl} here="none" />
      <main className="mx-auto max-w-3xl px-5 pt-16 pb-28 md:px-10">
        <h1 className="text-title">개인정보처리방침</h1>
        <p className="mt-5 text-lg leading-8 text-ink-700">
          내일몇개(운영: 팀 PREDICTOR)가 어떤 정보를 받아 어디에 쓰고, 어디로 보내며, 언제 지우는지 적었습니다. 지금은 무료 시연 단계이며, 공개된 시연 사이트는
          보기 전용이라 로그인과 파일 올리기를 받지 않습니다.
        </p>
        <p className="mt-3 text-sm text-ink-500">시행일 {EFFECTIVE}</p>

        <Part title="1. 받는 정보와 쓰는 곳">
          <Table
            head={['정보', '내용', '쓰는 곳']}
            rows={[
              ['계정', '구글·카카오가 알려 주는 계정 번호, 이름(별명), 이메일(제공된 경우), 프로필 사진 주소', '로그인, 내 매장을 나만 보게 하기'],
              ['매장', '매장 이름, 주소와 그 좌표, 닫는 시간', '날씨·근처 행사 같은 주변 정보 찾기, 화면 표시'],
              ['판매 기록', '올린 판매 기록 파일에서 남긴 열(날짜·메뉴·수량·시각·금액), 직접 적은 판매 수량, 이를 정리한 기록과 예측 결과', '내일 판매 예측과 준비표 만들기'],
              ['로그인 상태', '로그인을 유지하는 쿠키 하나 (30일 뒤 만료)', '다시 로그인하지 않게 하기'],
            ]}
          />
          <p>비밀번호는 받지 않습니다. 광고나 방문 분석을 위한 쿠키는 쓰지 않습니다.</p>
        </Part>

        <Part title="2. 손님 정보는 받지 않습니다">
          <p>
            예측에는 날짜, 메뉴 이름, 수량(있으면 시각과 금액)만 씁니다. 올린 파일은 서버가 읽자마자{' '}
            <strong className="font-semibold text-ink-900">이 열들만 남겨 보관하고, 나머지 열과 원본 파일은 저장하지 않습니다.</strong> 그래서 적립 전화번호·회원
            번호·카드 정보처럼 가게 손님의 정보가 든 열은 서버에 남지 않습니다.
          </p>
          <p>다만 메뉴 이름 칸에 손님 정보를 적어 둔 파일까지 가려내지는 못합니다. 그런 파일은 올리지 말아 주세요.</p>
        </Part>

        <Part title="3. 보관 기간과 지우기">
          <ul className="list-disc space-y-2 pl-5">
            <li>매장 관리에서 매장을 지우면 그 매장의 올린 파일, 직접 적은 판매, 정리한 기록, 예측 결과가 서버에서 바로 함께 지워집니다.</li>
            <li>계정 정보는 탈퇴할 때까지 보관합니다. 매장 관리의 '내 계정'에서 탈퇴하면 계정과 모든 매장의 자료가 바로 지워집니다.</li>
            <li>올린 판매 기록은 그 가게의 예측에만 씁니다. 다른 가게에 보여 주지 않습니다.</li>
          </ul>
        </Part>

        <Part title="4. 처리를 맡기는 곳과 나라 밖으로 나가는 정보">
          <p>예측을 만들려면 아래 업체의 서비스를 거칩니다. 판매 수량 자체(날짜별 판매 기록)는 외부 AI로 보내지 않습니다.</p>
          <Table
            head={['받는 곳 (나라)', '넘어가는 정보', '목적', '언제 · 어떻게']}
            rows={[
              ['Anthropic (미국)', '가게 이름과 위치, 메뉴 이름, 예측한 숫자, 주변에서 모은 기사·행사 글', '외부 AI(Claude)로 글을 읽고 주의할 소식을 쓰기', '분석을 실행할 때 암호화된 통신으로 전송'],
              ['Render (미국)', '위 1번의 모든 정보', '서비스 서버 운영(호스팅)', '서비스를 쓰는 동안 서버에 저장'],
              ['구글 · 카카오', '로그인 요청', '계정 확인', '로그인할 때'],
            ]}
          />
          <p>
            주변 정보를 찾을 때는 가게 주소·좌표와 메뉴 이름이 검색어로 나갑니다. 주소를 좌표로 바꾸고 주변 시설을 찾는 데 카카오(없으면 오픈스트리트맵), 뉴스·블로그와
            검색량에 네이버, 날씨와 행사에 기상청·공공데이터포털·서울시의 공개 서비스를 씁니다. 이때 계정 정보나 판매 수량은 보내지 않습니다.
          </p>
          <p>
            매장 주소를 비워 두면 주변 정보를 모으지 않고 판매 기록만으로 예측합니다. 나라 밖으로 정보가 나가는 것을 원하지 않으면 서비스를 쓰지 않거나, 탈퇴해 자료를
            지울 수 있습니다.
          </p>
        </Part>

        <Part title="5. 이용자의 권리">
          <p>
            내 정보의 열람, 고치기, 지우기, 처리 멈추기를 언제든 요청할 수 있습니다. 매장 이름·주소·닫는 시간은 매장 관리에서 직접 고치고, 매장과 그 자료도 거기서 직접
            지울 수 있습니다. 탈퇴도 거기의 '내 계정'에서 합니다. 그 밖의 요청은 문의로 알려 주세요.
          </p>
        </Part>

        <Part title="6. 안전하게 다루기 위해 하는 일">
          <ul className="list-disc space-y-2 pl-5">
            <li>내 매장과 그 자료는 로그인한 본인만 볼 수 있게 요청마다 확인합니다.</li>
            <li>로그인 상태를 나타내는 값은 그대로 저장하지 않고 알아볼 수 없게 바꿔 저장합니다.</li>
            <li>외부 서비스의 열쇠(API 키)는 화면이나 코드에 두지 않고 서버 설정에만 둡니다.</li>
          </ul>
        </Part>

        <Part title="7. 문의">
          <p>
            개인정보에 관한 문의와 요청은 팀 PREDICTOR가 받습니다.{' '}
            {contactUrl ? (
              <a href={contactUrl} target="_blank" rel="noreferrer" className="font-semibold text-ink-900 underline underline-offset-4">
                문의 남기기
              </a>
            ) : (
              <a href={`${SUPPORT_PATH}#contact`} className="font-semibold text-ink-900 underline underline-offset-4">
                고객지원
              </a>
            )}
          </p>
          <p>이 방침이 바뀌면 이 화면에 바뀐 내용과 시행일을 적어 알립니다.</p>
        </Part>
      </main>
      <SiteFooter contactUrl={contactUrl} />
    </div>
  )
}
