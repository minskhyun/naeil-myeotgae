// 첫 화면(Landing.tsx)과 소개(About.tsx)가 함께 쓰는 것: 보여 줄 예시 매장, 자주 묻는 질문.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

// 보여 줄 예시 매장. 없으면 목록의 첫 매장.
// 판매 기록은 1년치 가상 데이터(data/sample/campus-a: 실제 신촌의 날씨·학사일정·행사로 만든 것)이고,
// 주변 정보는 실제 주소(연세로)로 분석을 돌려 모은 실제 자료다 (기사·행사의 원문 링크가 실제 글로 간다).
export const FIRST_EXAMPLE = 'sinchon-a'

// 예시 매장과 그 매장을 분석했을 때의 과정(녹화본). 주소에 ?store=매장ID 를 붙이면 다른 예시 매장
export function useExample() {
  const stores = useQuery({ queryKey: ['stores'], queryFn: api.stores })
  const examples = stores.data?.filter((s) => s.demo) ?? []
  const picked = new URLSearchParams(window.location.search).get('store')
  const store = examples.find((s) => s.store_id === picked) ?? examples.find((s) => s.store_id === FIRST_EXAMPLE) ?? examples[0]
  const past = useQuery({
    queryKey: ['progress', store?.store_id],
    queryFn: () => api.progress(store!.store_id),
    enabled: !!store,
    retry: false,
  }).data
  return { stores, store, past }
}

// 자주 묻는 질문. 지금 실제로 되는 것만 적는다 (아직 없는 것은 없다고 적는다)
export const FAQ = [
  {
    q: '판매 기록은 얼마나 있어야 하나요?',
    a: '최소 3주(21일)치가 필요해요. 5주가 넘으면 마지막 1주를 따로 떼어 한 번 더 확인하고, 기록이 길수록 날씨·행사 같은 주변 정보의 효과를 더 잘 가려냅니다.',
  },
  {
    q: '어떤 파일을 올리면 되나요?',
    a: '포스나 매출 프로그램에서 내려받은 엑셀(.xlsx)·CSV 파일이면 됩니다. 날짜, 메뉴 이름, 수량 열만 있으면 읽어요. 토스 포스·OKPOS의 열 이름과 "상품별 매출" 엑셀(달마다 시트가 나뉜 것 포함)을 알아봅니다.',
  },
  {
    q: '결과는 어디서 보나요?',
    a: '지금은 이 웹 화면에서 봅니다. 판매 기록을 올리면 1~2분 뒤에 내일 준비표가 나와요. 포스 자동 연동과 카카오톡으로 매일 받아 보기는 아직 없고, 다음 단계로 계획하고 있습니다.',
  },
  {
    q: '주변 정보는 무조건 예측에 들어가나요?',
    a: '아니요. 가게마다 지난 기록으로 확인해서, 넣었을 때 예측이 실제로 더 정확해진 정보만 씁니다. 도움이 안 되면 쓰지 않고, 왜 안 썼는지도 보여 드려요.',
  },
  {
    q: '예측이 틀리면요?',
    a: '예측은 숫자 하나가 아니라 범위로 보여 드리고, 가게마다 지난 기록에서 얼마나 맞았는지를 그대로 공개합니다. 폐기를 줄일지 품절을 줄일지(준비 기준)는 사장님이 고릅니다.',
  },
  {
    q: '메뉴가 바뀌면요?',
    a: '최근 14일 동안 팔리지 않은 메뉴는 준비표에서 자동으로 빠지고, 새 메뉴는 판매 기록이 쌓이면 들어옵니다.',
  },
  {
    q: '카페·베이커리가 아니어도 되나요?',
    a: '메뉴별 하루 판매 기록이 있으면 돌아가지만, 지금까지 확인한 곳은 카페와 베이커리입니다.',
  },
  {
    q: '가격은 얼마인가요?',
    a: '아직 정하지 않았습니다. 지금은 시연 단계입니다.',
  },
]
