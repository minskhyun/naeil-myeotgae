// 준비표의 그래프들. 재료는 최근 4주 실제 판매(api.history)와 내일 예측(forecast)이다.
//   DayBars   하루하루 막대 28개 + 내일 예상 막대 하나 (내일과 같은 요일은 진하게). 전체 합계에도, 메뉴 하나에도 쓴다
//   Spark     표의 한 줄에 들어가는 작은 추이선 + 내일 예상 점과 범위
// 색의 뜻은 하나로 통일한다: 회색 = 지나간 실제 판매, 파랑 = 내일 예상. 글자는 색을 입히지 않는다.
// 움직임(막대가 자라고 선이 그려짐)은 index.css의 nm-bar · nm-line · nm-dotin 이 맡는다.
import { useState } from 'react'
import { CountUp } from './CountUp'
import { asDate, count, dayPrefix, dayWord, WEEKDAYS } from './format'

const short = (iso: string) => `${asDate(iso).getMonth() + 1}/${asDate(iso).getDate()}`

// 눈금의 맨 위 값: 가장 큰 값을 보기 좋은 수로 올린다 (690 → 800)
function niceTop(v: number) {
  const unit = 10 ** Math.floor(Math.log10(Math.max(v, 1)))
  return ([1, 1.5, 2, 3, 4, 5, 6, 8, 10].find((m) => m * unit >= v) ?? 10) * unit
}

export type NextDay = { date: string; value: number; lo?: number; hi?: number } // 내일 예상 (lo~hi = 예상 범위)

