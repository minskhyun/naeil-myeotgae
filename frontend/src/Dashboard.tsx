// 로그인 뒤의 분석 결과 화면: 한 매장의 내일 준비를 한눈에.
//   맨 위   날짜 · 준비 기준
//   요약    숫자 네 칸 (준비할 양 · 평소와 다른 메뉴 · 지난주 방식보다 덜 틀린 개수 · 주의할 소식)
//   본문    왼쪽: 메뉴별 준비표      오른쪽: AI 주의 안내 · 예측에 쓴 주변 정보 · 얼마나 맞나
// 자세한 내용(주변 정보 전체, 검증 전체)은 길게 늘어놓지 않고 '자세히'를 누르면 창으로 뜬다.
// 조각들은 기존 화면의 것을 그대로 쓴다 (ForecastView.tsx, BacktestView.tsx, SourcesView.tsx).
import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api } from './api'
import { BacktestView, BarRow } from './BacktestView'
import { ForecastTable, Notice, PrepToggle } from './ForecastView'
import { count, dayWord, fmtDate, fmtTime, GROUP_LABELS, pct1, won } from './format'
import { Modal } from './Modal'
import { SourcesView } from './SourcesView'
import { periodName, verdict } from './verdict'

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
  const day = dayWord(fc.rows[0].date) // 예측 날짜를 부르는 말: 오늘 · 내일 · 이날
  const totalPrep = fc.rows.reduce((sum, r) => sum + (r.prep_qty ?? 0), 0)
  const totalPred = Math.round(fc.rows.reduce((sum, r) => sum + r.pred, 0))
  const effect = (r: (typeof fc.rows)[number]) => r.reasons.reduce((sum, x) => sum + x.effect_pct, 0)
  const more = fc.rows.filter((r) => effect(r) > 0).length
  const less = fc.rows.filter((r) => effect(r) < 0).length
  // 얼마나 맞나: 지난주 같은 요일만큼 준비했을 때 vs 내일몇개 예측대로 준비했을 때 (최종 시험, 없으면 검증 기간)
  const v = verdict(backtest)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="text-sm text-muted">{storeName} · {day} 준비표</p>
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
        <Tile label={`${day} 준비할 양`} value={`${totalPrep}개`} note={`메뉴 ${fc.rows.length}개 · 예상 판매 ${totalPred}개`} />
        <Tile
          label="평소와 다른 메뉴"
          value={`${more + less}개`}
          note={more + less ? `평소보다 많이 ${more}개 · 적게 ${less}개` : '모든 메뉴가 평소와 비슷해요'}
        />
        <Tile
          label="지난주 방식보다 덜 틀린 양"
          value={v ? (v.saved > 0 ? `하루 ${count(v.saved)}개` : '차이 없음') : '–'}
          note={
            v
              ? `남거나 모자란 개수 ${count(v.baseShown)}개 → ${count(v.mineShown)}개${v.money !== null && v.money > 0 ? ` · 판매가로 약 ${won(v.money)}` : ''} · ${periodName(v)} 기준`
              : '검증 결과가 없어요'
          }
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
          <ForecastTable rows={fc.rows} limit={MENUS_SHOWN} compact storeId={storeId} />
          <p className="mt-3 text-xs leading-relaxed text-faint">
            준비 = 고른 준비 기준({prepMode})의 권장 개수 · 예상 범위 = 실제 판매가 들어올 것으로 보는 구간(세로 눈금이 예상값) · 평소와 다른 점 = 날씨·행사가
            평소와 같았을 때의 예측과 비교한 차이 ·
            메뉴를 누르면 그래프와 설명 · {fmtTime(fc.generated_at)}에 계산
          </p>
        </Card>

        <div className="min-w-0 space-y-5">
          <Card title="AI 주의 안내">
            {fc.warnings.length ? (
              <div className="space-y-3">
                <p className="text-xs leading-relaxed text-faint">AI가 읽은 소식이에요. 이 안내 때문에 준비표 숫자가 바뀌지는 않으니, 참고해서 판단해 주세요.</p>
                {fc.warnings.map((w, i) => (
                  <Notice key={i} w={w} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">{day}은 특별히 주의할 소식이 없어요.</p>
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
            <p className="mt-3 text-xs text-faint">지난 기록으로 확인해 예측이 실제로 나아진 정보만 써요.</p>
          </Card>

          <Card title="얼마나 맞나" onMore={() => setDetail('backtest')}>
            {v ? (
              <>
                <BarRow label="지난주 같은 요일만큼" value={v.baseMiss} max={Math.max(v.baseMiss, v.mineMiss)} strong={false} />
                <BarRow label="내일몇개 예측" value={v.mineMiss} max={Math.max(v.baseMiss, v.mineMiss)} strong />
                <p className="mt-3 text-sm text-muted">
                  {periodName(v)} 동안 하루에 남거나 모자란 개수(모든 메뉴 합, 짧을수록 좋음).{' '}
                  {v.gain > 0 ? (
                    <b className="text-ink">
                      지난주만큼 준비할 때보다 하루 {count(v.saved)}개({v.gain}%) 덜 틀려요
                      {v.money !== null && v.money > 0 && `. 판매가로 하루 약 ${won(v.money)}`}.
                    </b>
                  ) : (
                    '지난주만큼 준비하는 것보다 나아지지 않았어요.'
                  )}
                  {v.mine.days_won != null && (
                    <>
                      {' '}
                      {v.days}일 중 <b className="text-ink">{v.mine.days_won}일</b>은 내일몇개가 덜 틀렸어요.
                    </>
                  )}
                </p>
                <p className="mt-3 flex items-baseline justify-between gap-3 border-t border-rule pt-3 text-sm">
                  <span>
                    예상 범위 안에 든 비율 <span className="text-faint">(목표 80%)</span>
                  </span>
                  <b className="text-lg tabular-nums">{pct1(v.mine.coverage_80)}</b>
                </p>
                <p className="mt-1 text-xs text-faint">실제 판매가 예상 범위 안에 들어온 비율이에요. 80%에 가까울수록 범위를 알맞게 잡은 것입니다.</p>
              </>
            ) : (
              <p className="text-sm text-muted">검증 결과가 아직 없어요.</p>
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
