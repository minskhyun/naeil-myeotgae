// 분석 화면(Workspace.tsx)의 '매장 관리' 탭 (로그인한 사람만): 내가 만든 매장의 이름·주소·닫는 시간을 고치고,
// 판매 기록을 다시 올리고, 매장을 지운다. 새 매장은 '매장 추가' 버튼으로 (창이 뜬다).
// 주소와 닫는 시간은 예측의 재료라서, 고친 것은 다음에 분석할 때부터 반영된다.
// 서버 쪽은 backend/app/main.py의 /api/my/stores, 권한 규칙은 backend/app/auth.py.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type MyStore } from './api'
import { fmtTime } from './format'
import { ArrowLink } from './Site'

const LINK = 'underline underline-offset-4 hover:text-ink-900 disabled:opacity-40'

// 매장의 지금 상태를 한 줄로
function status(s: MyStore) {
  if (s.running) return '계산 중…'
  if (s.ready && s.updated_at) return `준비표 있음 · ${fmtTime(s.updated_at)} 계산`
  return '아직 준비표 없음 (판매 기록을 올려 주세요)'
}

// 매장 하나: 고칠 수 있는 칸 셋(이름 · 주소 · 닫는 시간)과 할 수 있는 일들
function StoreCard({ s, onOpen, onUpload, onChanged }: {
  s: MyStore
  onOpen: (storeId: string) => void
  onUpload: (storeId: string) => void
  onChanged: () => Promise<unknown>
}) {
  // 손대기 전에는 저장된 값을 보여 준다
  const [name, setName] = useState<string | null>(null)
  const [address, setAddress] = useState<string | null>(null)
  const [closeTime, setCloseTime] = useState<string | null>(null)
  const [asking, setAsking] = useState(false) // 지울지 한 번 더 묻는 중
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const now = { name: name ?? s.name, address: address ?? s.address ?? '', close_time: closeTime ?? s.close_time }
  const dirty = now.name !== s.name || now.address !== (s.address ?? '') || now.close_time !== s.close_time
  const moved = now.address !== (s.address ?? '') || now.close_time !== s.close_time // 예측에 영향을 주는 칸을 바꿨는가

  const act = async (work: () => Promise<unknown>, done?: () => void) => {
    setError(null)
    try {
      await work()
      await onChanged()
      done?.()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const save = () =>
    act(
      () => api.updateStore(s.store_id, now),
      () => {
        setName(null)
        setAddress(null)
        setCloseTime(null)
        setSaved(true)
      },
    )
  const touch = <T,>(set: (v: T) => void) => (v: T) => {
    set(v)
    setSaved(false)
  }

  return (
    <li className="rounded-[32px] bg-white p-6 sm:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="text-h3">
          {s.name}
          {!s.mine && <span className="ml-2 text-sm font-normal text-ink-500">다른 사람 또는 주인 없는 매장 (관리자에게만 보임)</span>}
        </h3>
        <p className="text-sm text-ink-500">{status(s)}</p>
      </div>

      <form
        className="mt-6 grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <label className="block">
          <span className="text-sm font-medium">매장 이름</span>
          <input value={now.name} maxLength={40} onChange={(e) => touch(setName)(e.target.value)} className="field mt-1 w-full" />
        </label>
        <label className="block">
          <span className="text-sm font-medium">닫는 시간</span>
          <input type="time" value={now.close_time} onChange={(e) => touch(setCloseTime)(e.target.value)} className="field mt-1 w-full" />
        </label>
        <label className="block sm:col-span-2">
          <span className="text-sm font-medium">매장 위치 (주소)</span>
          <input value={now.address} maxLength={200} onChange={(e) => touch(setAddress)(e.target.value)} className="field mt-1 w-full" placeholder="서울 성동구 서울숲2길 12-7" />
          <span className="mt-1 block text-sm text-ink-500">이 위치의 날씨와 근처 행사를 찾습니다. 비워 두면 판매 기록만으로 예측합니다</span>
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <button type="submit" disabled={!dirty || !now.name.trim() || !now.close_time} className="btn-md btn-primary">
            저장
          </button>
          {dirty && moved && <span className="text-sm text-ink-500">주소와 닫는 시간은 다음에 분석할 때부터 반영돼요.</span>}
          {saved && !dirty && <span className="text-sm text-up">저장했어요.</span>}
        </div>
      </form>
      {error && <p className="mt-3 text-sm text-down">{error}</p>}

      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-5 text-sm">
        {asking ? (
          <>
            <span className="text-down">올린 판매 기록과 결과가 모두 지워지고 되돌릴 수 없습니다.</span>
            <button onClick={() => act(() => api.deleteStore(s.store_id))} className="btn-md bg-down text-white">
              지우기
            </button>
            <button onClick={() => setAsking(false)} className={LINK}>
              취소
            </button>
          </>
        ) : (
          <>
            {s.ready && (
              <button onClick={() => onOpen(s.store_id)} className={LINK}>
                준비표 보기
              </button>
            )}
            <button onClick={() => onUpload(s.store_id)} disabled={s.running} className={LINK}>
              판매 기록 올리고 분석하기
            </button>
            <button onClick={() => setAsking(true)} disabled={s.running} className={`ml-auto text-down ${LINK}`}>
              매장 지우기
            </button>
          </>
        )}
      </div>
    </li>
  )
}

export function StoresView({ onOpen, onUpload }: {
  onOpen: (storeId: string) => void // 그 매장의 준비표 보기
  onUpload: (storeId: string | null) => void // 판매 기록 올리기 (null = 새 매장)
}) {
  const qc = useQueryClient()
  const stores = useQuery({
    queryKey: ['myStores'],
    queryFn: api.myStores,
    refetchInterval: (q) => (q.state.data?.some((s) => s.running) ? 3000 : false), // 계산 중인 매장이 있으면 다시 물어본다
  })
  // 바뀐 뒤에는 내 매장 목록과 옆의 매장 고르기를 새로 받는다
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['myStores'] }), qc.invalidateQueries({ queryKey: ['stores'] })])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <div>
          <p className="font-mono text-sm text-ink-500">Stores</p>
          <h2 className="mt-3 text-h1">매장 관리</h2>
          <p className="mt-3 text-ink-700">여기 있는 매장과 그 자료(올린 판매 기록, 결과)는 로그인한 본인만 볼 수 있습니다.</p>
        </div>
        <ArrowLink onClick={() => onUpload(null)} dark>
          매장 추가
        </ArrowLink>
      </div>

      {stores.data && !stores.data.length && (
        <p className="rounded-[32px] bg-white p-8 text-ink-700">아직 매장이 없습니다. '매장 추가'를 눌러 판매 기록을 올리면 여기에 나타납니다.</p>
      )}
      <ul className="space-y-5">
        {stores.data?.map((s) => (
          <StoreCard key={s.store_id} s={s} onOpen={onOpen} onUpload={onUpload} onChanged={refresh} />
        ))}
      </ul>
    </div>
  )
}
