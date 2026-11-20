// 스크롤에 묶여 나타나는 칸 (스크롤 스크러빙). 칸이 화면 아래에서 올라오는 만큼만 떠오르고, 다시 올리면 그만큼 가라앉는다.
// 진행도(0~1)를 요소의 CSS 변수 --p 에 적고, 모양은 index.css의 nm-reveal이 그 값으로 정한다.
//   0 = 칸의 윗변이 화면 아래 끝에 막 닿았다,  1 = 화면 높이의 35%만큼 올라왔다
// 안에 든 그래프의 움직임(nm-bar 등)은 칸이 절반쯤 보일 때 한 번 시작한다 (nm-in).
// lag(0~1) = 여러 칸이 차례로 나오게 할 때 늦추는 정도.
// effect: 'rise' = 떠오르기(기본), 'zoom' = 올라오며 커지고 둥근 모서리가 펴진다 (첫 화면의 큰 지도).
import { useEffect, useRef, type ReactNode } from 'react'
import { clamp01, watchScroll } from './scrub'

const RISE = 56 // 떠오르는 거리(px). index.css의 nm-reveal과 같은 값이어야 한다

export function Reveal({ children, className = '', lag = 0, effect = 'rise' }: {
  children: ReactNode
  className?: string
  lag?: number
  effect?: 'rise' | 'zoom'
}) {
  const box = useRef<HTMLDivElement>(null)

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

  return (
    <div ref={box} className={`${effect === 'zoom' ? 'nm-zoom' : 'nm-reveal'} ${className}`}>
      {children}
    </div>
  )
}
