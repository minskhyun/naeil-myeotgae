// 화면에 들어올 때 나타나는 칸. 첫 화면과 소개는 스크롤이 구역마다 멈추므로(index.css의 nm-snap),
// 구역이 화면에 들어오는 순간 그 안의 것들이 한 번 차례로 나타난다. 모양과 움직임은 index.css.
//   effect  'rise'  = 조금 아래에서 떠오르기 (기본)
//           'zoom'  = 조금 작았다가 제 크기로 펴진다 (첫 화면의 큰 지도)
//           'lines' = 안의 줄(자식 요소)이 하나씩, 흐릿했다가 또렷해지며 떠오른다 (큰 제목. 아래의 Lines)
//   lag(0~1) = 같은 구역의 칸들이 차례로 나오게 늦추는 정도 (1 = 1.2초)
//   as       = 어떤 요소로 그릴지 (제목이면 h2 등)
// 안에 든 그래프의 움직임(nm-bar 등)도 나타날 때(nm-in) 함께 시작한다.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react'
import { CountUp } from './CountUp'

const CLASS = { rise: 'nm-reveal', zoom: 'nm-zoom', lines: 'nm-lines' }

// 요소가 화면에 들어오면 한 번 알려 준다 (알 방법이 없는 브라우저에서는 바로)
function onceSeen(el: Element, seen: () => void, threshold: number) {
  if (typeof IntersectionObserver === 'undefined') {
    seen()
    return () => {}
  }
  const watcher = new IntersectionObserver(
    ([entry]) => {
      if (!entry.isIntersecting) return
      seen()
      watcher.disconnect()
    },
    { threshold },
  )
  watcher.observe(el)
  return () => watcher.disconnect()
}

export function Reveal({ children, className = '', lag = 0, effect = 'rise', as = 'div' }: {
  children: ReactNode
  className?: string
  lag?: number
  effect?: 'rise' | 'zoom' | 'lines'
  as?: 'div' | 'h1' | 'h2' | 'h3' | 'p' | 'li'
}) {
  const box = useRef<HTMLElement>(null)
  useEffect(() => {
    const el = box.current
    if (!el) return
    return onceSeen(el, () => el.classList.add('nm-in'), 0.12)
  }, [])

  const Tag = as as 'div' // 어떤 요소든 ref와 className을 받는 것은 같다
  return (
    <Tag ref={box as RefObject<HTMLDivElement | null>} className={`${CLASS[effect]} ${className}`} style={lag ? ({ '--d': `${Math.round(lag * 1200)}ms` } as CSSProperties) : undefined}>
      {children}
    </Tag>
  )
}

// 줄마다 차례로 떠오르는 글. text의 줄바꿈(\n)마다 한 줄이다. 큰 제목에 쓴다
export function Lines({ text, className = '', as = 'h2', lag = 0 }: { text: string; className?: string; as?: 'h1' | 'h2' | 'h3' | 'p'; lag?: number }) {
  return (
    <Reveal effect="lines" as={as} className={className} lag={lag}>
      {text.split('\n').map((line, i) => (
        <span key={i} style={{ '--i': i } as CSSProperties}>
          {line}
        </span>
      ))}
    </Reveal>
  )
}

// 화면에 들어오면 0에서 올라가는 숫자 (들어오기 전에는 0)
export function CountWhenSeen({ to, format }: { to: number; format?: (v: number) => string }) {
  const box = useRef<HTMLSpanElement>(null)
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const el = box.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    return onceSeen(el, () => setSeen(true), 0.6)
  }, [])
  return <span ref={box}>{seen ? <CountUp to={to} format={format} /> : (format ?? ((v: number) => String(Math.round(v))))(0)}</span>
}
