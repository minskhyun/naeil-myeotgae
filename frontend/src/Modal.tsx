// 화면 위에 뜨는 창 (매장 추가, 매장 관리). 바깥을 누르거나 Esc, ✕로 닫는다.
import { useEffect, type ReactNode } from 'react'

export function Modal({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-3 sm:p-8"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-label={label} className="relative w-full max-w-3xl rounded-3xl bg-sheet shadow-2xl">
        <button
          onClick={onClose}
          aria-label="닫기"
          className="absolute top-4 right-4 flex h-9 w-9 items-center justify-center rounded-full bg-paper text-lg leading-none text-muted hover:text-ink"
        >
          ✕
        </button>
        <div className="px-5 py-6 sm:px-8 sm:py-8">{children}</div>
      </div>
    </div>
  )
}
