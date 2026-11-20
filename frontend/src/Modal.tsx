// 화면 위에 뜨는 창 (매장 추가, 판매 입력, 로그인). 바깥을 누르거나 Esc, ✕로 닫는다.
// 어디서 띄우든 문서의 맨 끝(body)에 그린다 → 머리말처럼 층이 따로 있는 곳 안에서 띄워도 화면 전체를 덮는다.
import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

// narrow: 내용이 적은 좁은 창 (로그인)
export function Modal({ label, onClose, children, narrow = false }: { label: string; onClose: () => void; children: ReactNode; narrow?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    const before = document.body.style.overflow
    document.body.style.overflow = 'hidden' // 창이 떠 있는 동안 뒤 화면은 스크롤되지 않게
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = before
    }
  }, [onClose])

  return createPortal(
    <div
      className={`fixed inset-0 z-50 flex justify-center overflow-y-auto bg-ink-900/50 p-3 sm:p-8 ${narrow ? 'items-center' : 'items-start'}`}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-label={label} className={`relative w-full rounded-3xl bg-white shadow-pop ${narrow ? 'max-w-md' : 'max-w-3xl'}`}>
        <button
          onClick={onClose}
          aria-label="닫기"
          className="absolute top-4 right-4 flex h-9 w-9 items-center justify-center rounded-full bg-surface text-lg leading-none text-ink-700 hover:text-ink-900"
        >
          ✕
        </button>
        <div className="px-5 py-6 sm:px-8 sm:py-8">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
