// 로고: 표시(마주 보는 두 꺾쇠 사이의 주황 점) + 글자 '내일몇개'. 머리말 · 사이드바 · 분석 과정 화면 · 바닥글이 같이 쓴다.
//   꺾쇠는 둘레의 글자색을 따라가고(currentColor), 점은 포인트 색이다. 같은 그림이 public/favicon.svg에도 있다.
//   small = 바닥글처럼 작게 쓸 때
export function LogoMark({ className = 'h-6 w-6' }: { className?: string }) {
  return (
    <svg viewBox="0 0 1024 1024" fill="none" className={`shrink-0 ${className}`} aria-hidden>
      <path d="M290 153H870V751M153 273V870H734" stroke="currentColor" strokeWidth="85" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="512" cy="512" r="145" className="fill-point" />
    </svg>
  )
}

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <span className={`inline-flex items-center font-[800] tracking-[-0.05em] ${small ? 'gap-1.5 text-base' : 'gap-2 text-xl'}`}>
      <LogoMark className={small ? 'h-5 w-5' : 'h-7 w-7'} />
      내일몇개
    </span>
  )
}