export function DayBars({ dates, values, next, height = 150 }: {
  dates: string[]
  values: (number | null)[]
  next: NextDay
  height?: number
}) {
  const [hover, setHover] = useState<number | null>(null) // 마우스가 올라간 막대 (dates.length = 내일)
  const top = niceTop(Math.max(next.hi ?? next.value, ...values.map((v) => v ?? 0)))
  const weekday = asDate(next.date).getDay()
  const day = dayWord(next.date) // 오늘 · 내일 · 이날
  const pct = (v: number) => `${(v / top) * 100}%`
  const tipSide = (i: number) => (i < 4 ? 'left-0' : i > dates.length - 4 ? 'right-0' : 'left-1/2 -translate-x-1/2')
  const tip = (i: number, text: string, at: number) => (
    <span
      className={`pointer-events-none absolute z-10 mb-1.5 whitespace-nowrap rounded-lg bg-ink px-2.5 py-1 text-xs font-medium text-white shadow-lg ${tipSide(i)}`}
      style={{ bottom: pct(at) }}
    >
      {text}
    </span>
  )

  return (
    <div>
      <div className="relative pl-9" style={{ height }}>
        {[0, 0.5, 1].map((t) => (
          <div key={t} className="absolute left-9 right-0 border-t border-rule" style={{ bottom: `${t * 100}%` }}>
            <span className="absolute -left-9 -top-2 w-7.5 text-right text-[11px] text-faint tabular-nums">{count(top * t)}</span>
          </div>
        ))}
        <div className="relative flex h-full items-end gap-[2px]" onMouseLeave={() => setHover(null)}>
          {values.map((v, i) => {
            const same = asDate(dates[i]).getDay() === weekday
            return (
              <div key={dates[i]} className={`relative flex h-full flex-1 items-end ${hover === i ? 'bg-ink/5' : ''}`} onMouseEnter={() => setHover(i)}>
                {hover === i && tip(i, `${short(dates[i])} (${WEEKDAYS[asDate(dates[i]).getDay()]}) · ${v === null ? '기록 없음' : `${count(v)}개`}`, v ?? 0)}
                {v === null ? (
                  <span className="mx-auto mb-1 h-1 w-1 rounded-full bg-faint/60" />
                ) : (
                  <span
                    className={`nm-bar w-full rounded-t-[4px] ${hover === i ? 'bg-ink/70' : same ? 'bg-ink/45' : 'bg-ink/15'}`}
                    style={{ height: pct(v), minHeight: v > 0 ? 2 : 0, animationDelay: `${i * 22}ms` }}
                  />
                )}
              </div>
            )
          })}
          <span className="w-2 shrink-0" />
          <div className="relative flex h-full flex-[1.8] items-end" onMouseEnter={() => setHover(dates.length)}>
            {hover === dates.length &&
              next.lo !== undefined &&
              next.hi !== undefined &&
              tip(dates.length, `${dayPrefix(next.date)}예상 ${count(next.value)}개 · 범위 ${count(next.lo)}–${count(next.hi)}개`, next.hi)}
            <span
              className="nm-bar w-full rounded-t-[4px] bg-accent"
              style={{ height: pct(next.value), minHeight: 2, animationDelay: `${dates.length * 22 + 120}ms` }}
            />
            {next.lo !== undefined && next.hi !== undefined && (
              <span
                className="nm-fade absolute left-1/2 w-[2px] -translate-x-1/2 rounded-full bg-ink"
                style={{ bottom: pct(next.lo), height: pct(next.hi - next.lo), animationDelay: `${dates.length * 22 + 500}ms` }}
              />
            )}
            {hover !== dates.length && (
              <span
                className="nm-fade absolute left-1/2 mb-1 -translate-x-1/2 whitespace-nowrap text-sm font-extrabold tabular-nums"
                style={{ bottom: pct(next.hi ?? next.value), animationDelay: `${dates.length * 22 + 300}ms` }}
              >
                <CountUp to={next.value} />개
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="mt-1.5 flex gap-[2px] pl-9 text-[11px] text-faint" aria-hidden>
        {dates.map((d) => (
          <span key={d} className="flex-1 overflow-visible whitespace-nowrap text-center">
            {asDate(d).getDay() === weekday ? short(d) : ''}
          </span>
        ))}
        <span className="w-2 shrink-0" />
        <span className="flex-[1.8] whitespace-nowrap text-center font-bold text-ink">{day === '이날' ? short(next.date) : day}</span>
      </div>
    </div>
  )
}

// 그래프 아래의 색 설명 (회색 두 가지와 파랑)
export function BarsLegend({ date }: { date: string }) {
  const item = (color: string, text: string) => (
    <span className="flex items-center gap-1.5">
      <i className={`h-2.5 w-2.5 rounded-[3px] ${color}`} />
      {text}
    </span>
  )
  return (
    <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {item('bg-ink/45', `${WEEKDAYS[asDate(date).getDay()]}요일`)}
      {item('bg-accent', `${dayPrefix(date)}예상`)}
    </p>
  )
}

// 표의 한 줄에 들어가는 작은 그림: 최근 4주 추이선(회색) → 내일 예상(파란 점)과 예상 범위(세로 띠)
export function Spark({ values, next, delay = 0 }: { values: (number | null)[]; next: NextDay; delay?: number }) {
  const W = 120
  const H = 34
  const top = Math.max(next.hi ?? next.value, ...values.map((v) => v ?? 0), 1)
  const x = (i: number) => 2 + (i * (W - 22)) / Math.max(values.length - 1, 1)
  const y = (v: number) => H - 4 - (v / top) * (H - 8)
  let path = ''
  let pen = false // 빈 날(휴무)에서는 선을 끊는다
  values.forEach((v, i) => {
    if (v === null) pen = false
    else {
      path += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`
      pen = true
    }
  })
  const lastIndex = values.findLastIndex((v) => v !== null)
  const nx = W - 6

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible" aria-hidden>
      {next.lo !== undefined && next.hi !== undefined && (
        <line
          x1={nx} x2={nx} y1={y(next.lo)} y2={y(next.hi)}
          className="nm-fade stroke-accent/25" strokeWidth={6} strokeLinecap="round"
          style={{ animationDelay: `${delay + 700}ms` }}
        />
      )}
      <path d={path} pathLength={1} className="nm-line fill-none stroke-ink/30" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" style={{ animationDelay: `${delay}ms` }} />
      {lastIndex >= 0 && (
        <line
          x1={x(lastIndex)} y1={y(values[lastIndex] as number)} x2={nx} y2={y(next.value)}
          className="nm-fade stroke-accent" strokeWidth={1.5} strokeDasharray="2 3"
          style={{ animationDelay: `${delay + 700}ms` }}
        />
      )}
      <circle cx={nx} cy={y(next.value)} r={4} className="nm-dotin fill-accent stroke-white" strokeWidth={2} style={{ animationDelay: `${delay + 800}ms` }} />
    </svg>
  )
}
