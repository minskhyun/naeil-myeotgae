import { useState, type ReactNode } from 'react'
import { useDropzone } from 'react-dropzone'
import { api } from './api'
import { useJob } from './useJob'

const POS_TYPES = {
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls'],
  'text/csv': ['.csv'],
}
const INPUT = 'mt-1 w-full border border-rule bg-sheet px-3 py-2 focus:border-ink focus:outline-none'

// 번호가 붙은 단계 한 칸: 왼쪽에 제목, 오른쪽에 내용
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

// 글자 입력 한 칸: 이름 · 입력 · 설명
function Field({ label, hint, value, onChange, placeholder, wide }: {
  label: string; hint: string; value: string; onChange: (v: string) => void; placeholder: string; wide?: boolean
}) {
  return (
    <label className={`block ${wide ? 'sm:col-span-2' : ''}`}>
      <span className="text-sm font-medium">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} placeholder={placeholder} />
      <span className="mt-1 block text-sm text-faint">{hint}</span>
    </label>
  )
}

// POS 파일 고르기 (끌어다 놓기 가능)
function PosFile({ file, onPick }: { file?: File; onPick: (f: File) => void }) {
  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    accept: POS_TYPES, multiple: false, noClick: true, onDrop: (files) => files[0] && onPick(files[0]),
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
        <p className="font-medium">POS 판매 기록</p>
        <p className="text-sm text-muted">
          {file ? file.name : '토스포스·OKPOS에서 내려받은 엑셀(.xlsx) 또는 CSV — 끌어다 놓아도 됩니다'}
        </p>
      </div>
      <button type="button" onClick={open} className="border border-ink/80 bg-sheet px-3 py-1.5 text-sm hover:bg-paper">
        {file ? '다른 파일' : '파일 고르기'}
      </button>
    </div>
  )
}

// canDemo: '가상 매장 데이터로 시연'을 보여 줄지 (로그인을 쓰는 서버에서는 관리자만 시연 매장을 다시 계산할 수 있다)
export function UploadView({ onDone, canDemo = true }: { onDone: (storeId: string) => void; canDemo?: boolean }) {
  const [storeId, setStoreId] = useState('seongsu-a')
  const [closeTime, setCloseTime] = useState('21:00')
  const [address, setAddress] = useState('')
  const [pos, setPos] = useState<File>()
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const job = useJob(jobId, onDone)
  const running = job?.status === 'running'

  // 실행 요청을 보내고, 돌려받은 작업 번호로 진행 상황을 지켜본다
  const start = async (request: () => Promise<{ job_id: string }>) => {
    setError(null)
    try {
      setJobId((await request()).job_id)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="max-w-4xl">
      <header className="pb-6">
        <p className="text-sm text-muted">데이터 올리기</p>
        <h2 className="mt-0.5 text-3xl font-bold tracking-tight">판매 기록으로 내일 준비표 만들기</h2>
        <p className="mt-2 text-muted">
          포스에서 내려받은 파일 하나면 됩니다. 날씨·행사·뉴스 같은 주변 정보는 매장 주소로 저희가 찾아 붙입니다. 몇 분 걸립니다.
        </p>
      </header>

      <Step n={1} title="매장 정보">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field wide label="매장 주소" value={address} onChange={setAddress} placeholder="서울 성동구 서울숲2길 12-7"
            hint="이 위치의 날씨와 근처 행사를 찾습니다. 비워 두면 판매 기록만으로 예측합니다" />
          <Field label="매장 ID" value={storeId} onChange={(v) => setStoreId(v.trim())} placeholder="seongsu-a"
            hint="영어 소문자·숫자·하이픈. 같은 ID로 다시 올리면 그 매장의 결과가 새로 만들어집니다" />
          <Field label="영업 종료 시각" value={closeTime} onChange={setCloseTime} placeholder="21:00"
            hint="이 시각까지 공개된 정보만 다음 날 예측에 씁니다" />
        </div>
      </Step>

      <Step n={2} title="판매 기록">
        <PosFile file={pos} onPick={setPos} />
      </Step>

      <Step n={3} title="실행">
        <div className="flex flex-wrap items-center gap-3">
          <button disabled={!pos || running}
            onClick={() => start(() => api.run(storeId, pos!, { closeTime, address: address.trim() }))}
            className="bg-accent px-5 py-2.5 font-semibold text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-40">
            준비표 만들기
          </button>
          {canDemo && (
            <>
              <span className="text-sm text-muted">또는</span>
              <button disabled={running} onClick={() => start(api.demo)}
                className="text-sm underline underline-offset-4 hover:text-accent disabled:opacity-40">
                가상 매장 데이터로 시연
              </button>
            </>
          )}
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
