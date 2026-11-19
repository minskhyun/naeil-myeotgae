// 로그인 뒤의 분석 결과 화면: 한 매장의 준비를 한눈에. 글은 최소로, 숫자와 그림 위주로.
//   맨 위   매장 · 날짜 · 준비 기준
//   요약    숫자 네 칸 (준비할 개수 · 예상 판매 · 하루 오차 · 주의할 소식)
//   본문    왼쪽: 메뉴별 준비표      오른쪽: 주의할 소식 · 예측에 쓴 정보 · 얼마나 맞나 · 요일별 판매
// 풀이와 자세한 내용은 길게 늘어놓지 않는다: '자세히'를 누르면 창으로 뜨고, 짧은 뜻은 마우스를 올리면 보인다.
//   하루 오차 = 예측대로 준비했다면 남거나 모자랐을 개수 (모든 메뉴 합, 하루 평균). '지난주대로' = 지난주 같은 요일만큼 준비
import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api } from './api'
import { BacktestView, BarRow } from './BacktestView'
import { WeekdayBars } from './ForecastCharts'
import { ForecastTable, Notice, PrepToggle } from './ForecastView'
import { average, count, dayPrefix, fmtDate, GROUP_LABELS, pct1, RANGE_TARGET_TEXT, sameWeekday, shortDate, SITUATION_LABELS, weekdayName } from './format'
import { Modal } from './Modal'
import { SourcesView } from './SourcesView'
import { periodName, verdict } from './verdict'

const MENUS_SHOWN = 8 // 준비표에 처음 보여 줄 메뉴 수 (나머지는 '더 보기')
const MISS_HELP = '예측대로 준비했다면 남거나 모자랐을 개수 (모든 메뉴 합, 하루 평균)'

// 요약 숫자 한 칸: 이름 · 큰 숫자 · (짧은 덧말). help = 마우스를 올리면 보이는 뜻
function Tile({ label, value, note, warn = false, help }: { label: string; value: string; note?: string; warn?: boolean; help?: string }) {
  return (
    <div className="rounded-3xl bg-sheet px-6 py-5 shadow-sm" title={help}>
      <p className="flex items-center gap-2 text-sm font-semibold text-muted">
        {warn && <span className="h-2 w-2 rounded-full bg-warn" aria-hidden="true" />}
        {label}
      </p>
      <p className="mt-1.5 text-4xl font-extrabold tracking-tight tabular-nums">{value}</p>
      {note && <p className="mt-1.5 text-sm text-muted">{note}</p>}
    </div>
  )
}

// 카드 제목 옆의 작은 버튼 ('자세히', '분석 과정')
function More({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className="rounded-full bg-paper px-3.5 py-1 text-sm font-semibold text-muted hover:text-ink">
      {children}
    </button>
  )
}

