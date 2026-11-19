import { useQuery } from '@tanstack/react-query'
import { api } from './api'

// 지금 로그인한 사람 (로그인을 안 쓰는 서버면 묻지 않는다). 로그인·로그아웃 뒤에는 Auth.tsx가 새로 받게 한다.
export function useMe(enabled: boolean) {
  return useQuery({ queryKey: ['me'], queryFn: api.me, enabled })
}
