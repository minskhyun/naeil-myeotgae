// 처음 로그인했을 때 한 번 묻는 화면: 이용약관 · 개인정보 수집·이용 동의. 둘 다 동의해야 분석 화면에 들어간다.
// 서버도 동의 전에는 매장을 만들거나 고치지 못하게 한다 (backend/app/auth.py의 check_agreed).
// 동의하지 않고 나가면 방금 만들어진 계정을 지운다 (동의 없이 계정 정보를 남겨 두지 않는다).
// 광고·소식을 보내지 않으므로 마케팅 수신 동의는 받지 않는다 (보내게 되면 그때 따로 묻는다).
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, PRIVACY_PATH, TERMS_PATH } from './api'
import { Logo } from './Logo'

const ITEMS = [
  { id: 'terms', text: '이용약관에 동의합니다', note: '예측은 참고용이며 결과를 보장하지 않습니다.', href: TERMS_PATH },
  { id: 'privacy', text: '개인정보 수집·이용에 동의합니다', note: '계정 정보, 매장 정보, 판매 기록을 예측을 만드는 데 씁니다.', href: PRIVACY_PATH },
] as const

export function Consent() {
  const qc = useQueryClient()
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const all = ITEMS.every((it) => checked[it.id])

  const act = async (work: () => Promise<unknown>, then: () => unknown) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      await then()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  const agree = () => act(api.agree, () => qc.invalidateQueries({ queryKey: ['me'] }))
  const leave = () =>
    act(api.deleteMe, () => {
      window.google?.accounts.id.disableAutoSelect() // 다음에 자동으로 다시 로그인되지 않게
      window.location.assign('/')
    })

  return (
    <div className="min-h-screen bg-page">
      <header className="mx-auto flex h-16 max-w-content items-center px-5 md:px-10">
        <a href="/" aria-label="내일몇개 첫 화면">
          <Logo />
        </a>
      </header>
      <main className="mx-auto max-w-xl px-5 pt-10 pb-24 md:pt-20">
        <h1 className="nm-enter text-title">
          <span>시작하기 전에</span>
          <span style={{ animationDelay: '220ms' }}>확인해 주세요</span>
        </h1>
        <p className="mt-5 text-lg leading-8 text-ink-700">아래 두 가지에 동의하면 내 가게의 준비표를 만들 수 있어요.</p>

        <ul className="mt-10 space-y-3">
          {ITEMS.map((it) => (
            <li key={it.id} className="flex items-start gap-4 rounded-3xl bg-white px-6 py-5">
              <input
                id={it.id}
                type="checkbox"
                checked={!!checked[it.id]}
                onChange={(e) => setChecked({ ...checked, [it.id]: e.target.checked })}
                className="mt-1 h-5 w-5 shrink-0 accent-ink-900"
              />
              <div className="min-w-0 flex-1">
                <label htmlFor={it.id} className="cursor-pointer font-semibold">
                  {it.text} <span className="font-normal text-ink-500">(필수)</span>
                </label>
                <p className="mt-1 text-sm text-ink-700">{it.note}</p>
              </div>
              <a href={it.href} target="_blank" rel="noreferrer" className="shrink-0 text-sm font-medium underline underline-offset-4 hover:text-ink-900">
                전문 보기
              </a>
            </li>
          ))}
        </ul>

        {error && <p className="mt-6 rounded-lg bg-down-soft px-4 py-3 text-sm font-medium text-down">{error}</p>}
        <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
          <button onClick={agree} disabled={!all || busy} className="btn-xl btn-primary disabled:opacity-40">
            동의하고 시작하기
          </button>
          <button onClick={leave} disabled={busy} className="text-sm text-ink-700 underline underline-offset-4 hover:text-ink-900 disabled:opacity-40">
            동의하지 않고 나가기
          </button>
        </div>
        <p className="mt-4 text-sm text-ink-500">동의하지 않고 나가면 방금 만들어진 계정 정보는 바로 지워집니다.</p>
      </main>
    </div>
  )
}
