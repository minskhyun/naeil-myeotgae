import { useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { api } from './api'
import { useJob } from './useJob'

function FilePick({ label, hint, file, onPick, accept }: {
  label: string; hint: string; file?: File; onPick: (f: File) => void; accept: Record<string, string[]>
}) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept, multiple: false, onDrop: (files) => files[0] && onPick(files[0]),
  })
  return (
    <div
      {...getRootProps()}
      className={`cursor-pointer rounded-2xl border-2 border-dashed p-5 text-center transition ${
        isDragActive ? 'border-orange-400 bg-orange-50' : 'border-stone-300 bg-white hover:border-stone-400'
      }`}
    >
      <input {...getInputProps()} />
      <p className="font-medium text-stone-800">{label}</p>
      <p className="mt-1 text-sm text-stone-500">{file ? `✓ ${file.name}` : hint}</p>
    </div>
  )
}

export function UploadView({ onDone }: { onDone: (storeId: string) => void }) {
  const [storeId, setStoreId] = useState('seongsu-a')
  const [closeTime, setCloseTime] = useState('21:00')
  const [pos, setPos] = useState<File>()
  const [signals, setSignals] = useState<File>()
  const [collection, setCollection] = useState<File>()
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const job = useJob(jobId, onDone)
  const running = job?.status === 'running'

  const start = async (fn: () => Promise<{ job_id: string }>) => {
    setError(null)
    try {
      setJobId((await fn()).job_id)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-stone-900">판매 기록 올리기</h2>
        <p className="mt-1 text-sm text-stone-500">
          포스에서 내려받은 파일을 올리면 정리 → 검증 → 내일 예측까지 한 번에 돌립니다 (1~2분).
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium text-stone-700">매장 ID</span>
          <input
            value={storeId}
            onChange={(e) => setStoreId(e.target.value.trim())}
            className="mt-1 w-full rounded-xl border border-stone-300 bg-white px-3 py-2"
            placeholder="seongsu-a"
          />
          <span className="text-xs text-stone-400">영어 소문자·숫자·하이픈 (신호 파일의 store_id와 같게)</span>
        </label>
        <label className="block text-sm">
          <span className="font-medium text-stone-700">영업 종료 시각</span>
          <input
            value={closeTime}
            onChange={(e) => setCloseTime(e.target.value)}
            className="mt-1 w-full rounded-xl border border-stone-300 bg-white px-3 py-2"
            placeholder="21:00"
          />
          <span className="text-xs text-stone-400">이 시각까지 공개된 정보만 다음 날 예측에 씁니다 (처음 한 번만)</span>
        </label>
      </div>

      <FilePick
        label="POS 판매 기록 (필수)"
        hint="엑셀(.xlsx) 또는 CSV를 끌어다 놓거나 눌러서 고르세요"
        file={pos}
        onPick={setPos}
        accept={{
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
          'application/vnd.ms-excel': ['.xls'],
          'text/csv': ['.csv'],
        }}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <FilePick label="주변 정보 신호 (선택)" hint="signals.json" file={signals} onPick={setSignals}
          accept={{ 'application/json': ['.json'], 'text/csv': ['.csv'] }} />
        <FilePick label="행사·뉴스 원문 (선택)" hint="collection.json → AI 주의 안내" file={collection} onPick={setCollection}
          accept={{ 'application/json': ['.json'] }} />
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          disabled={!pos || running}
          onClick={() => start(() => api.run(storeId, { pos: pos!, signals, collection }, closeTime))}
          className="rounded-xl bg-orange-500 px-5 py-2.5 font-semibold text-white hover:bg-orange-600 disabled:opacity-40"
        >
          예측 돌리기
        </button>
        <button
          disabled={running}
          onClick={() => start(api.demo)}
          className="rounded-xl border border-stone-300 bg-white px-5 py-2.5 font-medium text-stone-700 hover:bg-stone-100 disabled:opacity-40"
        >
          가상 매장으로 시연
        </button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}
      {job && (
        <div className="rounded-2xl bg-stone-900 p-4 font-mono text-xs leading-relaxed text-stone-100">
          <p className="mb-2 font-sans text-sm font-semibold">
            {job.status === 'running' && '⏳ 실행 중…'}
            {job.status === 'done' && '✓ 완료 — 예측 탭에서 결과를 보세요'}
            {job.status === 'error' && '✕ 실패'}
          </p>
          {job.log.map((l, i) => (
            <p key={i} className="whitespace-pre-wrap">{l}</p>
          ))}
          {job.status === 'error' && job.error && <p className="mt-2 text-rose-300">{job.error}</p>}
        </div>
      )}
    </div>
  )
}