// 본문의 카드 한 장: 제목 (+ 작은 버튼들) · 내용. grow = 줄에서 남는 높이를 이 카드가 채운다 (내용도 그 높이만큼 늘어난다)
function Card({ title, actions, grow = false, children }: { title: string; actions?: ReactNode; grow?: boolean; children: ReactNode }) {
  return (
    <section className={`min-w-0 rounded-3xl bg-sheet p-5 shadow-sm sm:p-6 ${grow ? 'flex flex-1 flex-col' : ''}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-lg font-bold">{title}</h3>
        {actions && <div className="flex gap-2">{actions}</div>}
      </div>
      {grow ? <div className="min-h-0 flex-1">{children}</div> : children}
    </section>
  )
}

export function Dashboard({ storeId, storeName, prepMode, readOnly, onReplay }: {
  storeId: string
  storeName: string
  prepMode: string
  readOnly: boolean
  onReplay?: () => void // 분석 과정 다시 보기 (기록이 있을 때만)
}) {
  const forecast = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) })
  const backtest = useQuery({ queryKey: ['backtest', storeId], queryFn: () => api.backtest(storeId) }).data
  const history = useQuery({ queryKey: ['history', storeId], queryFn: () => api.history(storeId), retry: false }).data
  const [detail, setDetail] = useState<'sources' | 'backtest' | null>(null)

  if (forecast.isLoading) return <p className="text-muted">불러오는 중…</p>
  if (forecast.error || !forecast.data) return <p className="text-up">{(forecast.error as Error)?.message ?? '예측이 없습니다.'}</p>
  const fc = forecast.data

  // 요약 숫자에 쓸 값들
  const date = fc.rows[0].date
  const totalPrep = fc.rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(fc.rows.reduce((sum, r) => sum + r.pred, 0))
  // 예상 판매가 평소 같은 요일(지난 4주 평균)보다 몇 % 많은가
  const usual = history ? average(sameWeekday(history.dates, history.total, date)) : null
  const diff = usual ? Math.round((totalPred / usual - 1) * 100) : null
  // 얼마나 맞나: 지난주대로 준비했을 때 vs 내일몇개 예측대로 준비했을 때 (마지막 확인 기간, 없으면 검증 기간)
  const v = verdict(backtest)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          {/* 예측 날짜가 오늘·어제로 보일 때 헷갈리지 않게: 어느 날까지의 판매 기록으로 만든 준비표인지 적는다 */}
          <p className="text-sm font-semibold text-muted">
            {storeName}
            {history?.dates.length ? ` · 판매 기록 ${shortDate(history.dates[history.dates.length - 1])}까지` : ''}
          </p>
          <h2 className="mt-0.5 text-3xl font-extrabold tracking-tight">{fmtDate(date)}</h2>
        </div>
        <PrepToggle storeId={storeId} prepMode={prepMode} readOnly={readOnly} />
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label={`${dayPrefix(date)}준비할 개수`} value={`${count(totalPrep)}개`} note={`메뉴 ${fc.rows.length}개`} />
        <Tile
          label="예상 판매"
          value={`${count(totalPred)}개`}
          note={diff === null ? undefined : Math.abs(diff) < 3 ? `평소 ${weekdayName(date)}요일과 비슷` : `평소 ${weekdayName(date)}요일보다 ${Math.abs(diff)}% ${diff > 0 ? '많음' : '적음'}`}
        />
        <Tile
          label="하루 오차"
          value={v ? `${count(v.mineShown)}개` : '–'}
          note={v ? `지난주대로 준비하면 ${count(v.baseShown)}개` : undefined}
          help={MISS_HELP}
        />
        <Tile
          label="주의할 소식"
          value={fc.warnings.length ? `${fc.warnings.length}건` : '없음'}
          note={fc.warnings.length ? `${SITUATION_LABELS[fc.warnings[0].situation_type] ?? fc.warnings[0].situation_type} · 손님 ${fc.warnings[0].direction} 가능` : undefined}
          warn={fc.warnings.length > 0}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.75fr_1fr]">
        <Card title="메뉴별 준비표">
          <ForecastTable rows={fc.rows} limit={MENUS_SHOWN} compact storeId={storeId} />
        </Card>

        {/* 오른쪽 줄은 왼쪽 준비표와 아래 끝을 맞춘다: 남는 높이는 맨 아래의 요일별 그래프가 채운다 (막대가 그만큼 길어진다) */}
        <div className="flex min-w-0 flex-col gap-5">
          <Card title="주의할 소식">
            {fc.warnings.length ? (
              <div className="space-y-3">
                {fc.warnings.map((w, i) => (
                  <Notice key={i} w={w} />
                ))}
              </div>
            ) : (
              <p className="text-muted">특별한 소식이 없어요.</p>
            )}
          </Card>

          <Card
            title="예측에 쓴 정보"
            actions={
              <>
                {onReplay && <More onClick={onReplay}>분석 과정</More>}
                <More onClick={() => setDetail('sources')}>자세히</More>
              </>
            }
          >
            {backtest ? (
              <ul className="flex flex-wrap gap-2">
                <li className="rounded-full bg-accent px-3.5 py-1.5 text-sm font-bold text-white">판매 기록</li>
                {backtest.decisions.map((d) => (
                  <li
                    key={d.signal_group}
                    title={d.reason}
                    className={`rounded-full px-3.5 py-1.5 text-sm font-bold ${d.adopted ? 'bg-accent text-white' : 'bg-paper text-faint line-through decoration-faint/60'}`}
                  >
                    {GROUP_LABELS[d.signal_group] ?? d.signal_group}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted">검증 결과가 없어요.</p>
            )}
          </Card>

          <Card title="얼마나 맞나" actions={<More onClick={() => setDetail('backtest')}>자세히</More>}>
            {v ? (
              <div title={`${periodName(v)} 기준 · ${MISS_HELP}`}>
                <p className="mb-3 text-2xl font-extrabold tracking-tight">
                  {v.saved > 0 ? (
                    <>
                      지난주대로보다 <span className="text-accent">{v.gain}% 덜 틀려요</span>
                    </>
                  ) : (
                    '지난주대로와 비슷해요'
                  )}
                </p>
                <BarRow label="지난주대로 준비" value={v.baseMiss} max={Math.max(v.baseMiss, v.mineMiss)} strong={false} />
                <BarRow label="내일몇개" value={v.mineMiss} max={Math.max(v.baseMiss, v.mineMiss)} strong />
                <p className="mt-4 flex items-baseline justify-between gap-3 border-t border-rule pt-4 text-sm">
                  <span className="text-muted">예상 범위 안에 든 비율</span>
                  <span className="text-muted">
                    <b className="mr-2 text-lg tabular-nums text-ink">{pct1(v.mine.coverage_80)}</b>
                    {RANGE_TARGET_TEXT}
                  </span>
                </p>
              </div>
            ) : (
              <p className="text-muted">검증 결과가 아직 없어요.</p>
            )}
          </Card>

          {history && (
            <Card title="요일별 판매" grow>
              <WeekdayBars dates={history.dates} values={history.total} date={date} />
            </Card>
          )}
        </div>
      </div>

      {detail === 'sources' && (
        <Modal label="주변 정보" onClose={() => setDetail(null)} wide>
          <SourcesView storeId={storeId} />
        </Modal>
      )}
      {detail === 'backtest' && (
        <Modal label="얼마나 맞나" onClose={() => setDetail(null)} wide>
          <BacktestView storeId={storeId} />
        </Modal>
      )}
    </div>
  )
}
