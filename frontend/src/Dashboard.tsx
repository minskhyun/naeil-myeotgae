// 분석 화면(Workspace.tsx)의 두 탭.
//   DashboardTab  오늘 할 일: 판매 기록 올리기(분석 시작) · 준비 기준 · 준비할 개수 · 메뉴별 준비표 · 주의할 소식
//   AnalysisTab   얼마나 믿을 만한가: 예측 정확도(지난주대로 준비할 때와 비교) · 판매 그래프 · 예측에 쓴 주변 정보
// 모양은 첫 화면(Landing.tsx)과 같다: 옅은 회색 바탕 위의 흰 칸, 작은 고정폭 글씨의 구역 이름, 큰 숫자.
//   하루 오차 = 예측대로 준비했다면 남거나 모자랐을 개수 (모든 메뉴 합, 하루 평균). '지난주대로' = 지난주 같은 요일만큼 준비
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, type ProgressEvent } from './api'
import { BacktestView } from './BacktestView'
import { DayBars, WeekdayBars } from './ForecastCharts'
import { ForecastTable, Notice, PrepToggle } from './ForecastView'
import { average, count, dayPrefix, fmtDate, pct1, sameWeekday, shortDate, SITUATION_LABELS, weekdayName } from './format'
import { CountWhenSeen } from './Reveal'
import { ArrowLink } from './Site'
import { SignalsBoard } from './SignalsBoard'
import { periodName, verdict } from './verdict'

const MENUS_SHOWN = 8 // 준비표에 처음 보여 줄 메뉴 수 (나머지는 '더 보기')
const MISS_HELP = '예측대로 준비했다면 남거나 모자랐을 개수 (모든 메뉴 합, 하루 평균)'

// 탭의 머리: 구역 이름(작은 고정폭 글씨) · 작은 설명 · 큰 제목 · (오른쪽의 버튼)
function TabHead({ label, sub, title, action }: { label: string; sub?: string; title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
      <div>
        <p className="font-mono text-sm text-ink-500">{label}</p>
        {sub && <p className="mt-3 text-label text-ink-500">{sub}</p>}
        <h2 className="mt-1 text-h1">{title}</h2>
      </div>
      {action}
    </div>
  )
}

// 흰 칸 한 장: (제목) · 내용. grow = 줄에서 남는 높이를 이 칸이 채운다
function Card({ title, grow = false, children }: { title?: string; grow?: boolean; children: ReactNode }) {
  return (
    <section className={`min-w-0 rounded-[32px] bg-white p-6 sm:p-8 ${grow ? 'flex flex-1 flex-col' : ''}`}>
      {title && <h3 className="mb-5 text-h3">{title}</h3>}
      {grow ? <div className="min-h-0 flex-1">{children}</div> : children}
    </section>
  )
}

// 요약 숫자 한 칸: 이름 · 큰 숫자(단위는 작게 회색) · 짧은 덧말. big = 이 화면에서 가장 큰 숫자, point = 주황으로 강조
function Tile({ label, value, note, help, big = false, point = false }: { label: string; value: ReactNode; note?: string; help?: string; big?: boolean; point?: boolean }) {
  return (
    <div className="rounded-[32px] bg-white px-7 py-7" title={help}>
      <p className="text-label text-ink-500">{label}</p>
      <p className={`mt-2 whitespace-nowrap tabular-nums ${big ? 'text-display' : 'text-h1'} ${point ? 'text-point' : ''}`}>{value}</p>
      {note && <p className="mt-2 text-sm text-ink-700">{note}</p>}
    </div>
  )
}
const Unit = ({ children, big = false }: { children: ReactNode; big?: boolean }) => (
  <span className={`ml-1 font-normal tracking-normal text-ink-500 ${big ? 'text-[28px]' : 'text-xl'}`}>{children}</span>
)

