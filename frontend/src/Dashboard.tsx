// 로그인 뒤의 분석 결과 화면: 한 매장의 내일 준비를 한눈에.
//   맨 위   날짜 · 준비 기준
//   요약    숫자 네 칸 (준비할 양 · 평소와 다른 메뉴 · 얼마나 맞나 · 주의할 소식)
//   본문    왼쪽: 메뉴별 준비표      오른쪽: AI 주의 안내 · 예측에 쓴 주변 정보 · 얼마나 맞나
// 자세한 내용(주변 정보 전체, 검증 전체)은 길게 늘어놓지 않고 '자세히'를 누르면 창으로 뜬다.
// 조각들은 기존 화면의 것을 그대로 쓴다 (ForecastView.tsx, BacktestView.tsx, SourcesView.tsx).
import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, type ModelScore } from './api'
import { BacktestView, BarRow } from './BacktestView'
import { ForecastTable, Notice, PrepToggle } from './ForecastView'
import { fmtDate, fmtTime, GROUP_LABELS, pct1 } from './format'
import { Modal } from './Modal'
import { SourcesView } from './SourcesView'

const MENUS_SHOWN = 8 // 준비표에 처음 보여 줄 메뉴 수 (나머지는 '더 보기')

// 요약 숫자 한 칸: 이름 · 큰 숫자 · 한 줄 설명
function Tile({ label, value, note, warn = false }: { label: string; value: string; note: string; warn?: boolean }) {
  return (
    <div className="rounded-3xl bg-sheet px-6 py-5 shadow-sm">
      <p className="flex items-center gap-2 text-sm text-muted">
        {warn && <span className="h-2 w-2 rounded-full bg-warn" aria-hidden="true" />}
        {label}
      </p>
      <p className="mt-1 text-3xl font-extrabold tracking-tight tabular-nums">{value}</p>
      <p className="mt-1 text-sm text-muted">{note}</p>
    </div>
  )
}

// 본문의 카드 한 장: 제목 (+ '자세히') · 내용
function Card({ title, onMore, children }: { title: string; onMore?: () => void; children: ReactNode }) {
  return (
    <section className="min-w-0 rounded-3xl bg-sheet p-5 shadow-sm sm:p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-lg font-bold">{title}</h3>
        {onMore && (
          <button onClick={onMore} className="rounded-full bg-paper px-3.5 py-1 text-sm font-semibold text-muted hover:text-ink">
            자세히
          </button>
        )}
      </div>
      {children}
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
  const [detail, setDetail] = useState<'sources' | 'backtest' | null>(null)

  if (forecast.isLoading) return <p className="text-muted">불러오는 중…</p>
  if (forecast.error || !forecast.data) return <p className="text-up">{(forecast.error as Error)?.message ?? '예측이 없습니다.'}</p>
  const fc = forecast.data

  // 요약 숫자에 쓸 값들
  const totalPrep = fc.rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(fc.rows.reduce((sum, r) => sum + r.pred, 0))
  const effect = (r: (typeof fc.rows)[number]) => r.reasons.reduce((sum, x) => sum + x.effect_pct, 0)
  const more = fc.rows.filter((r) => effect(r) > 0).length
  const less = fc.rows.filter((r) => effect(r) < 0).length
  const test = Object.fromEntries((backtest?.test_scores ?? []).map((s) => [s.model.slice(0, 2), s])) as Record<string, ModelScore>
  const mine = backtest ? test[backtest.chosen_model.slice(0, 2)] : undefined
  const base = test.M0
  const gain = mine && base ? Math.round((1 - mine.wape / base.wape) * 100) : null

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="text-sm text-muted">{storeName} · 내일 준비표</p>
          <h2 className="mt-0.5 text-3xl font-extrabold tracking-tight">{fmtDate(fc.rows[0].date)}</h2>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {onReplay && (
            <button onClick={onReplay} className="rounded-full bg-accent-soft px-4 py-1.5 text-sm font-semibold text-accent hover:bg-accent hover:text-white">
              분석 과정 다시 보기
            </button>
          )}
          <PrepToggle storeId={storeId} prepMode={prepMode} readOnly={readOnly} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="내일 준비할 양" value={`${totalPrep}개`} note={`메뉴 ${fc.rows.length}개 · 예상 판매 ${totalPred}개`} />
        <Tile
          label="평소와 다른 메뉴"
          value={`${more + less}개`}
          note={more + less ? `평소보다 많이 ${more}개 · 적게 ${less}개` : '모든 메뉴가 평소와 비슷해요'}
        />
        <Tile
          label="예상 범위 안에 든 비율"
          value={mine ? `${Math.round(mine.coverage_80 * 100)}%` : '–'}
          note={mine ? `목표 80% · 틀린 양 ${pct1(mine.wape)}` : '기록이 짧아 최종 시험이 없어요'}
        />
        <Tile
          label="주의할 소식"
          value={fc.warnings.length ? `${fc.warnings.length}건` : '없음'}
          note={fc.warnings.length ? `${fc.warnings[0].situation_type} · 손님 ${fc.warnings[0].direction} 가능` : 'AI가 모은 소식에 특별한 것이 없어요'}
          warn={fc.warnings.length > 0}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.75fr_1fr]">
        <Card title="메뉴별 준비표">
          <ForecastTable rows={fc.rows} limit={MENUS_SHOWN} compact />
          <p className="mt-3 text-xs leading-relaxed text-faint">
            준비 = 고른 준비 기준({prepMode})의 권장 개수 · 예상 범위 = 실제 판매가 들어올 것으로 보는 구간(세로 눈금이 예상값) · 평소와 다른 점에
            마우스를 올리면 설명 · {fmtTime(fc.generated_at)}에 계산
          </p>
        </Card>

        <div className="min-w-0 space-y-5">
          <Card title="AI 주의 안내">
            {fc.warnings.length ? (
              <div className="space-y-3">
                {fc.warnings.map((w, i) => (
                  <Notice key={i} w={w} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">내일은 특별히 주의할 소식이 없어요.</p>
            )}
          </Card>

          <Card title="예측에 쓴 주변 정보" onMore={() => setDetail('sources')}>
            {backtest ? (
              <ul className="space-y-2 text-sm">
                {backtest.decisions.map((d) => (
                  <li key={d.signal_group} className="flex items-center justify-between gap-3" title={d.reason}>
                    <span>{GROUP_LABELS[d.signal_group] ?? d.signal_group}</span>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${d.adopted ? 'bg-accent text-white' : 'bg-paper text-faint'}`}>
                      {d.adopted ? '씀' : '안 씀'}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">검증 결과가 없습니다.</p>
            )}
            <p className="mt-3 text-xs text-faint">지난 기록으로 시험해 예측이 실제로 나아진 정보만 써요.</p>
          </Card>

          <Card title="얼마나 맞나" onMore={() => setDetail('backtest')}>
            {mine && base ? (
              <>
                <BarRow label="지난주 같은 요일만큼" value={base.wape} max={Math.max(base.wape, mine.wape)} strong={false} />
                <BarRow label="내일몇개 예측" value={mine.wape} max={Math.max(base.wape, mine.wape)} strong />
                <p className="mt-3 text-sm text-muted">
                  틀린 양(짧을수록 좋음).{' '}
                  {gain !== null && gain > 0 ? <b className="text-ink">지난주만큼 준비할 때보다 {gain}% 적게 틀려요.</b> : '지난주만큼 준비하는 것보다 나아지지 않았어요.'}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">기록이 짧아 최종 시험 없이 검증 기간 결과만 있어요. '자세히'에서 볼 수 있습니다.</p>
            )}
          </Card>
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
