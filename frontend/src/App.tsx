// 어떤 화면을 보여 줄지 정한다. 주소가 둘이다.
//   /      첫 화면 (Landing.tsx): 제품 소개와 예시. 누구나 본다. 들어갈 수 있는 사람에게는 '분석하러 가기' 버튼이 보인다
//   /app   분석 화면 (Workspace.tsx): 내 매장의 준비표, 매장 추가·관리. 로그인한 사람만 (로그인을 안 쓰는 서버는 누구나)
// 로그인하지 않았거나 보기 전용 시연 사이트에서 /app 을 열면 첫 화면으로 돌려보낸다.
// 화면 사이는 그냥 링크로 오간다 (주소가 둘뿐이라 라우터를 쓰지 않는다). 서버도 /app 에서 같은 화면 파일을 준다 (backend/app/main.py).
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, APP_PATH, type LoginConfig } from './api'
import { Landing } from './Landing'
import { useMe } from './useMe'
import { Workspace } from './Workspace'

const onAppPage = () => window.location.pathname.replace(/\/+$/, '') === APP_PATH

export default function App() {
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  // 서버가 쓰는 로그인 방법 (구글·카카오). 둘 다 없으면 null = 로그인을 안 쓰는 서버
  const google = config.data?.google_client_id ?? null
  const kakao = config.data?.kakao_login ?? false
  const login: LoginConfig | null = google || kakao ? { google, kakao } : null
  const me = useMe(!!login)

  const ready = !!config.data && !(login && me.isLoading)
  const demo = !!config.data?.demo_mode
  const canEnter = ready && !demo && (!login || !!me.data) // 분석 화면에 들어갈 수 있는가
  const wantApp = onAppPage()
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

  const contactUrl = config.data!.contact_url ?? null // '사전 신청·문의' 버튼이 여는 주소 (서버 설정 CONTACT_URL)
  if (wantApp) return canEnter ? <Workspace login={login} /> : null
  return <Landing login={demo ? null : login} contactUrl={contactUrl} canEnter={canEnter} />
}
