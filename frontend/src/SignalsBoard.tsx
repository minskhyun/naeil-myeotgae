// '예측에 쓴 주변 정보'를 글 대신 그림으로 (분석 탭). 긴 풀이(SourcesView)는 접어 두고, 한눈에 보이는 것만 앞에 둔다.
//   위    지도(가게 · 주변 시설 · 찾은 행사) + 모은 정보의 숫자 칸
//   아래  정보 묶음 네 칸: 썼는지 · 넣었을 때 오차가 얼마나 줄었는지(막대, 기준선 3%) · 시험한 구간 중 몇 곳에서 나아졌는지(점) · 그 안의 신호들
// 숫자의 뜻: 오차 변화 = 그 묶음을 넣었을 때와 뺐을 때의 차이 (ml/evaluate.py의 decide). 기준 3%와 '절반이 넘는 구간'을 모두 채워야 쓴다.
import { useQuery } from '@tanstack/react-query'
import { AnalysisMap } from './AnalysisMap'
import { api, type ProgressEvent, type SignalDecision } from './api'
import { count, GROUP_LABELS, SIGNAL_LABELS } from './format'
import { SourcesView } from './SourcesView'

const MIN_GAIN = 3 // 이만큼(%) 이상 줄어야 쓴다 (ml/evaluate.py의 MIN_GAIN_PCT)
const MAP_KINDS: ProgressEvent['kind'][] = ['store', 'places', 'plan', 'event'] // 지도에 그릴 것

// 분석 기록에서 '무엇을 얼마나 모았나'를 숫자 칸으로 (있는 것만)
function gathered(events: ProgressEvent[]) {
  const got = <K extends ProgressEvent['kind']>(kind: K) => events.filter((e) => e.kind === kind) as Extract<ProgressEvent, { kind: K }>[]
  const school = got('academic')[0]
  const terms = school ? (school.exams ?? 0) + (school.vacations ?? 0) + (school.festivals ?? 0) : 0
  return [
    { label: '날씨', value: got('weather')[0] ? `${count(got('weather')[0].days)}일` : null },
    { label: '주변 시설', value: got('places')[0] ? `${count(got('places')[0].count)}곳` : null },
    { label: '시험·방학·축제', value: terms ? `${terms}번` : school ? `${count(school.days)}일` : null },
    { label: '근처 행사', value: got('event').length ? `${got('event').length}건` : null },
    { label: '읽은 글', value: got('article').length ? `${got('article').length}건` : null },
    { label: '검색량을 본 메뉴', value: got('trend_span')[0] ? `${got('trend_span')[0].menus}개` : null },
    { label: '기념일', value: got('special').length ? `${got('special').length}개` : null },
  ].filter((g) => g.value)
}

