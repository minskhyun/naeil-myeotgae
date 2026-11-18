// 구글 로그인: 버튼(GoogleButton)과 머리말의 내 계정 칸(AccountBox).
// 흐름: 구글 버튼을 누르면 구글이 ID 토큰을 준다 → 서버(/api/auth/google)가 확인하고 로그인 쿠키를 준다.
// 서버 쪽 규칙은 backend/app/auth.py.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from './api'
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
            } catch (e) {
              setError((e as Error).message)
            }
          },
        })
        window.google.accounts.id.renderButton(box.current, { theme: 'outline', size: 'medium', text: 'signin_with', locale: 'ko' })
      })
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [clientId, qc])

  return (
    <div>
      <div ref={box} className="w-fit" />
      {error && <p className="mt-1 text-xs text-up">{error}</p>}
    </div>
  )
}

// 머리말 오른쪽: 로그인 전에는 구글 버튼, 로그인 뒤에는 이름과 로그아웃
export function AccountBox({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const me = useMe(true)
  if (me.isLoading) return null
  if (!me.data) return <GoogleButton clientId={clientId} />

  const logout = async () => {
    await api.logout()
    window.google?.accounts.id.disableAutoSelect() // 다음에 자동으로 다시 로그인되지 않게
    await qc.invalidateQueries()
  }
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-muted" title={me.data.email}>
        {me.data.name}
        {me.data.is_admin && ' (관리자)'}
      </span>
      <button onClick={logout} className="underline underline-offset-4 hover:text-accent">
        로그아웃
      </button>
    </div>
  )
}
