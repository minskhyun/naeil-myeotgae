// '내 매장' 화면 (로그인한 사람만): 내가 만든 매장을 보고, 이름을 바꾸고, 판매 기록을 다시 올리고, 지운다.
// 서버 쪽은 backend/app/main.py의 /api/my/stores, 권한 규칙은 backend/app/auth.py.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type MyStore } from './api'
import { fmtTime } from './format'

const LINK = 'underline underline-offset-4 hover:text-accent disabled:opacity-40'

// 매장의 지금 상태를 한 줄로
function status(s: MyStore) {
  if (s.running) return <span className="text-accent">계산 중…</span>
  if (s.ready && s.updated_at) return <>준비표 있음 · {fmtTime(s.updated_at)} 계산</>
  return <span className="text-faint">아직 준비표 없음 (판매 기록을 올려 주세요)</span>
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
  const [editing, setEditing] = useState<string | null>(null) // 이름을 고치는 중인 매장
  const [draft, setDraft] = useState('')
  const [asking, setAsking] = useState<string | null>(null) // 지울지 한 번 더 묻는 중인 매장
  const [error, setError] = useState<string | null>(null)

  // 서버에 요청하고, 끝나면 내 매장 목록과 위쪽 매장 고르기를 새로 받는다
  const act = async (work: () => Promise<unknown>) => {
    setError(null)
    try {
      await work()
      setEditing(null)
      setAsking(null)
      await Promise.all([qc.invalidateQueries({ queryKey: ['myStores'] }), qc.invalidateQueries({ queryKey: ['stores'] })])
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="max-w-4xl">
      <header className="flex flex-wrap items-end justify-between gap-4 pb-6">
        <div>
          <p className="text-sm text-muted">내 매장</p>
          <h2 className="mt-0.5 text-3xl font-bold tracking-tight">내 매장 관리</h2>
          <p className="mt-2 text-muted">여기 있는 매장과 그 자료(올린 판매 기록, 결과)는 로그인한 본인만 볼 수 있습니다.</p>
        </div>
        <button onClick={() => onUpload(null)} className="bg-accent px-4 py-2 font-semibold text-white hover:bg-accent/90">
          새 매장 추가
        </button>
      </header>

      {error && <p className="mb-4 border-l-4 border-up bg-sheet px-4 py-3 text-sm">{error}</p>}
      {stores.data && !stores.data.length && (
        <p className="border-t border-rule py-6 text-muted">아직 매장이 없습니다. '새 매장 추가'에서 판매 기록을 올리면 여기에 나타납니다.</p>
      )}

      <ul className="border-t border-rule">
        {stores.data?.map((s) => (
          <li key={s.store_id} className="grid gap-x-6 gap-y-2 border-b border-rule py-4 sm:grid-cols-[1fr_auto]">
            <div className="min-w-0">
              {editing === s.store_id ? (
                <form
                  className="flex flex-wrap items-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault()
                    act(() => api.renameStore(s.store_id, draft.trim()))
                  }}
                >
                  <input
                    autoFocus
                    value={draft}
                    maxLength={40}
                    onChange={(e) => setDraft(e.target.value)}
                    aria-label="매장 이름"
                    className="min-w-0 flex-1 border border-rule bg-sheet px-2 py-1 focus:border-ink focus:outline-none"
                  />
                  <button type="submit" disabled={!draft.trim()} className={`text-sm ${LINK}`}>
                    저장
                  </button>
                  <button type="button" onClick={() => setEditing(null)} className={`text-sm text-muted ${LINK}`}>
                    취소
                  </button>
                </form>
              ) : (
                <p className="font-semibold">
                  {s.name}
                  {!s.mine && <span className="ml-2 text-sm font-normal text-faint">다른 사람 또는 주인 없는 매장 (관리자에게만 보임)</span>}
                </p>
              )}
              <p className="mt-0.5 text-sm text-muted">
                {s.address ?? '주소 없음'} · 영업 종료 {s.close_time}
              </p>
              <p className="mt-0.5 text-sm">{status(s)}</p>
            </div>

            {asking === s.store_id ? (
              <div className="flex flex-wrap items-center gap-3 text-sm sm:justify-end">
                <span className="text-up">올린 판매 기록과 결과가 모두 지워지고 되돌릴 수 없습니다.</span>
                <button onClick={() => act(() => api.deleteStore(s.store_id))} className="bg-up px-3 py-1.5 font-semibold text-white">
                  지우기
                </button>
                <button onClick={() => setAsking(null)} className={LINK}>
                  취소
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm sm:justify-end">
                {s.ready && (
                  <button onClick={() => onOpen(s.store_id)} className={LINK}>
                    준비표 보기
                  </button>
                )}
                <button onClick={() => onUpload(s.store_id)} disabled={s.running} className={LINK}>
                  판매 기록 올리기
                </button>
                <button
                  onClick={() => {
                    setDraft(s.name)
                    setEditing(s.store_id)
                  }}
                  className={LINK}
                >
                  이름 바꾸기
                </button>
                <button onClick={() => setAsking(s.store_id)} disabled={s.running} className={`text-up ${LINK}`}>
                  지우기
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