// 정보 묶음 하나: 썼는지 · 효과 막대 · 구간 점 · 신호들
function GroupCard({ d, scale }: { d: SignalDecision; scale: number }) {
  const tested = d.folds_total > 0
  const cut = Math.max(0, -d.wape_change_pct) // 오차가 줄어든 만큼(%). 늘었으면 0
  const names = [...new Set(d.signals.map((s) => SIGNAL_LABELS[s]).filter(Boolean))]
  return (
    <li className={`flex flex-col rounded-3xl p-6 ${d.adopted ? 'bg-ink-900 text-white' : 'bg-page'}`} title={d.reason}>
      <p className="flex items-center justify-between gap-2">
        <span className="text-h3">{GROUP_LABELS[d.signal_group] ?? d.signal_group}</span>
        <span className={`tag ${d.adopted ? 'bg-point text-white' : 'bg-white text-ink-500'}`}>{d.adopted ? '예측에 씀' : '안 씀'}</span>
      </p>

      <p className="mt-5 text-h1 tabular-nums">
        {tested ? (
          <>
            {cut.toFixed(1)}
            <span className={`ml-1 text-xl font-normal tracking-normal ${d.adopted ? 'text-white/70' : 'text-ink-500'}`}>% 오차 감소</span>
          </>
        ) : (
          <span className="text-ink-500">–</span>
        )}
      </p>
      {/* 효과 막대: 세로선이 기준(3%). 막대가 선을 넘어야 쓴다 */}
      <div className={`relative mt-3 h-3 rounded-full ${d.adopted ? 'bg-white/20' : 'bg-white'}`}>
        <div className={`nm-band h-3 rounded-full ${d.adopted ? 'bg-point' : 'bg-ink-300'}`} style={{ width: `${Math.min(100, (cut / scale) * 100)}%` }} />
        <span className={`absolute -top-1 h-5 w-0.5 ${d.adopted ? 'bg-white' : 'bg-ink-900'}`} style={{ left: `${(MIN_GAIN / scale) * 100}%` }} aria-hidden />
      </div>
      <p className={`mt-1.5 text-xs ${d.adopted ? 'text-white/70' : 'text-ink-500'}`}>세로선 = 기준 {MIN_GAIN}%</p>

      {/* 시험한 구간마다 점 하나: 나아진 구간은 채운 점 */}
      <p className={`mt-5 flex items-center gap-2 text-sm ${d.adopted ? 'text-white/80' : 'text-ink-700'}`}>
        {tested ? (
          <>
            <span className="flex gap-1" aria-hidden>
              {Array.from({ length: d.folds_total }, (_, i) => (
                <i key={i} className={`h-2.5 w-2.5 rounded-full ${i < d.folds_improved ? (d.adopted ? 'bg-point' : 'bg-ink-900') : d.adopted ? 'bg-white/25' : 'bg-ink-300'}`} />
              ))}
            </span>
            {d.folds_total}개 구간 중 {d.folds_improved}개에서 나아짐
          </>
        ) : (
          '평가할 자료가 없어요'
        )}
      </p>

      <ul className="mt-auto flex flex-wrap gap-1.5 pt-5">
        {names.map((n) => (
          <li key={n} className={`tag ${d.adopted ? 'bg-white/15 text-white' : 'bg-white text-ink-700'}`}>
            {n}
          </li>
        ))}
      </ul>
    </li>
  )
}

// events = 이 매장을 마지막으로 분석했을 때의 기록 (없으면 지도와 숫자 칸은 그리지 않는다)
export function SignalsBoard({ storeId, events }: { storeId: string; events?: ProgressEvent[] }) {
  const backtest = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) }).data
  const onMap = (events ?? []).filter((e) => MAP_KINDS.includes(e.kind))
  const hasMap = onMap.some((e) => e.kind === 'store' && e.lat)
  const tiles = gathered(events ?? [])
  const decisions = backtest?.decisions ?? []
  // 막대의 오른쪽 끝: 가장 큰 효과에 맞추되 기준선이 너무 오른쪽으로 가지 않게 최소 8%
  const scale = Math.max(8, ...decisions.map((d) => -d.wape_change_pct)) * 1.1

  return (
    <div className="space-y-5">
      {(hasMap || !!tiles.length) && (
        <div className={`grid gap-5 ${hasMap ? 'lg:grid-cols-[1.25fr_1fr]' : ''}`}>
          {hasMap && (
            <div className="relative isolate h-80 overflow-hidden rounded-3xl lg:h-auto lg:min-h-80">
              <AnalysisMap events={onMap} ambient />
              <p className="absolute left-4 top-4 z-[900] rounded-full bg-white px-3.5 py-1.5 text-sm font-medium text-ink-700">가게 주변에서 찾은 곳</p>
            </div>
          )}
          <ul className="grid grid-cols-2 gap-3 self-start">
            {tiles.map((g) => (
              <li key={g.label} className="rounded-3xl bg-page px-5 py-6">
                <p className="text-h2 tabular-nums">{g.value}</p>
                <p className="mt-1.5 text-sm text-ink-700">{g.label}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!!decisions.length && (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {decisions.map((d) => (
            <GroupCard key={d.signal_group} d={d} scale={scale} />
          ))}
        </ul>
      )}

      <details>
        <summary className="cursor-pointer text-sm font-semibold underline-offset-4 hover:underline">AI가 고른 정보원과 읽은 글 자세히 보기</summary>
        <div className="mt-8">
          <SourcesView storeId={storeId} brief />
        </div>
      </details>
    </div>
  )
}
