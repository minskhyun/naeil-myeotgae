// 숫자가 0에서 올라가며 나타난다 (준비표의 준비 개수, 분석 끝 화면의 요약 숫자)
import { useEffect, useState } from 'react'

export function CountUp({ to, format = (v) => String(Math.round(v)) }: { to: number; format?: (v: number) => string }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    let step = 0
    const timer = window.setInterval(() => {
      step += 1
      setV(to * (1 - (1 - step / 30) ** 3)) // 처음엔 빠르게, 끝에서 천천히
      if (step >= 30) window.clearInterval(timer)
    }, 30)
    return () => window.clearInterval(timer)
  }, [to])
  return <>{format(v)}</>
}
