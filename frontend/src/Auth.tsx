// 로그인: 버튼 하나(LoginButton)와 머리말의 내 계정 칸(AccountBox).
// 화면에는 '로그인' 버튼 하나만 보인다. 누르면 창이 떠서 어느 계정(구글 · 카카오)으로 로그인할지 고른다.
// 구글:  버튼을 누르면 구글이 ID 토큰을 준다 → 서버(/api/auth/google)가 확인하고 로그인 쿠키를 준다.
// 카카오: 버튼은 그냥 링크다 → 서버(/api/auth/kakao/start)가 카카오 로그인 화면으로 보내고, 끝나면 첫 화면으로 돌아온다.
// 서버 쪽 규칙은 backend/app/auth.py.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, APP_PATH, PRIVACY_PATH, TERMS_PATH, type LoginConfig } from './api'
import { Modal } from './Modal'
import { useMe } from './useMe'

// 구글이 주는 로그인 스크립트(window.google)에서 우리가 쓰는 부분만
type GoogleId = {
  initialize: (options: { client_id: string; callback: (response: { credential: string }) => void }) => void
  renderButton: (parent: HTMLElement, options: Record<string, string | number>) => void
  disableAutoSelect: () => void
}
declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } }
  }
}

const SCRIPT = 'https://accounts.google.com/gsi/client'
const BUTTON_WIDTH = 280 // 로그인 창 안의 두 버튼(구글 · 카카오)을 같은 폭으로
let loading: Promise<void> | null = null

// 구글 로그인 스크립트를 한 번만 불러온다
function loadGoogle(): Promise<void> {
  loading ??= new Promise((resolve, reject) => {
    const tag = document.createElement('script')
    tag.src = SCRIPT
    tag.async = true
    tag.onload = () => resolve()
    tag.onerror = () => {
      loading = null
      reject(new Error('구글 로그인 스크립트를 불러오지 못했습니다.'))
    }
    document.head.appendChild(tag)
  })
  return loading
}

// '구글로 로그인' 버튼. 모양은 구글이 그린다 (구글 규정)
export function GoogleButton({ clientId }: { clientId: string }) {
  const box = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    loadGoogle()
      .then(() => {
        if (!alive || !box.current || !window.google) return
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }) => {
            try {
              await api.loginGoogle(credential)
              setError(null)
              await qc.invalidateQueries() // 내 정보·매장 목록을 모두 새로 받는다
              window.location.assign(APP_PATH) // 로그인했으면 바로 분석 화면으로 (첫 화면에서도 '분석하러 가기'로 갈 수 있다)
            } catch (e) {
              setError((e as Error).message)
            }
          },
        })
        window.google.accounts.id.renderButton(box.current, { theme: 'outline', size: 'large', text: 'signin_with', width: BUTTON_WIDTH, locale: 'ko' })
      })
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [clientId, qc])

  return (
    <div>
      <div ref={box} className="w-fit" />
      {error && <p className="mt-1 text-xs text-down">{error}</p>}
    </div>
  )
}

// '카카오 로그인' 버튼 (카카오 디자인 지침: 노란 바탕 #FEE500, 검은 말풍선과 글자)
export function KakaoButton() {
  return (
    <a
      href="/api/auth/kakao/start"
      style={{ width: BUTTON_WIDTH }}
      className="inline-flex h-10 items-center justify-center gap-2 rounded bg-[#FEE500] px-3 text-sm font-medium text-black/85 hover:brightness-95"
    >
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path
          fill="currentColor"
          d="M12 3C6.48 3 2 6.58 2 11c0 2.83 1.84 5.31 4.6 6.73l-.98 3.6c-.09.33.28.6.57.41l4.3-2.85c.49.07 1 .11 1.51.11 5.52 0 10-3.58 10-8s-4.48-8-10-8z"
        />
      </svg>
      카카오 로그인
    </a>
  )
}

// '로그인' 버튼 하나. 누르면 창이 떠서 어느 계정으로 로그인할지 고른다 (이 서버가 쓰는 방법만 보여 준다).
//   label · className = 놓이는 자리에 맞춘 버튼의 글과 모양 (머리말은 작은 버튼, 맨 아래 띠는 큰 흰 버튼)
export function LoginButton({ login, label = '로그인', className = 'btn-md btn-primary' }: { login: LoginConfig; label?: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const link = 'font-medium text-ink-700 underline underline-offset-4 hover:text-ink-900'
  return (
    <>
      <button onClick={() => setOpen(true)} className={className}>
        {label}
      </button>
      {open && (
        <Modal label="로그인" onClose={() => setOpen(false)} narrow>
          <div className="text-left text-ink-900">
            <h2 className="text-h2">로그인</h2>
            <p className="mt-2 text-ink-700">어느 계정으로 시작할까요? 비밀번호는 받지 않아요.</p>
            <div className="mt-8 flex flex-col items-center gap-3">
              {login.google && <GoogleButton clientId={login.google} />}
              {login.kakao && <KakaoButton />}
            </div>
            <p className="mt-8 text-sm leading-relaxed text-ink-500">
              처음이면 로그인한 뒤{' '}
              <a href={TERMS_PATH} target="_blank" rel="noreferrer" className={link}>
                이용약관
              </a>
              과{' '}
              <a href={PRIVACY_PATH} target="_blank" rel="noreferrer" className={link}>
                개인정보 수집·이용
              </a>{' '}
              동의를 묻습니다.
            </p>
          </div>
        </Modal>
      )}
    </>
  )
}

// 머리말 오른쪽: 로그인 전에는 '로그인' 버튼, 로그인 뒤에는 이름과 로그아웃
export function AccountBox({ login }: { login: LoginConfig }) {
  const qc = useQueryClient()
  const me = useMe(true)
  if (me.isLoading) return null
  if (!me.data) return <LoginButton login={login} />

  const logout = async () => {
    await api.logout()
    window.google?.accounts.id.disableAutoSelect() // 다음에 자동으로 다시 로그인되지 않게
    await qc.invalidateQueries()
  }
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-ink-700" title={me.data.email ?? '카카오 계정'}>
        {me.data.name}
        {me.data.is_admin && ' (관리자)'}
      </span>
      <button onClick={logout} className="underline underline-offset-4 hover:text-ink-900">
        로그아웃
      </button>
    </div>
  )
}
