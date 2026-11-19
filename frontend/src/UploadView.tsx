import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useDropzone } from 'react-dropzone'
import { api } from './api'

const POS_TYPES = {
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls'],
  'text/csv': ['.csv'],
}
const NEW = 'new' // 매장 고르기에서 '새 매장 만들기'
const INPUT = 'mt-1 w-full rounded-xl border border-rule bg-sheet px-3.5 py-2.5 focus:border-accent focus:outline-none'

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

// 입력 한 칸: 이름 · 입력 · 설명. type="time"이면 시각만 고를 수 있는 칸 (값은 "21:00" 형식)
function Field({ label, hint, value, onChange, placeholder, wide, type = 'text' }: {
  label: string; hint: string; value: string; onChange: (v: string) => void; placeholder?: string; wide?: boolean; type?: 'text' | 'time'
}) {
  return (
    <label className={`block ${wide ? 'sm:col-span-2' : ''}`}>
      <span className="text-sm font-medium">{label}</span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} placeholder={placeholder} />
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
      className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border-2 border-dashed px-4 py-4 ${
        isDragActive ? 'border-accent bg-accent-soft' : 'border-rule bg-paper'
      }`}
    >
      <input {...getInputProps()} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">POS 판매 기록</p>
        <p className="text-sm text-muted">
          {file ? file.name : '토스포스·OKPOS에서 내려받은 CSV 또는 엑셀(.xlsx) — 끌어다 놓아도 됩니다'}
        </p>
      </div>
      <button type="button" onClick={open} className="rounded-full border border-rule bg-sheet px-4 py-1.5 text-sm font-semibold hover:bg-paper">
        {file ? '다른 파일' : '파일 고르기'}
      </button>
    </div>
  )
}

// 판매 기록을 올려 준비표를 만드는 창 (Workspace.tsx가 Modal 안에 띄운다). 세 가지 경우가 있다.
//   계정 방식 + 새 매장   : '매장 추가' — 매장 이름, 위치, 닫는 시간, 판매 기록 파일 (매장 ID는 서버가 지어 준다)
//   계정 방식 + 있는 매장 : 그 매장의 판매 기록 다시 올리기 ('매장 관리'에서 누르고 온 경우, initialTarget)
//   로그인을 안 쓰는 서버 : 매장 ID를 직접 적는다 (혼자 쓰는 노트북용, 가상 매장 시연 단추도 여기만)
// first: 아직 매장이 하나도 없는 사람에게 처음 보여 주는 경우 (환영 문구)
// onStarted: 실행이 시작되면 작업 번호를 Workspace에 넘긴다 → 이 창은 닫히고 '분석 중' 화면(AnalysisView)이 뜬다
// busy: 다른 분석이 아직 돌고 있다 (끝날 때까지 새로 시작할 수 없다)
export function UploadView({ onStarted, busy = false, account = false, initialTarget = null, first = false }: {
  onStarted: (jobId: string) => void
  busy?: boolean
  account?: boolean
  initialTarget?: string | null
  first?: boolean
}) {
  const qc = useQueryClient()
  const mine = useQuery({ queryKey: ['myStores'], queryFn: api.myStores, enabled: account }).data ?? []
  const [target, setTarget] = useState(initialTarget ?? NEW) // 계정 방식: 올릴 매장 (NEW = 새로 만들기)
  const isNew = account && target === NEW
  const chosen = mine.find((s) => s.store_id === target)
  const [name, setName] = useState('') // 새 매장 이름
  const [storeId, setStoreId] = useState('seongsu-a') // 로그인 없는 방식: 직접 적는 매장 ID
  // 위치·닫는 시간: 손대기 전에는 그 매장에 저장된 값을 보여 준다
  const [typedClose, setCloseTime] = useState<string | null>(null)
  const [typedAddress, setAddress] = useState<string | null>(null)
  const closeTime = typedClose ?? chosen?.close_time ?? '21:00'
  const address = typedAddress ?? chosen?.address ?? ''
  const [pos, setPos] = useState<File>()
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false) // 파일을 보내는 중

  // 실행 요청을 보내고, 돌려받은 작업 번호를 Workspace에 넘긴다 (거기서 분석 화면을 띄우고 진행을 지켜본다)
  const start = async (request: () => Promise<{ job_id: string }>) => {
    setError(null)
    setSending(true)
    try {
      onStarted((await request()).job_id)
    } catch (e) {
      setError((e as Error).message)
      setSending(false)
    }
  }
  const running = busy || sending

  // 준비표 만들기: 새 매장이면 먼저 매장을 만들어 ID를 받고, 그 매장에 파일을 올린다
  const run = async () => {
    const opts = { closeTime, address: address.trim() }
    if (!account) return api.run(storeId, pos!, opts)
    let id = target
    if (id === NEW) {
      id = (await api.createStore(name.trim(), closeTime)).store_id
      setTarget(id) // 올리기가 실패해 다시 눌러도 매장을 또 만들지 않게
      qc.invalidateQueries({ queryKey: ['myStores'] })
    }
    return api.run(id, pos!, opts)
  }

  const label = !account ? '데이터 올리기' : isNew ? '매장 추가' : '판매 기록 다시 올리기'
  const title = !account
    ? '판매 기록으로 내일 준비표 만들기'
    : isNew
      ? first ? '첫 매장을 추가해 주세요' : '새 매장 추가'
      : `${chosen?.name ?? '이 매장'}의 판매 기록 다시 올리기`

  return (
    <div className="max-w-4xl">
      <header className="pb-6">
        <p className="text-sm text-muted">{label}</p>
        <h2 className="mt-0.5 text-3xl font-bold tracking-tight">{title}</h2>
        <p className="mt-2 text-muted">
          {account && !isNew
            ? '새 판매 기록으로 이 매장의 결과를 다시 만듭니다. 위치나 닫는 시간이 바뀌었으면 여기서 고쳐 주세요. 몇 분 걸립니다.'
            : '포스에서 내려받은 파일 하나면 됩니다. 날씨·행사·뉴스 같은 주변 정보는 매장 위치로 저희가 찾아 붙입니다. 몇 분 걸립니다.'}
        </p>
      </header>

      <Step n={1} title="매장 정보">
        <div className="grid gap-4 sm:grid-cols-2">
          {isNew && (
            <Field wide label="매장 이름" value={name} onChange={setName} placeholder="우리 빵집 성수점"
              hint="화면에 보이는 이름입니다. '매장 관리'에서 언제든 바꿀 수 있습니다" />
          )}
          <Field wide label="매장 위치 (주소)" value={address} onChange={setAddress} placeholder="서울 성동구 서울숲2길 12-7"
            hint="이 위치의 날씨와 근처 행사를 찾습니다. 비워 두면 판매 기록만으로 예측합니다" />
          {!account && (
            <Field label="매장 ID" value={storeId} onChange={(v) => setStoreId(v.trim())} placeholder="seongsu-a"
              hint="영어 소문자·숫자·하이픈. 같은 ID로 다시 올리면 그 매장의 결과가 새로 만들어집니다" />
          )}
          <Field type="time" label="닫는 시간" value={closeTime} onChange={setCloseTime}
            hint="이 시각까지 공개된 정보만 다음 날 예측에 씁니다" />
        </div>
      </Step>

      <Step n={2} title="판매 기록 파일">
        <PosFile file={pos} onPick={setPos} />
      </Step>

      <Step n={3} title="분석">
        <div className="flex flex-wrap items-center gap-3">
          <button disabled={!pos || running || !closeTime || (isNew && !name.trim())} onClick={() => start(run)}
            className="rounded-full bg-accent px-7 py-3 font-bold text-white hover:bg-accent-deep disabled:cursor-not-allowed disabled:opacity-40">
            {sending ? '보내는 중…' : '분석 및 예측하기'}
          </button>
          {!account && (
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
        {busy && <p className="mt-3 text-sm text-muted">다른 분석이 아직 진행 중입니다. 끝난 뒤에 시작할 수 있어요.</p>}
      </Step>
    </div>
  )
}
