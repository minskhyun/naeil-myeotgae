// 어떤 화면을 보여 줄지 정한다.
//   로그인 전, 또는 보기 전용 시연 사이트  → Landing.tsx   (예시 매장으로 제품 소개: 준비표 · 주변 정보 · 얼마나 맞나)
//   로그인한 뒤                          → Workspace.tsx (내 매장만: 분석 화면, 매장 추가, 매장 관리)
//   로그인을 안 쓰는 서버(혼자 쓰는 노트북) → Workspace.tsx (모든 매장)
import { useQuery } from '@tanstack/react-query'
import { api, type LoginConfig } from './api'
import { Landing } from './Landing'
import { useMe } from './useMe'
import { Workspace } from './Workspace'

export default function App() {
  const config = useQuery({ queryKey: ['config'], queryFn: api.config })
  // 서버가 쓰는 로그인 방법 (구글·카카오). 둘 다 없으면 null = 로그인을 안 쓰는 서버
  const google = config.data?.google_client_id ?? null
  const kakao = config.data?.kakao_login ?? false
  const login: LoginConfig | null = google || kakao ? { google, kakao } : null
  const me = useMe(!!login)

  if (config.error) {
    return (
      <p className="m-8 border-l-4 border-up bg-sheet px-4 py-3 text-sm">
        백엔드에 연결하지 못했습니다. 프로젝트 맨 위 폴더에서{' '}
        <code className="bg-paper px-1">.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000</code>을 실행하세요.
      </p>
    )
  }
  if (!config.data || (login && me.isLoading)) return null // 누구인지 알기 전에는 아무 화면도 깜빡이지 않게

  const contactUrl = config.data.contact_url ?? null // '사전 신청·문의' 버튼이 여는 주소 (서버 설정 CONTACT_URL)
  if (config.data.demo_mode) return <Landing login={null} contactUrl={contactUrl} />
  if (login && !me.data) return <Landing login={login} contactUrl={contactUrl} />
  return <Workspace login={login} />
}
