// 스크롤 스크러빙의 바탕: 스크롤(과 창 크기 변화)이 있을 때마다, 화면을 그리기 직전에 등록한 함수들을 한 번씩 부른다.
// 움직임을 시간이 아니라 스크롤 위치에 묶기 위한 것이다 (내리면 진행하고 올리면 되감긴다).
// 화면을 다시 그리지 않도록(React 상태를 쓰지 않고) 각 함수가 자기 요소의 CSS 변수만 고친다. 쓰는 곳: Reveal.tsx, Landing.tsx.
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

export const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
