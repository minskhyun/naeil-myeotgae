import { useState, type ReactNode } from 'react'
import { useDropzone } from 'react-dropzone'
import { api } from './api'
import { useJob } from './useJob'

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-t border-rule py-6 sm:grid-cols-[12rem_1fr]">
      <h3 className="font-semibold">
        <span className="mr-2 text-muted tabular-nums">{n}</span>
        {title}
      </h3>
      <div>{children}</div>
    </section>
  )
}

function FileRow({ label, hint, file, onPick, accept, required }: {
  label: string; hint: string; file?: File; onPick: (f: File) => void; accept: Record<string, string[]>; required?: boolean
}) {
  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    accept, multiple: false, noClick: true, onDrop: (files) => files[0] && onPick(files[0]),
  })
  return (
    <div
      {...getRootProps()}
      className={`flex flex-wrap items-center justify-between gap-3 border px-4 py-3 ${
        isDragActive ? 'border-accent bg-accent-soft' : 'border-rule bg-sheet'
      }`}
    >
      <input {...getInputProps()} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {label} {required ? <span className="text-sm font-normal text-up">필수</span> : <span className="text-sm font-normal text-faint">선택</span>}
        </p>
        <p className="text-sm text-muted">{file ? file.name : hint}</p>
      </div>
      <button type="button" onClick={open} className="border border-ink/80 bg-sheet px-3 py-1.5 text-sm hover:bg-paper">
        {file ? '다른 파일' : '파일 고르기'}
      </button>
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
    <div className="max-w-4xl">
      <header className="pb-6">
        <p className="text-sm text-muted">데이터 올리기</p>
        <h2 className="mt-0.5 text-3xl font-bold tracking-tight">판매 기록으로 내일 준비표 만들기</h2>
        <p className="mt-2 text-muted">포스에서 내려받은 파일을 올리면 정리 → 검증 → 내일 예측까지 한 번에 합니다. 1~2분 걸립니다.</p>
      </header>

      <Step n={1} title="매장 정보">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium">매장 ID</span>
            <input value={storeId} onChange={(e) => setStoreId(e.target.value.trim())}
              className="mt-1 w-full border border-rule bg-sheet px-3 py-2 focus:border-ink focus:outline-none" placeholder="seongsu-a" />
            <span className="mt-1 block text-sm text-faint">영어 소문자·숫자·하이픈. 신호 파일의 store_id와 같게</span>
          </label>
          <label className="block">
            <span className="text-sm font-medium">영업 종료 시각</span>
            <input value={closeTime} onChange={(e) => setCloseTime(e.target.value)}
              className="mt-1 w-full border border-rule bg-sheet px-3 py-2 focus:border-ink focus:outline-none" placeholder="21:00" />
            <span className="mt-1 block text-sm text-faint">이 시각까지 공개된 정보만 다음 날 예측에 씁니다</span>
          </label>
        </div>
      </Step>

      <Step n={2} title="파일">
        <div className="space-y-2">
          <FileRow label="POS 판매 기록" hint="엑셀(.xlsx) 또는 CSV — 끌어다 놓아도 됩니다" file={pos} onPick={setPos} required
            accept={{
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
              'application/vnd.ms-excel': ['.xls'],
              'text/csv': ['.csv'],
            }} />
          <FileRow label="주변 정보 신호" hint="signals.json — 날씨·행사" file={signals} onPick={setSignals}
            accept={{ 'application/json': ['.json'], 'text/csv': ['.csv'] }} />
          <FileRow label="행사·뉴스 원문" hint="collection.json — AI 주의 안내에 씀" file={collection} onPick={setCollection}
            accept={{ 'application/json': ['.json'] }} />
        </div>
      </Step>

      <Step n={3} title="실행">
        <div className="flex flex-wrap items-center gap-3">
          <button disabled={!pos || running}
            onClick={() => start(() => api.run(storeId, { pos: pos!, signals, collection }, closeTime))}
            className="bg-accent px-5 py-2.5 font-semibold text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40">
            준비표 만들기
          </button>
          <span className="text-sm text-muted">또는</span>
          <button disabled={running} onClick={() => start(api.demo)}
            className="text-sm underline underline-offset-4 hover:text-accent disabled:opacity-40">
            가상 매장 데이터로 시연
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-up">{error}</p>}
        {job && (
          <div className="mt-5 border border-rule bg-sheet">
            <p className="border-b border-rule px-4 py-2 text-sm font-semibold">
              {job.status === 'running' && '실행 중…'}
              {job.status === 'done' && <span className="text-accent">완료 — '내일 준비표'에서 결과를 보세요</span>}
              {job.status === 'error' && <span className="text-up">실패</span>}
            </p>
            <pre className="overflow-x-auto px-4 py-3 font-mono text-xs leading-relaxed text-muted">
              {job.log.join('\n') || '시작하는 중…'}
              {job.status === 'error' && job.error && `\n\n${job.error}`}
            </pre>
          </div>
        )}
      </Step>
    </div>
  )
}
