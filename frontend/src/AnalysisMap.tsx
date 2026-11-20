// 분석 중 화면의 지도: 알림(ProgressEvent)이 하나씩 들어올 때마다 지도 위에 그린다.
//   매장으로 날아가 내려앉고 → 주변 시설이 점으로 돋아나고 → 찾은 정보가 빛줄기가 되어 가게로 들어온다.
// 지도는 Leaflet + OpenStreetMap (키 없이 씀). 표시의 모양·움직임은 index.css의 nm-… 클래스.
// React가 그리는 것이 아니라 Leaflet에 직접 그리므로, 어디까지 그렸는지(drawn)를 따로 센다.
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import type { ProgressEvent } from './api'
import { KIND_COLOR } from './format'

type Spot = [number, number] // [위도, 경도]

const SEOUL: Spot = [37.5512, 126.9882]
// 위치가 없는 정보가 들어오는 방향: 가게 기준으로 [북쪽으로 몇 도, 동쪽으로 몇 도] 떨어진 곳에서 출발
const EDGE: Record<string, Spot> = {
  weather: [0.0075, -0.002],
  academic: [-0.0062, -0.0095],
  special: [0.0045, -0.0115],
  trend: [0.002, 0.0118],
  sales: [-0.0072, 0.003],
  article: [0.0068, 0.0085],
}

// 배경용(ambient) 지도에서 위치 없는 정보의 이름표가 뜨는 자리: 칸의 [가로, 세로] 비율. 가운데 글을 피해 가장자리에 둔다
const AMBIENT_SLOTS: Record<string, [number, number]> = {
  weather: [0.1, 0.2],
  academic: [0.88, 0.22],
  special: [0.08, 0.55],
  trend: [0.91, 0.52],
  sales: [0.15, 0.8],
  article: [0.85, 0.78],
}
const AMBIENT_ZOOM = 17 // 배경용은 더 가까이 본다 (주변 시설의 점이 화면 가득 퍼지게)
const AMBIENT_STORE_Y = 0.86 // 배경용에서 가게가 놓이는 세로 위치 (가운데 글 아래)

const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

// 화면 위치가 정해진 HTML 표시 (크기 0인 자리 표시에 안쪽 요소를 올린다)
const mark = (at: Spot, html: string, z = 0) =>
  L.marker(at, { icon: L.divIcon({ className: '', html, iconSize: [0, 0] }), interactive: false, zIndexOffset: z })

// 두 점을 잇는 휜 선 (가운데가 옆으로 부풀어 오른다)
function curve(from: Spot, to: Spot): Spot[] {
  const mid: Spot = [(from[0] + to[0]) / 2 + (to[1] - from[1]) * 0.22, (from[1] + to[1]) / 2 - (to[0] - from[0]) * 0.22]
  return Array.from({ length: 25 }, (_, i) => {
    const t = i / 24
    return [
      (1 - t) ** 2 * from[0] + 2 * (1 - t) * t * mid[0] + t ** 2 * to[0],
      (1 - t) ** 2 * from[1] + 2 * (1 - t) * t * mid[1] + t ** 2 * to[1],
    ] as Spot
  })
}

