// 판매 입력: 파일을 다시 올리지 않고 하루치 판매 수량을 메뉴마다 적어 덧붙인다 → 그 기록까지 넣어 다시 분석한다.
// 기본은 여전히 파일 올리기다. 이 창은 '어제 올린 기록 뒤에 오늘 것만 더할 때' 쓰는 작은 길이다.
//   - 적을 수 있는 날: 올린 파일의 마지막 날짜 뒤 ~ 오늘 (서버가 한 번 더 확인한다: main.add_sales)
//   - 같은 날을 다시 적으면 그날 것을 바꾼다. 나중에 그 날짜가 든 새 파일을 올리면 파일의 기록을 쓴다 (ml/ingest.merge_added)
//   - 메뉴는 지금 준비표에 있는 메뉴다. 새 메뉴는 파일로 올린다
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from './api'
import { count } from './format'

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const nextDay = (day: string) => {
  const d = new Date(`${day}T00:00:00`)
  d.setDate(d.getDate() + 1)
  return iso(d)
}

export function SalesEntry({ storeId, onStarted }: { storeId: string; onStarted: (jobId: string) => void }) {
  const forecast = useQuery({ queryKey: ['forecast', storeId], queryFn: () => api.forecast(storeId) }).data
  const history = useQuery({ queryKey: ['history', storeId], queryFn: () => api.history(storeId), retry: false }).data
  const last = history?.dates[history.dates.length - 1] ?? null // 마지막 판매 기록 날짜
  const today = iso(new Date())
  const first = last ? nextDay(last) : today // 적을 수 있는 첫 날
  const [picked, setDate] = useState<string | null>(null)
  const date = picked ?? (first > today ? today : first)
  const [qty, setQty] = useState<Record<string, string>>({})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const menus = forecast?.rows.map((r) => r.menu) ?? []
  const total = menus.reduce((sum, m) => sum + (Number(qty[m]) || 0), 0)

  const send = async () => {
    setSending(true)
    setError(null)
    try {
      const items = menus.map((menu) => ({ menu, qty: Math.max(0, Math.round(Number(qty[menu]) || 0)) }))
      onStarted((await api.addSales(storeId, date, items)).job_id)
    } catch (e) {
      setError((e as Error).message)
      setSending(false)
    }
  }

  return (
    <div className="p-6 sm:p-10">
      <h2 className="text-h2">판매 입력</h2>
      <p className="mt-2 text-ink-700">그날 팔린 수량을 적으면, 올린 기록 뒤에 덧붙여 다시 예측해요. 팔리지 않은 메뉴는 비워 두세요.</p>

      <label className="mt-8 block w-fit">
        <span className="text-label">판매한 날</span>
        <input type="date" value={date} min={last ? first : undefined} max={today} onChange={(e) => setDate(e.target.value)} className="field mt-1 block" />
      </label>
      {last && <p className="mt-2 text-sm text-ink-500">지금 기록은 {last}까지 있어요. 그 뒤 날짜를 적을 수 있습니다.</p>}

      <div className="mt-8 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {menus.map((m) => (
          <label key={m} className="flex items-center justify-between gap-4">
            <span className="min-w-0 truncate font-medium">{m}</span>
            <span className="flex shrink-0 items-center gap-2">
              <input
                type="number"
                inputMode="numeric"
                min={0}
                placeholder="0"
                value={qty[m] ?? ''}
                onChange={(e) => setQty({ ...qty, [m]: e.target.value })}
                className="field w-24 text-right"
              />
              <span className="text-sm text-ink-500">개</span>
            </span>
          </label>
        ))}
      </div>
      {!forecast && <p className="mt-8 text-ink-700">메뉴를 불러오는 중…</p>}

      {error && <p className="mt-6 rounded-lg bg-down-soft px-4 py-3 text-sm font-medium text-down">{error}</p>}
      <div className="mt-8 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
        <p className="text-ink-700">
          합계 <strong className="text-lg font-semibold text-ink-900">{count(total)}개</strong>
        </p>
        <button onClick={send} disabled={sending || !total} className="btn-xl btn-primary disabled:opacity-40">
          {sending ? '보내는 중…' : '저장하고 다시 예측하기'}
        </button>
      </div>
    </div>
  )
}
