// 스크롤에 묶여 나타나는 칸 (스크롤 스크러빙). 칸이 화면 아래에서 올라오는 만큼만 나타나고, 다시 올리면 그만큼 되돌아간다.
// 진행도(0~1)를 요소의 CSS 변수 --p 에 적고, 모양은 index.css가 그 값으로 정한다.
//   0 = 칸의 윗변이 화면 아래 끝에 막 닿았다,  1 = 화면 높이의 35%만큼 올라왔다
// 안에 든 그래프의 움직임(nm-bar 등)은 칸이 절반쯤 보일 때 한 번 시작한다 (nm-in).
//   effect  'rise'  = 떠오르기 (기본)
//           'zoom'  = 올라오며 커지고 둥근 모서리가 펴진다 (첫 화면의 큰 지도)
//           'lines' = 안의 줄(자식 요소)이 하나씩, 흐릿했다가 또렷해지며 떠오른다 (큰 제목. 아래의 Lines)
//   lag(0~1) = 여러 칸이 차례로 나오게 할 때 늦추는 정도
//   as       = 어떤 요소로 그릴지 (제목이면 h2 등)
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react'
import { CountUp } from './CountUp'
import { clamp01, watchScroll } from './scrub'

const RISE = 56 // 떠오르는 거리(px). index.css의 nm-reveal과 같은 값이어야 한다
const CLASS = { rise: 'nm-reveal', zoom: 'nm-zoom', lines: 'nm-lines' }

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
    let p = 0
    return watchScroll(() => {
      const view = window.innerHeight
      const top = el.getBoundingClientRect().top - (effect === 'rise' ? (1 - p) * RISE : 0) // 떠오르기 전의 제자리 (지금 옮겨 놓은 만큼을 뺀다)
      p = clamp01((view - top) / (view * (effect === 'zoom' ? 0.7 : 0.35)) - lag)
      el.style.setProperty('--p', p.toFixed(3))
      if (p > 0.5) el.classList.add('nm-in')
    })
  }, [lag, effect])

  const Tag = as as 'div' // 어떤 요소든 ref와 className을 받는 것은 같다
  return (
    <Tag ref={box as RefObject<HTMLDivElement | null>} className={`${CLASS[effect]} ${className}`}>
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
    const watcher = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        setSeen(true)
        watcher.disconnect()
      },
      { threshold: 0.6 },
    )
    watcher.observe(el)
    return () => watcher.disconnect()
  }, [])
  return <span ref={box}>{seen ? <CountUp to={to} format={format} /> : (format ?? ((v: number) => String(Math.round(v))))(0)}</span>
}
