import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api } from './api'

// 실행 작업(예측 돌리기)의 상태를 0.8초마다 물어보고, 끝나면 화면의 데이터를 새로 받는다.
export function useJob(jobId: string | null, onDone?: (storeId: string) => void) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.job(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === 'running' || !q.state.data ? 800 : false),
  })
  const status = query.data?.status
  const storeId = query.data?.store_id
  useEffect(() => {
    if (status === 'done' && storeId) {
      qc.invalidateQueries({ queryKey: ['stores'] })
      qc.invalidateQueries({ queryKey: ['myStores'] })
      qc.invalidateQueries({ queryKey: ['forecast', storeId] })
      qc.invalidateQueries({ queryKey: ['backtest', storeId] })
      qc.invalidateQueries({ queryKey: ['sources', storeId] })
      qc.invalidateQueries({ queryKey: ['progress', storeId] })
      onDone?.(storeId)
    }
    // onDone은 매번 새로 만들어지므로 상태가 바뀔 때만 실행한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, storeId, qc])
  return query.data
}
