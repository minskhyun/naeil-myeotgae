// 스크롤과 관련된 작은 도구 둘.
//   watchScroll     스크롤(과 창 크기 변화)이 있을 때마다, 화면을 그리기 직전에 등록한 함수들을 한 번씩 부른다.
//                   화면을 다시 그리지 않도록(React 상태를 쓰지 않고) 각 함수가 자기 요소만 고친다. 쓰는 곳: Site.tsx의 머리말
//   useSnapScroll   이 화면이 떠 있는 동안 스크롤이 구역(nm-screen)마다 멈추게 한다 (index.css의 nm-snap). 첫 화면과 소개
import { useEffect } from 'react'

const watchers = new Set<() => void>()
let waiting = false

function tick() {
  if (waiting) return
  waiting = true
  requestAnimationFrame(() => {
    waiting = false
    watchers.forEach((update) => update())
  })
}

// update를 등록하고(바로 한 번 부른다), 등록을 푸는 함수를 돌려준다
export function watchScroll(update: () => void): () => void {
  if (!watchers.size) {
    window.addEventListener('scroll', tick, { passive: true })
    window.addEventListener('resize', tick)
  }
  watchers.add(update)
  update()
  return () => {
    watchers.delete(update)
    if (!watchers.size) {
      window.removeEventListener('scroll', tick)
      window.removeEventListener('resize', tick)
    }
  }
}

// 한 화면에 한 내용: 이 화면이 떠 있는 동안만 html에 nm-snap을 붙인다 (분석 화면처럼 길게 읽는 화면에는 붙이지 않는다)
export function useSnapScroll() {
  useEffect(() => {
    document.documentElement.classList.add('nm-snap')
    return () => document.documentElement.classList.remove('nm-snap')
  }, [])
}