// ambient = 첫 화면 머리의 배경으로 쓸 때: 만질 수 없고(끌기·확대 없음, 페이지 스크롤을 가로채지 않는다),
//           가게로 날아가지 않고 처음부터 가게 둘레를 보여 주며, 다 그린 뒤에도 주변의 점에서 빛줄기가 계속 들어온다.
export function AnalysisMap({ events, ambient = false }: { events: ProgressEvent[]; ambient?: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const store = useRef<{ at: Spot; pin: L.Marker } | null>(null)
  const drawn = useRef(0)
  const spots = useRef<Spot[]>([]) // 지도에 찍은 점들 (배경용에서 빛줄기가 출발할 곳)

  // 지도 만들기 (한 번). 처음에는 서울 전체를 보여 주다가, 매장 위치를 알게 되면 날아간다
  useEffect(() => {
    const still = ambient ? { dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false, boxZoom: false, keyboard: false } : {}
    const m = L.map(box.current!, { center: SEOUL, zoom: 11, zoomControl: false, attributionControl: true, ...still })
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap',
    }).addTo(m)
    map.current = m
    drawn.current = 0
    store.current = null
    spots.current = []
    const resized = new ResizeObserver(() => m.invalidateSize()) // 칸 크기가 바뀌면 지도도 다시 맞춘다
    resized.observe(box.current!)
    return () => {
      resized.disconnect()
      m.remove()
      map.current = null
    }
  }, [ambient])

  // 새로 들어온 알림만 그린다
  useEffect(() => {
    const m = map.current
    if (!m) return

    // 정보가 가게로 들어오는 빛줄기. 도착하면 가게 표시가 한 번 꿀꺽한다
    const flow = (from: Spot, color: string) => {
      const s = store.current
      if (!s) return
      const path = curve(from, s.at)
      const trail = L.polyline(path, { className: 'nm-trail nm-fading', color, interactive: false }).addTo(m)
      window.setTimeout(() => trail.remove(), 4000) // 지나간 자국은 잠시 뒤 지운다 (지도가 선으로 덮이지 않게)
      const beam = L.polyline(path, { className: 'nm-flow', color, interactive: false }).addTo(m)
      beam.getElement()?.setAttribute('pathLength', '100')
      window.setTimeout(() => {
        beam.remove()
        const el = s.pin.getElement()?.firstElementChild
        el?.classList.remove('gulp')
        void (el as HTMLElement | undefined)?.offsetWidth // 같은 움직임을 다시 틀려면 한 번 끊어 줘야 한다
        el?.classList.add('gulp')
      }, 1250)
    }
    // 위치가 없는 정보: 지도 가장자리에 이름표가 잠깐 뜨고 거기서 들어온다
    const fromEdge = (kind: string, label: string) => {
      const s = store.current
      if (!s) return
      let at: Spot
      if (ambient) {
        const [fx, fy] = AMBIENT_SLOTS[kind] ?? AMBIENT_SLOTS.article
        const size = m.getSize()
        const p = m.containerPointToLatLng([size.x * (fx + (Math.random() - 0.5) * 0.05), size.y * (fy + (Math.random() - 0.5) * 0.08)])
        at = [p.lat, p.lng]
      } else {
        const [dLat, dLon] = EDGE[kind] ?? EDGE.article
        at = [s.at[0] + dLat * (0.85 + Math.random() * 0.3), s.at[1] + dLon * (0.85 + Math.random() * 0.3)]
      }
      const chip = mark(at, `<div class="nm-chip" style="--c:${KIND_COLOR[kind]}">${escapeHtml(label)}</div>`, 500).addTo(m)
      window.setTimeout(() => chip.remove(), 2700)
      flow(at, KIND_COLOR[kind])
    }
    const pin = (at: Spot, color: string, label: string) =>
      mark(at, `<div class="nm-pin" style="--c:${color}"><u></u><i></i><span>${escapeHtml(label)}</span></div>`, 300).addTo(m)

    for (const e of events.slice(drawn.current)) {
      if (e.kind === 'store' && e.lat && e.lon) {
        const at: Spot = [e.lat, e.lon]
        const html = `<div class="nm-store"><u></u><u></u><i></i><span>${escapeHtml(e.name)}</span></div>`
        store.current = { at, pin: mark(at, html, 1000).addTo(m) }
        if (ambient) {
          // 가게가 칸의 아래쪽(AMBIENT_STORE_Y)에 오도록, 그만큼 위쪽을 지도의 가운데로 잡는다
          const center = m.project(at, AMBIENT_ZOOM).subtract([0, (AMBIENT_STORE_Y - 0.5) * m.getSize().y])
          m.setView(m.unproject(center, AMBIENT_ZOOM), AMBIENT_ZOOM, { animate: false })
        } else m.flyTo(at, 15, { duration: 1.8 })
      } else if (e.kind === 'places') {
        e.places.forEach((p, i) => {
          const html = `<i class="nm-dot" style="--c:${KIND_COLOR.places};animation-delay:${i * 18}ms"></i>`
          mark([p.lat, p.lon], html).addTo(m)
          spots.current.push([p.lat, p.lon])
        })
      } else if (e.kind === 'plan') {
        if (store.current && e.radius_m) {
          L.circle(store.current.at, { radius: e.radius_m, className: 'nm-trail', color: KIND_COLOR.plan, fill: false, interactive: false }).addTo(m)
        }
        e.picks.forEach((p, i) =>
          window.setTimeout(() => {
            pin([p.lat, p.lon], KIND_COLOR.plan, p.name)
            flow([p.lat, p.lon], KIND_COLOR.plan)
          }, i * 260),
        )
      } else if (e.kind === 'event') {
        const color = e.source === '뉴스·블로그' ? KIND_COLOR.news : KIND_COLOR.event
        pin([e.lat, e.lon], color, e.title)
        flow([e.lat, e.lon], color)
      } else if (e.kind === 'weather') fromEdge('weather', `날씨 ${e.days}일`)
      else if (e.kind === 'academic') fromEdge('academic', e.exams ? `시험 기간 ${e.exams}번 · 방학 ${e.vacations ?? 0}번` : `학교 일정 ${e.days}일`)
      else if (e.kind === 'special') fromEdge('special', e.name)
      else if (e.kind === 'trend_span') fromEdge('trend', `검색량 ${e.days}일치`)
      else if (e.kind === 'trend') fromEdge('trend', `${e.menu} 검색 ${e.pct > 0 ? '+' : ''}${e.pct}%`)
      else if (e.kind === 'sales') fromEdge('sales', `판매 기록 ${e.days}일`)
      else if (e.kind === 'article') fromEdge('article', '소식 읽는 중')
    }
    drawn.current = events.length

    // 배경용: 다 그린 뒤에도 살아 있게, 주변의 점 하나에서 가게로 빛줄기를 가끔 보낸다
    if (!ambient) return
    const timer = window.setInterval(() => {
      const from = spots.current[Math.floor(Math.random() * spots.current.length)]
      if (from) flow(from, KIND_COLOR.places)
    }, 1100)
    return () => window.clearInterval(timer)
  }, [events, ambient])

  return <div ref={box} className={`nm-map h-full w-full ${ambient ? 'nm-map-ambient' : ''}`} />
}
