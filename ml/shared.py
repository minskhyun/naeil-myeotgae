"""다른 매장과 함께 배우기: 내 매장 기록에 '함께 배우기'를 켠 다른 매장의 기록을 더해 한 모델이 배운다.

왜
  가게 한 곳의 기록에는 큰 행사나 기념일 같은 드문 일이 1년에 몇 번뿐이다. 여러 매장의 줄을 함께 보면 그런 사례가 늘고,
  기록이 짧은 새 매장도 다른 매장에서 배운 요일·날씨·행사 규칙을 바로 쓸 수 있다.

어떻게 섞나
  - 학습용 표는 (매장 × 메뉴 × 날짜)마다 한 줄이다. 메뉴가 열이 아니라 줄이라서, 메뉴 구성이 다른 매장의 줄도
    그대로 이어 붙일 수 있다 (pooled). 목표가 '평소 대비 비율'이라 큰 가게와 작은 가게도 같은 단위다.
  - 내 매장 줄의 무게는 1, 다른 매장 줄은 PARTNER_WEIGHT. 공통 규칙은 함께 배우되 내 가게 기록을 더 믿는다.
  - 쓸지는 검증이 정한다: 내 기록만으로 배운 모델보다 지난 기록에서 실제로 나을 때만 (evaluate.run_backtest).
  - 시점 규칙은 그대로다: 검증·예측 날짜보다 앞선 줄만 학습에 쓰인다. 다른 매장의 줄도 날짜로 걸러진다.

누구와 섞나
  run.py가 정한다: 이 매장이 '함께 배우기'를 켰을 때만, 같은 설정을 켠 다른 매장과 (store.json의 share_learning).
  한쪽만 켠 매장의 기록은 쓰이지 않는다. 다른 매장의 판매 기록 자체는 누구에게도 보이지 않는다.

한계
  메뉴 이름이 다르면('아이스 아메리카노' vs '아메리카노(ICE)') 그 메뉴 고유의 성질은 옮겨 가지 않는다 (공통 규칙만 공유).
"""
import pandas as pd

from ml.features import SIGNAL_GROUPS, available_signals, build_frame

PARTNER_WEIGHT = 0.5     # 다른 매장 줄 하나의 무게 (내 매장 줄 = 1)
MAX_PARTNERS = 20        # 함께 배울 매장 수 상한 (학습 시간이 매장 수만큼 늘어나므로)

# 함께 배울 매장 하나: (판매 기록, 신호 또는 None, 영업 종료 시각)
Partner = tuple[pd.DataFrame, pd.DataFrame | None, str]


def pooled(frame: pd.DataFrame, partners: list[Partner], signal_names: list[str]) -> pd.DataFrame:
    """내 매장의 학습용 표 + 다른 매장들의 표 → 한 표. 'weight' 열이 붙는다 (내 줄 1, 다른 매장 줄 PARTNER_WEIGHT).
    다른 매장에 없는 신호는 빈 값으로 남는다 (모델이 '모름'으로 다룬다)."""
    parts = [frame.assign(weight=1.0)]
    for sales, signals, close_time in partners:
        have = set(available_signals(SIGNAL_GROUPS, signals)) if signals is not None else set()
        names = [n for n in signal_names if n in have]
        part = build_frame(sales, signals if names else None, names, close_time=close_time)
        parts.append(part.assign(weight=PARTNER_WEIGHT))
    return pd.concat(parts, ignore_index=True)


def mine(table: pd.DataFrame, store_id: str) -> pd.DataFrame:
    """여러 매장이 섞인 표(예측표 등)에서 내 매장 줄만."""
    return table[table["store_id"] == store_id].reset_index(drop=True)
