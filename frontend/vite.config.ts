import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // 화면(5173)에서 /api 로 부르면 백엔드(8000)로 넘긴다 → 주소를 코드에 적지 않아도 됨
    proxy: { '/api': 'http://localhost:8000' },
  },
})
