// '예상 범위 안에 든 비율'이 무슨 뜻인지 보여 주는 눈금.
// 예상 범위(예: 18~27개)는 실제 판매가 10번 중 8번 그 안에 들도록 잡은 폭이다. 그래서 지난 날짜로 재 본
// '실제로 든 비율'이 80%에 가까울수록 폭을 알맞게 잡은 것이다. 높을수록 좋은 점수가 아니다:
//   80%보다 많이 낮다 = 범위가 좁다 (실제 판매가 자주 벗어난다)
//   80%보다 많이 높다 = 범위가 넓다 (틀릴 일은 없지만 쓸모가 줄어든다)
// value = 실제로 든 비율 (0~1). 눈금은 50~100%만 그린다 (그 아래는 거의 나오지 않는다)
import { RANGE_NEAR as NEAR, RANGE_TARGET as TARGET } from './format'

const LOW = 50

const at = (pct: number) => `${Math.min(100, Math.max(0, ((pct - LOW) / (100 - LOW)) * 100))}%`

export function RangeMeter({ value }: { value: number }) {
  return (
    <div className="mt-4" role="img" aria-label={`예상 범위 안에 든 비율 ${(value * 100).toFixed(1)}%. 80%에 가까울수록 알맞은 폭입니다.`}>
      <div className="relative h-2 rounded-full bg-line">
        {/* 알맞은 자리: 80% 둘레 */}
        <span className="absolute inset-y-0 rounded-full bg-ink-300" style={{ left: at(TARGET - NEAR), width: `${((NEAR * 2) / (100 - LOW)) * 100}%` }} />
        <span className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-point" style={{ left: at(value * 100) }} />
      </div>
      <div className="relative mt-1.5 h-4 text-xs text-ink-500">
        <span className="absolute left-0">좁음</span>
        <span className="absolute -translate-x-1/2 font-medium text-ink-700" style={{ left: at(TARGET) }}>
          알맞음 80%
        </span>
        <span className="absolute right-0">넓음</span>
      </div>
    </div>
  )
}
