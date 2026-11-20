// 소개(About.tsx)의 작은 그림들. 글만으로는 읽기 힘든 내용을 칸마다 그림 하나로 먼저 보여 준다.
// 모두 같은 틀(160×96)에 선 굵기 2.5로 그린다. 색은 셋: 잉크(선) · 옅은 회색(바탕이 되는 것) · 주황(말하려는 것).
// 그림은 뜻을 전하는 약도다: 실제 숫자를 그린 그래프가 아니다 (실제 결과는 아래 '예시 매장의 실제 결과'에 있다).
import { type ReactNode } from 'react'

function Art({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 160 96" className="h-full w-full" fill="none" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {children}
    </svg>
  )
}
const INK = 'stroke-ink-900'
const SOFT = 'stroke-ink-300'
const HOT = 'stroke-point'

// 종 모양 곡선 (판매 개수가 퍼지는 모양). 범위·준비 기준 그림이 같이 쓴다
const BELL = 'M12 78 C44 78 52 18 80 18 C108 18 116 78 148 78'

const ART: Record<string, ReactNode> = {
  // ---- 네 단계
  // 판매 기록 정리: 표에서 합계 줄을 뺀다
  tidy: (
    <Art>
      <rect x="34" y="14" width="92" height="68" rx="8" className={INK} />
      <path d="M34 32H126M34 48H126M34 64H126M66 14V82" className={SOFT} />
      <path d="M42 73H118" className={HOT} />
      <path d="M44 23H58M76 23H112M44 40H58M76 40H104M44 56H58M76 56H110" className={INK} />
    </Art>
  ),
  // 주변 정보 모으기: 가게 둘레에서 점들을 찾는다
  gather: (
    <Art>
      <circle cx="80" cy="48" r="20" className={SOFT} strokeDasharray="1 7" />
      <circle cx="80" cy="48" r="36" className={SOFT} strokeDasharray="1 7" />
      <g className="fill-ink-900" stroke="none">
        <circle cx="52" cy="30" r="3.5" />
        <circle cx="112" cy="36" r="3.5" />
        <circle cx="104" cy="70" r="3.5" />
        <circle cx="50" cy="64" r="3.5" />
        <circle cx="86" cy="18" r="3.5" />
      </g>
      <path d="M56 33L74 45M108 38L88 46M101 67L86 53" className={HOT} strokeDasharray="4 5" />
      <circle cx="80" cy="48" r="7" className="fill-point" stroke="none" />
    </Art>
  ),
  // 지난 날짜로 시험하기: 앞의 기록만 보고 다음 칸을 맞혀 본다
  rehearse: (
    <Art>
      <g className="fill-ink-300" stroke="none">
        <rect x="14" y="38" width="22" height="26" rx="5" />
        <rect x="42" y="38" width="22" height="26" rx="5" />
        <rect x="70" y="38" width="22" height="26" rx="5" />
      </g>
      <rect x="100" y="36" width="44" height="30" rx="7" className={HOT} strokeDasharray="5 5" />
      <path d="M113 51L119 57L131 45" className={HOT} />
      <path d="M14 78H92" className={INK} />
      <path d="M86 73L92 78L86 83" className={INK} />
      <path d="M25 26V30M53 26V30M81 26V30" className={SOFT} />
    </Art>
  ),
  // 다음 날 예측하기: 지난 막대들 옆에 내일 막대와 범위
  tomorrow: (
    <Art>
      <g className="fill-ink-300" stroke="none">
        <rect x="20" y="46" width="16" height="34" rx="4" />
        <rect x="44" y="36" width="16" height="44" rx="4" />
        <rect x="68" y="52" width="16" height="28" rx="4" />
        <rect x="92" y="42" width="16" height="38" rx="4" />
      </g>
      <rect x="118" y="34" width="18" height="46" rx="4" className="fill-point" stroke="none" />
      <path d="M127 16V44M120 16H134M120 44H134" className={INK} />
    </Art>
  ),

  // ---- 이렇게 예측해요
  // 평소보다 몇 배: 큰 메뉴든 작은 메뉴든 같은 비율로 늘어난다
  ratio: (
    <Art>
      <rect x="34" y="36" width="30" height="46" rx="5" className="fill-ink-300" stroke="none" />
      <rect x="34" y="20" width="30" height="16" rx="5" className="fill-point" stroke="none" />
      <rect x="100" y="66" width="30" height="16" rx="5" className="fill-ink-300" stroke="none" />
      <rect x="100" y="59" width="30" height="7" rx="3.5" className="fill-point" stroke="none" />
      <path d="M20 82H144" className={INK} />
      <text x="49" y="13" textAnchor="middle" className="fill-ink-900 text-[11px] font-semibold" stroke="none">
        ×1.3
      </text>
      <text x="115" y="52" textAnchor="middle" className="fill-ink-900 text-[11px] font-semibold" stroke="none">
        ×1.3
      </text>
    </Art>
  ),
  // 범위로 답하기: 퍼지는 모양의 가운데 80%가 예상 범위
  range: (
    <Art>
      <path d="M52 78 C58 48 66 18 80 18 C94 18 102 48 108 78Z" className="fill-point/25" stroke="none" />
      <path d={BELL} className={INK} />
      <path d="M80 18V78" className={HOT} />
      <path d="M52 86H108M52 82V90M108 82V90" className={INK} />
    </Art>
  ),
  // 준비 기준: 같은 모양에서 어느 지점을 꺼낼지 고른다
  prep: (
    <Art>
      <path d={BELL} className={SOFT} />
      <path d="M14 78H146" className={INK} />
      <path d="M62 78V42M80 78V18M98 78V42" className={SOFT} strokeDasharray="3 5" />
      <circle cx="62" cy="78" r="6" className="fill-white stroke-ink-900" />
      <circle cx="80" cy="78" r="7" className="fill-point" stroke="none" />
      <circle cx="98" cy="78" r="6" className="fill-white stroke-ink-900" />
    </Art>
  ),

  // ---- 주변 정보를 쓰는 조건
  // 오차가 3% 이상 줄어야: 줄어든 막대가 기준선을 넘어야 한다
  gain: (
    <Art>
      <rect x="18" y="26" width="124" height="16" rx="8" className="fill-ink-300" stroke="none" />
      <rect x="18" y="54" width="104" height="16" rx="8" className="fill-point" stroke="none" />
      <path d="M130 16V82" className={INK} strokeDasharray="3 6" />
    </Art>
  ),
  // 절반이 넘는 기간에서: 네 기간 중 셋에서 나아짐
  folds: (
    <Art>
      <path d="M20 62H140" className={SOFT} />
      <path d="M20 56V68M60 56V68M100 56V68M140 56V68" className={SOFT} />
      <g className="fill-point" stroke="none">
        <circle cx="40" cy="38" r="9" />
        <circle cx="80" cy="38" r="9" />
        <circle cx="120" cy="38" r="9" />
      </g>
      <path d="M36 38L39 41L45 35M76 38L79 41L85 35M116 38L119 41L125 35" className="stroke-white" />
    </Art>
  ),
  // 얹혀 가면 안 됨: 하나를 빼 보고 나빠지는지 본다
  alone: (
    <Art>
      <rect x="24" y="52" width="40" height="26" rx="6" className="fill-ink-300" stroke="none" />
      <rect x="24" y="20" width="40" height="26" rx="6" className="fill-point" stroke="none" />
      <rect x="96" y="52" width="40" height="26" rx="6" className="fill-ink-300" stroke="none" />
      <rect x="96" y="20" width="40" height="26" rx="6" className={HOT} strokeDasharray="5 5" />
      <path d="M72 49H88M83 44L88 49L83 54" className={INK} />
    </Art>
  ),
  // 그때 몰랐던 정보는 안 씀: 닫는 시간 앞의 것만 쓴다
  cutoff: (
    <Art>
      <path d="M14 58H146" className={SOFT} />
      <path d="M92 18V82" className={INK} />
      <g className="fill-point" stroke="none">
        <circle cx="30" cy="58" r="6" />
        <circle cx="54" cy="58" r="6" />
        <circle cx="76" cy="58" r="6" />
      </g>
      <circle cx="112" cy="58" r="6" className="fill-white stroke-ink-300" />
      <circle cx="134" cy="58" r="6" className="fill-white stroke-ink-300" />
      <path d="M100 30H122" className={SOFT} strokeDasharray="1 6" />
    </Art>
  ),

  // ---- AI가 하는 일
  // 어디를 볼지 고르기: 주변의 점들 가운데 몇 개를 고른다
  choose: (
    <Art>
      <g className="fill-ink-300" stroke="none">
        <circle cx="30" cy="30" r="4" />
        <circle cx="52" cy="66" r="4" />
        <circle cx="132" cy="28" r="4" />
        <circle cx="126" cy="72" r="4" />
      </g>
      <circle cx="78" cy="42" r="22" className={INK} />
      <path d="M94 58L112 76" className={INK} />
      <circle cx="72" cy="38" r="5" className="fill-point" stroke="none" />
      <circle cx="86" cy="48" r="5" className="fill-point" stroke="none" />
    </Art>
  ),
  // 글에서 행사 찾기: 글 가운데 날짜·장소가 든 줄
  read: (
    <Art>
      <rect x="30" y="12" width="76" height="72" rx="8" className={INK} />
      <path d="M42 28H94M42 60H94M42 72H76" className={SOFT} />
      <rect x="40" y="38" width="56" height="12" rx="6" className="fill-point" stroke="none" />
      <rect x="112" y="34" width="28" height="28" rx="6" className={INK} />
      <path d="M112 44H140M120 30V37M132 30V37" className={INK} />
    </Art>
  ),
  // 관련 따지기: 1~5 가운데 몇 점인지
  rate: (
    <Art>
      <g className="fill-point" stroke="none">
        <circle cx="28" cy="48" r="10" />
        <circle cx="54" cy="48" r="10" />
        <circle cx="80" cy="48" r="10" />
        <circle cx="106" cy="48" r="10" />
      </g>
      <circle cx="132" cy="48" r="9" className={SOFT} />
    </Art>
  ),
  // 주의할 소식 쓰기: 말풍선과 그 근거가 되는 인용
  notice: (
    <Art>
      <path d="M26 16H134A8 8 0 0 1 142 24V58A8 8 0 0 1 134 66H70L52 82V66H26A8 8 0 0 1 18 58V24A8 8 0 0 1 26 16Z" className={INK} />
      <path d="M34 32H112M34 46H90" className={SOFT} />
      <circle cx="124" cy="46" r="5" className="fill-point" stroke="none" />
      <path d="M124 26V36" className={HOT} />
    </Art>
  ),
}

// 이름으로 그림 하나를 그린다 (About.tsx의 칸들이 쓴다)
export function Picture({ name }: { name: string }) {
  return <>{ART[name]}</>
}