// ---------------------------------------------------------------- 대시보드
export function DashboardTab({ storeId, storeName, prepMode, readOnly, onUpload }: {
  storeId: string
  storeName: string
  prepMode: string
  readOnly: boolean
  onUpload?: () => void // 이 매장의 판매 기록을 (다시) 올려 분석을 시작한다. 고칠 수 없는 매장이면 없다
}) {
  const forecast = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) })
  const history = useQuery({ queryKey: ['history', storeId], queryFn: () => api.history(storeId), retry: false }).data

  if (forecast.isLoading) return <p className="text-ink-700">불러오는 중…</p>
  if (forecast.error || !forecast.data) return <p className="text-down">{(forecast.error as Error)?.message ?? '예측이 없습니다.'}</p>
  const fc = forecast.data
  const date = fc.rows[0].date
  const totalPrep = fc.rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(fc.rows.reduce((sum, r) => sum + r.pred, 0))
  // 예상 판매가 평소 같은 요일(지난 4주 평균)보다 몇 % 많은가
  const usual = history ? average(sameWeekday(history.dates, history.total, date)) : null
  const diff = usual ? Math.round((totalPred / usual - 1) * 100) : null
  const first = fc.warnings[0]

  return (
    <div className="space-y-6">
      <TabHead
        label="Dashboard"
        // 예측 날짜가 오늘·어제로 보일 때 헷갈리지 않게: 어느 날까지의 판매 기록으로 만든 준비표인지 적는다
        sub={`${storeName}${history?.dates.length ? ` · 판매 기록 ${shortDate(history.dates[history.dates.length - 1])}까지` : ''}`}
        title={fmtDate(date)}
        action={
          onUpload && (
            <ArrowLink onClick={onUpload} dark>
              판매 기록 올리고 분석하기
            </ArrowLink>
          )
        }
      />

      <Card>
        <PrepToggle storeId={storeId} prepMode={prepMode} readOnly={readOnly} />
      </Card>

      <div className="grid gap-5 md:grid-cols-3">
        <Tile
          big
          label={`${dayPrefix(date)}준비할 개수`}
          value={
            <>
              {count(totalPrep)}
              <Unit big>개</Unit>
            </>
          }
          note={`메뉴 ${fc.rows.length}개`}
        />
        <Tile
          label="예상 판매"
          value={
            <>
              {count(totalPred)}
              <Unit>개</Unit>
            </>
          }
          note={diff === null ? undefined : Math.abs(diff) < 3 ? `평소 ${weekdayName(date)}요일과 비슷` : `평소 ${weekdayName(date)}요일보다 ${Math.abs(diff)}% ${diff > 0 ? '많음' : '적음'}`}
        />
        <Tile
          label="주의할 소식"
          value={
            fc.warnings.length ? (
              <>
                {fc.warnings.length}
                <Unit>건</Unit>
              </>
            ) : (
              '없음'
            )
          }
          note={first ? `${SITUATION_LABELS[first.situation_type] ?? first.situation_type} · 손님 ${first.direction} 가능` : undefined}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.7fr_1fr]">
        <Card title="메뉴별 준비표">
          <ForecastTable rows={fc.rows} limit={MENUS_SHOWN} compact storeId={storeId} />
        </Card>
        <Card title="주의할 소식">
          {fc.warnings.length ? (
            <div className="space-y-3">
              {fc.warnings.map((w, i) => (
                <Notice key={i} w={w} />
              ))}
            </div>
          ) : (
            <p className="text-ink-700">특별한 소식이 없어요.</p>
          )}
        </Card>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 분석
export function AnalysisTab({ storeId, storeName, onReplay, events }: {
  storeId: string
  storeName: string
  onReplay?: () => void // 분석 과정 다시 보기 (기록이 있을 때만)
  events?: ProgressEvent[] // 이 매장을 마지막으로 분석했을 때의 기록 (지도와 '모은 정보' 숫자의 재료)
}) {
  const forecast = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) }).data
  const backtest = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) }).data
  const history = useQuery({ queryKey: ['history', storeId], queryFn: () => api.history(storeId), retry: false }).data
  const v = verdict(backtest) // 마지막 확인 기간의 결과, 기록이 짧아 없으면 검증 기간 결과
  const rows = forecast?.rows ?? []
  const date = rows[0]?.date
  const sum = (pick: (r: (typeof rows)[number]) => number) => rows.reduce((total, r) => total + pick(r), 0)

  return (
    <div className="space-y-6">
      <TabHead
        label="Analysis"
        sub={`${storeName}${v ? ` · ${periodName(v)} 동안 맞혀 본 결과` : ''}`}
        title="예측이 얼마나 맞나요"
        action={onReplay && <ArrowLink onClick={onReplay}>분석 과정 다시 보기</ArrowLink>}
      />

      {v ? (
        <div className="grid gap-5 md:grid-cols-3" title={MISS_HELP}>
          <Tile
            big
            point={v.saved > 0}
            label="지난주대로 준비할 때 대비 정확도 향상"
            value={
              <>
                <CountWhenSeen to={Math.max(v.gain, 0)} />%
              </>
            }
            note="남거나 모자라는 개수가 줄어든 비율"
          />
          <Tile
            label="하루 오차"
            value={
              <>
                {count(v.baseShown)} → <CountWhenSeen to={v.mineShown} />
                <Unit>개</Unit>
              </>
            }
            note="모든 메뉴의 남은 개수와 모자란 개수의 합"
          />
          <Tile label="예상 범위 안에 든 비율" value={<CountWhenSeen to={v.mine.coverage_80} format={pct1} />} note="80%가 이상적" />
        </div>
      ) : (
        <Card>
          <p className="text-ink-700">검증 결과가 아직 없어요.</p>
        </Card>
      )}

      {history && date && (
        <div className="grid gap-5 xl:grid-cols-[1.7fr_1fr]">
          <Card title="최근 4주 판매와 예측">
            <DayBars dates={history.dates} values={history.total} next={{ date, value: sum((r) => r.pred), lo: sum((r) => r.p10), hi: sum((r) => r.p90) }} height={220} />
          </Card>
          <div className="flex min-w-0 flex-col">
            <Card title="요일별 판매" grow>
              <WeekdayBars dates={history.dates} values={history.total} date={date} />
            </Card>
          </div>
        </div>
      )}

      <Card title="예측 정확도">
        <BacktestView storeId={storeId} />
      </Card>

      <Card title="예측에 쓴 주변 정보">
        <SignalsBoard storeId={storeId} events={events} />
      </Card>
    </div>
  )
}
