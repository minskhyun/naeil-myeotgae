// 어떤 화면을 보여 줄지 정한다. 주소는 여섯이다.
//   /        첫 화면 (Landing.tsx): 무엇을 해 주는 서비스인지. 누구나 본다
//   /about   소개 (About.tsx): 어떻게 예측하는지, 예시 매장의 결과와 검증. 누구나 본다
//   /support 고객지원 (Support.tsx): 처음 쓰는 법, 자주 묻는 질문, 문의. 누구나 본다
//   /privacy 개인정보처리방침 (Privacy.tsx), /terms 이용약관 (Terms.tsx). 누구나 본다
//   /app     분석 화면 (Workspace.tsx): 내 매장의 준비표, 매장 추가·관리. 로그인한 사람만 (로그인을 안 쓰는 서버는 누구나)
// 들어갈 수 있는 사람에게는 첫 화면과 소개에 '분석하러 가기' 버튼이 보인다.
// 로그인하지 않았는데 /app 을 열면 첫 화면으로 돌려보낸다.
// 보기 전용 시연 사이트(DEMO_MODE)에서는 누구나 /app 에 들어가 예시 매장의 분석 화면을 본다 (올리기·수정은 없다: viewOnly).
// 처음 로그인한 사람에게는 분석 화면 대신 약관 동의 화면(Consent.tsx)을 먼저 보여 준다.
// 화면 사이는 그냥 링크로 오간다 (주소가 몇 개뿐이라 라우터를 쓰지 않는다). 서버도 이 주소들에서 같은 화면 파일을 준다 (backend/app/main.py).
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { About } from './About'
import { ABOUT_PATH, api, APP_PATH, PRIVACY_PATH, SUPPORT_PATH, TERMS_PATH, type LoginConfig } from './api'
import { Consent } from './Consent'
import { Landing } from './Landing'
import { Privacy } from './Privacy'
import { Support } from './Support'
import { Terms } from './Terms'
import { useMe } from './useMe'
import { Workspace } from './Workspace'

const here = () => window.location.pathname.replace(/\/+$/, '')

export default function App() {
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  // 서버가 쓰는 로그인 방법 (구글·카카오). 둘 다 없으면 null = 로그인을 안 쓰는 서버
  const google = config.data?.google_client_id ?? null
  const kakao = config.data?.kakao_login ?? false
  const login: LoginConfig | null = google || kakao ? { google, kakao } : null
  const me = useMe(!!login)

  const ready = !!config.data && !(login && me.isLoading)
  const demo = !!config.data?.demo_mode
  const canEnter = ready && (demo || !login || !!me.data) // 분석 화면에 들어갈 수 있는가 (시연 사이트는 누구나, 보기만)
  const path = here()
  const wantApp = path === APP_PATH
  // 들어갈 수 없는데 분석 화면 주소를 열었으면 (로그아웃한 직후 포함) 첫 화면으로
  useEffect(() => {
    if (ready && wantApp && !canEnter) window.location.replace('/')
  }, [ready, wantApp, canEnter])

  if (config.error) {
    return (
      <p className="m-8 border-l-4 border-down bg-white px-4 py-3 text-sm">
        백엔드에 연결하지 못했습니다. 프로젝트 맨 위 폴더에서{' '}
        <code className="bg-surface px-1">.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000</code>을 실행하세요.
      </p>
    )
  }
  if (!ready) return null // 누구인지 알기 전에는 아무 화면도 깜빡이지 않게

  if (wantApp) {
    if (!canEnter) return null
    if (demo) return <Workspace login={null} viewOnly />
    return login && me.data && !me.data.agreed ? <Consent /> : <Workspace login={login} />
  }
  // 첫 화면과 소개에 함께 넘기는 것. contactUrl = '사전 신청·문의' 버튼이 여는 주소 (서버 설정 CONTACT_URL)
  const site = { login: demo ? null : login, canEnter, viewOnly: demo, contactUrl: config.data!.contact_url ?? null }
  if (path === ABOUT_PATH) return <About {...site} />
  if (path === SUPPORT_PATH) return <Support {...site} />
  if (path === PRIVACY_PATH) return <Privacy {...site} />
  if (path === TERMS_PATH) return <Terms {...site} />
  return <Landing {...site} />
}
