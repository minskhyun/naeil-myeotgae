// 스크롤해서 화면에 들어오면 나타나는 칸. 처음에는 살짝 아래에서 투명하게 기다리다가, 들어오는 순간 올라오며 나타난다 (한 번만).
// 모양과 움직임은 index.css의 nm-reveal. 안에 든 그래프의 움직임도 그때 함께 시작한다.
// delay(ms) = 여러 칸이 차례로 나오게 할 때 늦추는 시간.
import { useEffect, useRef, useState, type ReactNode } from 'react'

export function Reveal({ children, className = '', delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const box = useRef<HTMLDivElement>(null)
  // 화면에 들어왔는가. 들어왔는지 알 방법이 없는 브라우저에서는 처음부터 보여 준다
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    const el = box.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const watcher = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        setSeen(true)
        watcher.disconnect()
      },
      { threshold: 0.08, rootMargin: '0px 0px -6% 0px' }, // 칸의 윗부분이 화면 아래쪽에 조금 들어오면
    )
    watcher.observe(el)
    return () => watcher.disconnect()
  }, [])

  return (
    <div ref={box} className={`nm-reveal ${seen ? 'nm-in' : ''} ${className}`} style={delay ? { transitionDelay: `${delay}ms` } : undefined}>
      {children}
    </div>
  )
}
