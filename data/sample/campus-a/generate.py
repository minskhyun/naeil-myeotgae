# -*- coding: utf-8 -*-
"""
campus-a (연세로 베이커리카페, 가상 매장) POS 시뮬레이터.

이 파일 하나로 아래 세 산출물을 매번 같은 바이트로 다시 만든다.
  - pos_raw.csv  : POS 내보내기 (판매일자, 상품명, 수량, 판매금액)
  - truth.json   : 날짜별 잠재 요인(정답) 기록
  - truth.md     : 생성 모형 설명 + 점검 통계

설계 원칙
  * "평균 × 요인별 배수"가 아니라 "누가(고객층) 왜(방문 목적) 왔는가"에서 출발한다.
    방문 건수 = 고객층 10개 × 방문 목적 5개 행렬이고, 요일·학사·휴일·날씨·행사가
    이 행렬의 칸마다 다르게 작용한다. 품목 판매량은 방문 목적별 장바구니에서 나온다.
  * 실제 공개 자료(drivers/ 폴더의 날씨·학사일정·문화행사)를 그대로 읽어 쓴다.
  * 예측 모델 쪽 코드는 전혀 보지 않고, 효과 크기는 캠퍼스 상권 카페의 일반 상식으로 정했다.
  * 표준 라이브러리 + numpy + pandas 만 쓴다. 난수 씨앗은 고정이다.
"""
import csv
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DRV = os.path.join(HERE, "drivers")
SEED = 20261119
START = dt.date(2025, 11, 1)
END = dt.date(2026, 11, 17)


def D(s):
    return dt.date.fromisoformat(s)


def sig(x):
    return 1.0 / (1.0 + math.exp(-x))


def clip(x, lo, hi):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# 1. 고객층(세그먼트)과 방문 목적(미션)
# ---------------------------------------------------------------------------
SEGS = ["yonsei", "sogang", "ewha", "staff", "hospital", "office",
        "resident", "visitor", "tourist", "academy"]
SEG_LABEL = {
    "yonsei": "연세대 학부·대학원생",
    "sogang": "서강대 학생",
    "ewha": "이화여대 학생(신촌으로 놀러 오는 수요)",
    "staff": "대학 교직원·연구원",
    "hospital": "세브란스병원 직원·환자 보호자",
    "office": "신촌 일대 직장인·상인",
    "resident": "인근 거주자(자취생·오피스텔 주민)",
    "visitor": "약속·데이트·영화·공연으로 신촌에 온 방문객",
    "tourist": "외국인 관광객·어학당 수강생",
    "academy": "신촌 어학원·자격증 학원 수강생",
}
MISSIONS = ["commute", "lunch", "study", "social", "bakery_run"]
MIS_LABEL = {
    "commute": "등굣길·출근길 테이크아웃",
    "lunch": "식후 커피",
    "study": "카공·과제",
    "social": "약속·수다·데이트",
    "bakery_run": "빵·디저트 포장 구매",
}
# 학기 중 평범한 평일(요일 지수 1.0)의 방문(결제) 건수
BASE = {"yonsei": 78, "sogang": 16, "ewha": 7, "staff": 22, "hospital": 20,
        "office": 24, "resident": 18, "visitor": 32, "tourist": 9, "academy": 12}
# 고객층별 방문 목적 비중 (합 = 1)
MIX = {
    "yonsei":   [0.30, 0.22, 0.22, 0.20, 0.06],
    "sogang":   [0.10, 0.20, 0.25, 0.40, 0.05],
    "ewha":     [0.00, 0.00, 0.20, 0.70, 0.10],
    "staff":    [0.40, 0.45, 0.00, 0.05, 0.10],
    "hospital": [0.40, 0.25, 0.00, 0.10, 0.25],
    "office":   [0.35, 0.50, 0.00, 0.05, 0.10],
    "resident": [0.10, 0.10, 0.20, 0.20, 0.40],
    "visitor":  [0.00, 0.15, 0.00, 0.65, 0.20],
    "tourist":  [0.00, 0.15, 0.00, 0.55, 0.30],
    "academy":  [0.40, 0.15, 0.35, 0.05, 0.05],
}
STUDENTS = ("yonsei", "sogang", "ewha")

# 요일 리듬 (월..일). 방문 목적마다 다르다.
_STU = {
    "commute":    [1.00, 1.05, 1.05, 1.00, 0.78, 0.05, 0.03],  # 금요일 공강이 흔하다
    "lunch":      [1.00, 1.05, 1.05, 1.00, 0.82, 0.14, 0.08],
    "study":      [1.00, 1.00, 1.00, 1.00, 0.85, 0.65, 0.70],
    "social":     [0.90, 0.95, 1.00, 1.05, 1.15, 0.60, 0.40],
    "bakery_run": [1.00, 1.00, 1.00, 1.00, 1.00, 0.50, 0.40],
}


def _flat(v):
    return {m: v for m in MISSIONS}


DOWP = {
    "yonsei": _STU,
    "sogang": _STU,
    "ewha": _flat([0.90, 0.90, 1.00, 1.00, 1.30, 0.90, 0.60]),
    "staff": _flat([1.00, 1.00, 1.00, 1.00, 0.97, 0.08, 0.03]),
    "hospital": _flat([1.00, 1.03, 1.00, 1.00, 1.00, 0.50, 0.25]),  # 토요일 오전 외래
    "office": _flat([1.00, 1.00, 1.00, 1.00, 1.03, 0.28, 0.18]),
    "resident": {
        "commute":    [1.00, 1.00, 1.00, 1.00, 1.00, 0.30, 0.20],
        "lunch":      [1.00, 1.00, 1.00, 1.00, 1.00, 1.20, 1.20],
        "study":      [0.85, 0.85, 0.90, 0.90, 1.05, 1.45, 1.40],
        "social":     [0.85, 0.85, 0.90, 0.90, 1.05, 1.45, 1.40],
        "bakery_run": [0.85, 0.85, 0.90, 0.90, 1.05, 1.45, 1.40],
    },
    "visitor": _flat([0.62, 0.66, 0.72, 0.82, 1.15, 2.25, 1.75]),
    "tourist": _flat([0.90, 0.90, 0.95, 1.00, 1.10, 1.35, 1.25]),
    "academy": _flat([1.00, 1.00, 1.00, 1.00, 0.90, 0.60, 0.25]),
}
# 평일 공휴일에 어느 요일 리듬을 따르는가: 수업·근무에 묶인 층은 일요일, 놀러 오는 층은 토요일
HOLIDAY_DOW = {"yonsei": 6, "sogang": 6, "ewha": 5, "staff": 6, "hospital": 6,
               "office": 6, "resident": 5, "visitor": 5, "tourist": 5, "academy": 6}

# 날씨 민감도 (고객층 × 방문 목적). 꼭 와야 하는 방문일수록 날씨를 덜 탄다.
W_SEG = {"yonsei": 0.9, "sogang": 0.9, "ewha": 1.1, "staff": 0.6, "hospital": 0.55,
         "office": 0.7, "resident": 1.0, "visitor": 1.25, "tourist": 1.0, "academy": 0.7}
W_RAIN_MIS = {"commute": 0.25, "lunch": 0.55, "study": 0.60, "social": 1.00, "bakery_run": 0.90}
W_TEMP_MIS = {"commute": 0.20, "lunch": 0.50, "study": 0.30, "social": 1.00, "bakery_run": 0.90}

# ---------------------------------------------------------------------------
# 2. 메뉴
# ---------------------------------------------------------------------------
AME_H, AME_I = "아메리카노(HOT)", "아메리카노(ICE)"
LAT_H, LAT_I = "카페라떼(HOT)", "카페라떼(ICE)"
CHOCO, ADE, STRAW, WMELON, MATCHA = "초코라떼", "자몽에이드", "생딸기라떼", "수박주스", "말차라떼"
SALT, CROI, SCONE, SAND = "소금빵", "크루아상", "플레인스콘", "햄치즈샌드위치"
CAKE, COOKIE = "바스크치즈케이크", "르뱅쿠키"
ITEMS = [AME_H, AME_I, LAT_H, LAT_I, CHOCO, ADE, STRAW, WMELON, MATCHA,
         SALT, CROI, SCONE, SAND, CAKE, COOKIE]
FAMILY = {AME_H: "coffee", AME_I: "coffee", LAT_H: "coffee", LAT_I: "coffee",
          CHOCO: "noncoffee", ADE: "noncoffee", STRAW: "noncoffee", WMELON: "noncoffee",
          MATCHA: "noncoffee", SALT: "bakery", CROI: "bakery", SCONE: "bakery",
          SAND: "bakery", CAKE: "dessert", COOKIE: "dessert"}
FAMILIES = ["coffee", "noncoffee", "bakery", "dessert"]
# 정가 이력 (적용 시작일, 가격)
PRICE = {
    AME_H: [("2025-01-01", 4500), ("2026-02-02", 4800)],
    AME_I: [("2025-01-01", 4500), ("2026-02-02", 4800)],
    LAT_H: [("2025-01-01", 5000), ("2026-02-02", 5300)],
    LAT_I: [("2025-01-01", 5000), ("2026-02-02", 5300)],
    CHOCO: [("2025-01-01", 5500)],
    ADE: [("2025-01-01", 6000)],
    STRAW: [("2025-01-01", 6500)],
    WMELON: [("2025-01-01", 6500)],
    MATCHA: [("2025-01-01", 5800)],
    SALT: [("2025-01-01", 3200), ("2026-07-01", 3500)],
    CROI: [("2025-01-01", 3800)],
    SCONE: [("2025-01-01", 3500)],
    SAND: [("2025-01-01", 6800)],
    CAKE: [("2025-01-01", 6500)],
    COOKIE: [("2025-01-01", 3800)],
}
COFFEE_PRICE_UP = D("2026-02-02")   # 원두값 인상분 반영 (+300원)
SALT_PRICE_UP = D("2026-07-01")     # 버터값 인상분 반영 (+300원)
# 판매 가능 기간 (없으면 전 기간 판매)
AVAIL = {
    STRAW: (D("2025-12-05"), D("2026-04-26")),    # 딸기 철 한정
    WMELON: (D("2026-06-05"), D("2026-09-06")),   # 여름 한정
    MATCHA: (D("2026-03-23"), None),              # 기간 중 신메뉴
    SCONE: (None, D("2026-06-28")),               # 기간 중 단종
}
ITEM_NOTE = {
    AME_H: "기본 커피. 추울수록 비중이 커진다.",
    AME_I: "최다 판매 품목. 한겨울에도 학생층은 3~4할이 아이스를 고른다.",
    LAT_H: "추운 날·직장인·병원 고객 비중이 높다.",
    LAT_I: "따뜻한 계절에 HOT 라떼를 대체한다.",
    CHOCO: "커피를 안 마시는 손님용. 추울수록 잘 팔린다.",
    ADE: "연중 판매하지만 기온에 가장 민감한 여름 음료.",
    STRAW: "겨울~봄 딸기 철 한정. 2~3월이 정점.",
    WMELON: "여름 한정. 더운 날에만 잘 팔리고 수박 손질량만큼만 판다.",
    MATCHA: "2026-03-23 출시 신메뉴. 출시 직후 반짝 인기 뒤 안정.",
    SALT: "간판 빵. 하루 굽는 양이 정해져 있어 자주 품절된다.",
    CROI: "꾸준한 빵. 인기는 아주 천천히 줄어든다.",
    SCONE: "인기가 계속 줄어 2026-06-28 을 끝으로 단종.",
    SAND: "아침·점심 대용. 아침에 만든 수량만 판다.",
    CAKE: "약속·데이트 손님이 주로 주문. 홀케이크 1판 = 8조각 단위로 준비.",
    COOKIE: "카공·테이크아웃 손님 간식. 시험 기간·기념일에 강하다.",
}

# 방문 1건당 수량
DPV = {"commute": 1.00, "lunch": 1.45, "study": 1.15, "social": 2.10, "bakery_run": 0.30}  # 음료
BPV = {"commute": 0.28, "lunch": 0.12, "study": 0.20, "social": 0.30, "bakery_run": 2.30}  # 빵
DSV = {"commute": 0.03, "lunch": 0.08, "study": 0.14, "social": 0.40, "bakery_run": 0.30}  # 디저트
# 음료 중 커피 비중
CS = {"commute": 0.92, "lunch": 0.82, "study": 0.80, "social": 0.60, "bakery_run": 0.70}
CS_OFF = {"yonsei": 0.0, "sogang": 0.0, "ewha": -0.05, "staff": 0.05, "hospital": 0.0,
          "office": 0.04, "resident": -0.02, "visitor": -0.05, "tourist": -0.08, "academy": 0.03}
# 커피 안에서 아메리카노 비중 (나머지는 라떼)
AW = {"yonsei": 0.72, "sogang": 0.72, "ewha": 0.62, "staff": 0.66, "hospital": 0.60,
      "office": 0.70, "resident": 0.60, "visitor": 0.58, "tourist": 0.50, "academy": 0.75}
# 아이스 선호를 체감기온 몇 도만큼 옮기는가 (+ 는 아이스 쪽)
T_SHIFT = {"yonsei": 3.0, "sogang": 3.0, "ewha": 3.0, "staff": -3.0, "hospital": -4.0,
           "office": -1.0, "resident": -2.0, "visitor": 1.0, "tourist": 0.0, "academy": 3.0}
BAFF = {"yonsei": 0.90, "sogang": 0.90, "ewha": 1.00, "staff": 1.00, "hospital": 1.25,
        "office": 1.00, "resident": 1.25, "visitor": 1.10, "tourist": 1.30, "academy": 0.85}
DAFF = {"yonsei": 0.95, "sogang": 0.95, "ewha": 1.20, "staff": 0.80, "hospital": 1.00,
        "office": 0.80, "resident": 1.00, "visitor": 1.20, "tourist": 1.20, "academy": 0.80}
# 논커피 취향 (초코, 에이드, 딸기, 수박, 말차)
TASTE = {
    "yonsei":   [0.9, 1.1, 1.1, 1.0, 1.1],
    "sogang":   [0.9, 1.1, 1.1, 1.0, 1.1],
    "ewha":     [0.9, 1.1, 1.3, 1.0, 1.3],
    "staff":    [0.8, 0.8, 0.7, 0.8, 0.8],
    "hospital": [1.1, 0.8, 0.8, 0.9, 0.7],
    "office":   [0.8, 0.9, 0.8, 0.9, 0.9],
    "resident": [1.2, 0.9, 1.0, 1.0, 0.8],
    "visitor":  [1.0, 1.1, 1.3, 1.1, 1.2],
    "tourist":  [0.9, 1.0, 1.5, 1.1, 1.5],
    "academy":  [0.9, 1.0, 0.9, 0.9, 0.9],
}
NC_ITEMS = [CHOCO, ADE, STRAW, WMELON, MATCHA]
HEAT_THIRST = 0.12   # 폭염일(최고 35도 이상)에 방문 1건당 음료가 12% 는다
NC_NONE = 0.70   # "마실 만한 논커피가 없다"는 선택지의 무게
# 빵 품목 선택 무게 (소금빵, 크루아상, 스콘, 샌드위치)
BK_ITEMS = [SALT, CROI, SCONE, SAND]
BW = {
    "commute":    [0.38, 0.20, 0.12, 0.30],
    "lunch":      [0.25, 0.15, 0.10, 0.50],
    "study":      [0.34, 0.18, 0.26, 0.22],
    "social":     [0.46, 0.28, 0.20, 0.06],
    "bakery_run": [0.56, 0.25, 0.14, 0.05],
}
# 디저트 선택 무게 (케이크, 쿠키)
DW = {"commute": [0.2, 0.8], "lunch": [0.4, 0.6], "study": [0.3, 0.7],
      "social": [0.7, 0.3], "bakery_run": [0.45, 0.55]}

# 하루 준비량(상한)이 있는 품목: (한 번에 만드는 단위, 점주의 여유율)
CAPPED = {
    SALT: (6, 1.15), CROI: (4, 1.30), SCONE: (4, 1.35), SAND: (2, 1.22),
    CAKE: (8, 1.34), COOKIE: (6, 1.50), STRAW: (5, 1.45), WMELON: (6, 1.40),
}
BREADS = [SALT, CROI, SCONE]
BREAD_SPILL = 0.35   # 품절된 빵 수요 중 다른 빵으로 옮겨 가는 비율
CAKE_SPILL = 0.25    # 케이크 품절 시 쿠키로 옮겨 가는 비율

# ---------------------------------------------------------------------------
# 3. 달력에 박아 둔 사건들
# ---------------------------------------------------------------------------
CLOSURES = {
    "2026-01-22": "수도 동파로 임시 휴무 (실제 한파일: 최저 -13.2도)",
    "2026-02-16": "설 연휴 휴무 (설 전날)",
    "2026-02-17": "설 연휴 휴무 (설 당일)",
    "2026-06-29": "종강 직후 설비 점검·에어컨 교체로 휴무",
    "2026-07-27": "점주 여름휴가",
    "2026-07-28": "점주 여름휴가",
    "2026-07-29": "점주 여름휴가",
    "2026-09-24": "추석 연휴 휴무 (추석 전날)",
    "2026-09-25": "추석 연휴 휴무 (추석 당일)",
}
SHORT_HOURS = {"2026-01-01": (0.75, "신정 단축 영업(12~20시)")}
# 할인 행사: (시작, 끝, {품목: 할인액}, {품목: 수요 배수}, 설명)
PROMOS = [
    ("2025-12-05", "2025-12-07", {STRAW: 600}, {STRAW: 1.25}, "생딸기라떼 출시 기념 600원 할인"),
    ("2026-03-03", "2026-03-06", {AME_H: 1000, AME_I: 1000},
     {AME_H: 1.28, AME_I: 1.28, LAT_H: 0.94, LAT_I: 0.94}, "개강맞이 아메리카노 1,000원 할인"),
    ("2026-04-20", "2026-04-26", {COOKIE: 500}, {COOKIE: 1.35}, "중간고사 응원 르뱅쿠키 500원 할인"),
    ("2026-07-20", "2026-07-26", {ADE: 1000}, {ADE: 1.30}, "여름방학 자몽에이드 1,000원 할인"),
    ("2026-09-01", "2026-09-04", {AME_H: 1000, AME_I: 1000},
     {AME_H: 1.28, AME_I: 1.28, LAT_H: 0.94, LAT_I: 0.94}, "개강맞이 아메리카노 1,000원 할인"),
]
# 기념일·학교 행사. source:
#   fixed   = 해마다 날짜가 같은 기념일
#   file    = drivers/events.json 에 있는 실제 일정
#   assumed = 일반 상식으로 넣었고 날짜는 확인하지 못한 일정
# seg: {(고객층, 방문목적 또는 '*'): 배수}, item: {품목: 배수}
SPECIALS = [
    ("2025-11-10", "2025-11-10", "빼빼로데이 전날", "fixed", {}, {COOKIE: 1.15}),
    ("2025-11-11", "2025-11-11", "빼빼로데이", "fixed",
     {("yonsei", "social"): 1.05, ("sogang", "social"): 1.05}, {COOKIE: 1.35, CHOCO: 1.10}),
    ("2026-11-10", "2026-11-10", "빼빼로데이 전날", "fixed", {}, {COOKIE: 1.15}),
    ("2026-11-11", "2026-11-11", "빼빼로데이", "fixed",
     {("yonsei", "social"): 1.05, ("sogang", "social"): 1.05}, {COOKIE: 1.35, CHOCO: 1.10}),
    ("2025-11-13", "2025-11-13", "수능 당일 저녁 수험생 유입", "assumed", {("visitor", "*"): 1.12}, {}),
    ("2025-11-14", "2025-11-14", "수능 다음 날", "assumed", {("visitor", "*"): 1.10}, {}),
    ("2025-11-15", "2025-11-16", "수능 직후 주말 + 서강대 논술고사(학부모 대기)", "assumed",
     {("visitor", "*"): 1.20}, {}),
    ("2025-12-20", "2025-12-22", "크리스마스 앞둔 케이크 수요", "fixed", {}, {CAKE: 1.15}),
    ("2025-12-23", "2025-12-23", "크리스마스 이틀 전", "fixed", {("visitor", "*"): 1.10}, {CAKE: 1.5}),
    ("2025-12-24", "2025-12-24", "크리스마스이브", "fixed", {("visitor", "*"): 1.45},
     {CAKE: 2.2, COOKIE: 1.3, STRAW: 1.25}),
    ("2025-12-25", "2025-12-25", "크리스마스", "fixed", {("visitor", "*"): 1.40},
     {CAKE: 2.0, COOKIE: 1.2, STRAW: 1.25}),
    ("2025-12-26", "2025-12-30", "연말 모임", "fixed", {("visitor", "*"): 1.08}, {}),
    ("2025-12-31", "2025-12-31", "한 해 마지막 날 저녁", "fixed", {("visitor", "*"): 1.15}, {}),
    ("2026-02-13", "2026-02-13", "밸런타인데이 전날", "fixed", {}, {COOKIE: 1.30, CHOCO: 1.15}),
    ("2026-02-14", "2026-02-14", "밸런타인데이", "fixed", {("visitor", "*"): 1.15},
     {COOKIE: 1.50, CAKE: 1.30, CHOCO: 1.25}),
    ("2026-02-23", "2026-02-23", "연세대 학위수여식(가족 방문)", "assumed",
     {("visitor", "*"): 1.35}, {CAKE: 1.30}),
    ("2026-03-13", "2026-03-13", "화이트데이 전날", "fixed", {}, {COOKIE: 1.20}),
    ("2026-03-14", "2026-03-14", "화이트데이", "fixed", {("visitor", "*"): 1.10},
     {COOKIE: 1.40, CAKE: 1.30}),
    ("2026-05-14", "2026-05-15", "서강대 개교기념 축제", "file",
     {("sogang", "lunch"): 0.85, ("sogang", "study"): 0.70, ("sogang", "social"): 1.10}, {}),
    ("2026-05-27", "2026-05-29", "연세대 무악대동제", "assumed",
     {("yonsei", "social"): 1.15, ("yonsei", "study"): 0.80, ("visitor", "*"): 1.08}, {}),
    ("2026-05-30", "2026-05-30", "연세대 아카라카(토요일 응원제)", "assumed",
     {("yonsei", "*"): 2.00, ("visitor", "*"): 1.15}, {ADE: 1.15}),
    ("2026-08-28", "2026-08-28", "연세대 후기 학위수여식", "assumed", {("visitor", "*"): 1.15}, {}),
    ("2026-09-14", "2026-09-18", "서강문화제", "file",
     {("sogang", "lunch"): 0.85, ("sogang", "study"): 0.70, ("sogang", "social"): 1.10}, {}),
    ("2026-09-18", "2026-09-18", "정기 연고전 첫날(학생들이 경기장으로 이동)", "assumed",
     {("yonsei", "commute"): 0.60, ("yonsei", "lunch"): 0.60, ("yonsei", "study"): 0.60}, {}),
    ("2026-09-19", "2026-09-19", "정기 연고전 둘째 날 저녁 신촌 뒤풀이", "assumed",
     {("yonsei", "social"): 1.40}, {}),
    ("2026-10-10", "2026-10-10", "연세대 수시 논술고사(학부모 대기)", "assumed",
     {("visitor", "*"): 1.30}, {}),
    ("2026-10-30", "2026-10-30", "핼러윈 전날", "fixed", {("visitor", "*"): 1.06}, {}),
    ("2026-10-31", "2026-10-31", "핼러윈", "fixed", {("visitor", "*"): 1.10}, {}),
]
# 공개 자료에 없는 운영 사고 (가상의 사건)
INCIDENTS = {
    "2026-03-10": ("에스프레소 머신 고장(오후)",
                   {AME_H: 0.5, AME_I: 0.5, LAT_H: 0.5, LAT_I: 0.5, CHOCO: 1.15, ADE: 1.15, STRAW: 1.15}, {}),
    "2026-04-14": ("오븐 고장 1일차", {}, {SALT: 0.45, CROI: 0.45, SCONE: 0.45, COOKIE: 0.5}),
    "2026-04-15": ("오븐 고장 2일차", {}, {SALT: 0.45, CROI: 0.45, SCONE: 0.45, COOKIE: 0.5}),
    "2026-08-06": ("폭염 중 제빙기 고장", {AME_I: 0.6, LAT_I: 0.6, ADE: 0.6, WMELON: 0.6}, {}),
}
COMPETITOR_OPEN = D("2026-05-18")     # 근처에 저가 커피 매장 개업 (가상)
CONSTRUCTION = (D("2026-03-16"), D("2026-03-27"))   # 매장 앞 보도 정비 공사 (가상)
VIRAL_START = D("2026-05-08")         # 소금빵이 SNS 에서 화제 (가상)
EVENT_SIZE = {"축제-문화/예술": 0.45, "축제-자연/경관": 0.25, "콘서트": 0.10, "연극": 0.05,
              "무용": 0.05, "전시/미술": 0.02, "교육/체험": 0.05}
EVENT_DIST_SCALE = 250.0   # 거리 감쇠: exp(-거리/250m)
TOURIST_MONTH = {1: 0.70, 2: 0.75, 3: 0.95, 4: 1.20, 5: 1.25, 6: 1.00,
                 7: 1.10, 8: 1.10, 9: 1.10, 10: 1.30, 11: 1.00, 12: 0.90}
ANNUAL_GROWTH = 0.05     # 단골이 쌓이면서 매장 전체가 연 5% 성장

# 잡음 크기 (로그 표준편차)
SD_DAY = 0.040
SD_AR, RHO_AR = 0.025, 0.70
SD_RW = 0.003
SD_SEG = {"yonsei": 0.07, "sogang": 0.10, "ewha": 0.15, "staff": 0.08, "hospital": 0.10,
          "office": 0.08, "resident": 0.10, "visitor": 0.12, "tourist": 0.20, "academy": 0.12}
SD_FAM = {"coffee": 0.03, "noncoffee": 0.06, "bakery": 0.05, "dessert": 0.07}
SD_ITEM = 0.05
SD_POP_RW = 0.003
NB_K = 250.0
HABIT_MISSIONS = ("commute", "lunch")


# ---------------------------------------------------------------------------
# 4. 공개 자료 읽기
# ---------------------------------------------------------------------------
def load_external():
    df = pd.read_csv(os.path.join(DRV, "external_daily.csv"))
    rows = {}
    for r in df.to_dict("records"):
        hn = r["holiday_name"]
        rows[D(str(r["date"]))] = {
            "dow": int(r["dow"]),
            "is_holiday": int(r["is_holiday"]) == 1,
            "holiday_name": "" if (hn is None or hn != hn) else str(hn),
            "tmean": None if r["temp_mean"] != r["temp_mean"] else float(r["temp_mean"]),
            "tmin": None if r["temp_min"] != r["temp_min"] else float(r["temp_min"]),
            "tmax": None if r["temp_max"] != r["temp_max"] else float(r["temp_max"]),
            "rain": None if r["rain_mm"] != r["rain_mm"] else float(r["rain_mm"]),
        }
    return rows


def load_events():
    with open(os.path.join(DRV, "events.json"), encoding="utf-8") as f:
        return json.load(f)


def build_schools(events):
    """학교별 개강일·시험 기간·방학 기간을 실제 학사일정에서 뽑는다."""
    out = {}
    for sc in STUDENTS:
        ev = [e for e in events if e.get("source") == "academic" and e.get("school") == sc]
        starts = sorted(D(e["start_date"]) for e in ev if e["type"] == "semester_start")
        exams = sorted((D(e["start_date"]), D(e["end_date"])) for e in ev if e["type"] == "exam")
        vacs = sorted((D(e["start_date"]), D(e["end_date"])) for e in ev if e["type"] == "vacation")
        ends = sorted(D(e["start_date"]) for e in ev if e["type"] == "semester_end")
        if sc == "ewha":
            # 이화여대는 자료에 기말시험이 없어 종강일까지 5일을 기말로 가정한다.
            for se in ends:
                exams.append((se - dt.timedelta(days=4), se))
            exams.sort()
        # 기말시험이 끝난 다음 날부터 방학으로 본다 (자료상 하루 이틀 비는 날 메우기).
        vacs2 = []
        for vs, ve in vacs:
            for es, ee in exams:
                if 0 < (vs - ee).days <= 3:
                    vs = ee + dt.timedelta(days=1)
            vacs2.append((vs, ve))
        exams2 = []
        for es, ee in exams:
            final = any(0 <= (vs - ee).days <= 4 for vs, _ in vacs2)
            exams2.append((es, ee, final))
        out[sc] = {"starts": starts, "exams": exams2, "vacs": vacs2}
    return out


def school_state(sc, day):
    for vs, ve in sc["vacs"]:
        if vs <= day <= ve:
            return {"phase": "vacation", "d_in": (day - vs).days, "d_left": (ve - day).days + 1}
    for es, ee, fin in sc["exams"]:
        if es <= day <= ee:
            return {"phase": "exam", "k": (day - es).days, "n": (ee - es).days + 1, "final": fin}
    start = max(s for s in sc["starts"] if s <= day)
    d_sem = (day - start).days
    nxt = [es for es, _, _ in sc["exams"] if es > day]
    dte = (min(nxt) - day).days if nxt else 999
    prev = [(ee, fin) for _, ee, fin in sc["exams"] if start <= ee < day]
    dse = (day - max(prev)[0]).days if prev else 999
    if dte <= 10:
        ph = "pre_exam"
    elif dse <= 5:
        ph = "post_exam"
    elif d_sem < 21:
        ph = "early_semester"
    else:
        ph = "semester"
    return {"phase": ph, "d_sem": d_sem, "dte": dte, "dse": dse}


def vacation_presence(st):
    """방학 중 신촌에 남아 있는 학생 비율."""
    d_in, d_left = st["d_in"], st["d_left"]
    if d_in < 4:
        p = 0.50          # 종강 직후 며칠은 아직 남아 있다
    elif d_in < 24:
        p = 0.40          # 계절학기 약 3주
    else:
        p = 0.27          # 한가운데
    if d_left <= 10:      # 개강 앞 열흘: 자취방 복귀·수강신청
        p = max(p, 0.27 + (0.50 - 0.27) * (11 - d_left) / 10.0)
    return p


def student_factors(st):
    """학사 국면에 따라 학생의 방문 목적별 배수와 '시험 모드' 강도를 돌려준다."""
    f = {m: 1.0 for m in MISSIONS}
    exam_x = 0.0
    ph = st["phase"]
    if ph == "vacation":
        p = vacation_presence(st)
        f = {"commute": p * 0.8, "lunch": p, "study": p * 1.5, "social": p * 1.3, "bakery_run": p}
    elif ph == "exam":
        k, n = st["k"], st["n"]
        rem = 1.0 - 0.7 * k / max(1, n - 1)       # 시험이 남은 학생 비율 (1.0 → 0.3)
        boost = 1.1 if st["final"] else 0.9
        f["commute"] = 0.62                        # 수업이 없어 등굣길 구매가 준다
        f["lunch"] = 0.75 * (0.6 + 0.4 * rem)
        f["study"] = (1.0 + boost * rem) * (0.55 + 0.45 * rem)
        f["social"] = 0.45 + 0.75 * (1.0 - rem)    # 시험이 끝난 학생부터 약속이 살아난다
        f["bakery_run"] = 0.90
        exam_x = 0.5 + 0.5 * rem
    else:
        d = st["d_sem"]
        r = math.exp(-d / 10.0)                    # 개강 직후 들뜬 분위기 (개강 모임·동아리·짧은 수업)
        f["social"] *= 1.0 + 1.00 * r
        f["lunch"] *= 1.0 + 0.30 * r
        f["commute"] *= 1.0 + 0.15 * r
        f["study"] *= 1.0 - 0.50 * r
        if d > 70:
            f["commute"] *= 0.96                   # 학기 말 출석률 하락
        if ph == "pre_exam":
            x = (11 - st["dte"]) / 10.0
            f["study"] *= 1.0 + 0.7 * x
            f["social"] *= 1.0 - 0.2 * x
            exam_x = 0.5 * x
        elif ph == "post_exam":
            f["study"] *= 0.60
            f["social"] *= 1.12
    return f, exam_x


# ---------------------------------------------------------------------------
# 5. 날씨
# ---------------------------------------------------------------------------
def rain_term(r, snow, streak):
    """비가 재량 방문(민감도 1.0)에 주는 로그 효과. 보슬비는 거의 없고 폭우에서 포화한다."""
    if r <= 0:
        return 0.0
    reff = r * (2.5 if snow else 1.0)
    v = -0.40 * (1.0 - math.exp(-reff / 22.0)) - (0.03 if reff >= 0.5 else 0.0)
    if streak:
        v *= 0.85      # 비가 사흘째면 사람들이 익숙해진다
    return v


def temp_term(t_day, contrast, month):
    """기온이 재량 방문에 주는 로그 효과 (역 U자)."""
    if t_day < 5:
        v = -0.013 * (5 - t_day)
    elif t_day < 13:
        v = 0.05 * (t_day - 5) / 8.0
    elif t_day <= 25:
        v = 0.05
    elif t_day <= 29:
        v = 0.05 - 0.07 * (t_day - 25) / 4.0
    else:
        v = -0.02 - 0.012 * (t_day - 29)
    if contrast < -5:
        v -= 0.04      # 갑자기 추워진 날
    if contrast > 5 and t_day > 10 and month in (2, 3, 4, 5):
        v += 0.05      # 봄에 갑자기 포근해진 날
    return v


def p_ice_americano(t):
    return 0.22 + 0.74 * sig((t - 10.0) / 6.0)


def p_ice_latte(t):
    return 0.08 + 0.84 * sig((t - 14.0) / 5.5)


# ---------------------------------------------------------------------------
# 6. 날짜별 공개 맥락(context) 만들기
# ---------------------------------------------------------------------------
def build_contexts(ext, events, schools):
    days = [START + dt.timedelta(days=i) for i in range((END - START).days + 1)]
    off = {d: (v["dow"] >= 5 or v["is_holiday"]) for d, v in ext.items()}
    core = {d: v["holiday_name"] in ("설날", "추석") for d, v in ext.items()}
    one = dt.timedelta(days=1)

    def block(d):
        a = d
        while off.get(a - one, False):
            a -= one
        b = d
        while off.get(b + one, False):
            b += one
        n = (b - a).days + 1
        mj = any(core.get(a + dt.timedelta(days=i), False) for i in range(n))
        return n, mj

    def t_day(d):
        v = ext[d]
        return 0.5 * (v["tmean"] + v["tmax"])

    culture = [e for e in events if e.get("source") == "seoul_culture"]
    ctxs = []
    for d in days:
        v = ext[d]
        c = {"date": d, "dow": v["dow"], "is_holiday": v["is_holiday"], "holiday_name": v["holiday_name"],
             "tmean": v["tmean"], "tmax": v["tmax"], "tmin": v["tmin"], "rain": v["rain"]}
        # --- 휴일 구조
        c["off"] = off[d]
        if off[d]:
            n, mj = block(d)
            c["block_len"], c["mj_block"], c["mj_core"] = n, mj, core[d]
        else:
            c["block_len"], c["mj_block"], c["mj_core"] = 0, False, False
        c["eve"] = c["eve_mj"] = c["sandwich"] = False
        if not off[d]:
            nxt_off, prev_off = off.get(d + one, False), off.get(d - one, False)
            if nxt_off:
                n, mj = block(d + one)
                if mj:
                    c["eve_mj"] = True
                elif n >= 3:
                    c["eve"] = True
            if nxt_off and prev_off:
                c["sandwich"] = True
        if c["mj_core"]:
            c["day_type"] = "명절 당일 전후"
        elif c["mj_block"]:
            c["day_type"] = "명절 연휴"
        elif off[d] and c["block_len"] >= 3:
            c["day_type"] = "연휴"
        elif v["is_holiday"] and v["dow"] < 5:
            c["day_type"] = "단독 공휴일"
        elif off[d]:
            c["day_type"] = "주말"
        elif c["sandwich"]:
            c["day_type"] = "징검다리 평일"
        elif c["eve_mj"]:
            c["day_type"] = "명절 연휴 전날"
        elif c["eve"]:
            c["day_type"] = "연휴 전날"
        else:
            c["day_type"] = "평일"
        # --- 날씨
        td = t_day(d)
        prev = [t_day(d - dt.timedelta(days=i)) for i in range(1, 11)]
        contrast = td - sum(prev) / len(prev)
        c["t_day"] = td
        c["contrast"] = contrast
        c["snow"] = v["rain"] > 0 and v["tmean"] < 0.5
        c["streak"] = all(ext[d - dt.timedelta(days=i)]["rain"] >= 3 for i in (1, 2)) and v["rain"] >= 3
        c["t_eff"] = td + 0.3 * clip(contrast, -8, 8) - 1.5 * min(1.0, v["rain"] / 10.0)
        c["heat"] = clip((v["tmax"] - 28.0) / 7.0, 0.0, 1.0)
        c["cold"] = clip((10.0 - c["t_eff"]) / 15.0, 0.0, 1.0)
        # --- 학사
        c["school"] = {s: school_state(schools[s], d) for s in STUDENTS}
        # --- 공개 문화행사
        evs, tot = [], 0.0
        for e in culture:
            s0, e0 = D(e["start_date"]), D(e["end_date"])
            if not (s0 <= d <= e0):
                continue
            if "카운트다운" in e["title"] or "COUNTDOWN" in e["title"].upper():
                if d != s0:      # 자정을 넘겨 끝나서 종료일이 다음 날로 찍힌 것뿐이다
                    continue
            eff = EVENT_SIZE.get(e.get("category"), 0.03) * math.exp(-float(e["distance_m"]) / EVENT_DIST_SCALE)
            evs.append({"title": e["title"], "category": e.get("category"),
                        "distance_m": e["distance_m"], "log_effect_visitor": round(eff, 4)})
            tot += eff
        c["events"], c["event_log"] = evs, tot
        # --- 기념일·학교 행사
        c["specials"] = [sp for sp in SPECIALS if D(sp[0]) <= d <= D(sp[1])]
        # --- 할인
        c["promos"] = [p for p in PROMOS if D(p[0]) <= d <= D(p[1])]
        c["closed"] = CLOSURES.get(d.isoformat())
        ctxs.append(c)
    return ctxs


def unit_price(item, c):
    d = c["date"]
    p = [v for s, v in PRICE[item] if D(s) <= d][-1]
    for pr in c["promos"]:
        p -= pr[2].get(item, 0)
    return p


def available(item, d):
    if item not in AVAIL:
        return True
    a, b = AVAIL[item]
    return (a is None or d >= a) and (b is None or d <= b)


# ---------------------------------------------------------------------------
# 7. 숨은 난수 (공개 자료로는 알 수 없는 것들)
# ---------------------------------------------------------------------------
def draw_hidden(ctxs, schools):
    ss = np.random.SeedSequence(SEED)
    r_noise, r_ops, r_shock = [np.random.default_rng(s) for s in ss.spawn(3)]
    n = len(ctxs)
    z = r_noise.normal(0, SD_DAY, n)
    e = r_noise.normal(0, SD_AR, n)
    ar = np.zeros(n)
    for i in range(n):
        ar[i] = (RHO_AR * ar[i - 1] if i else 0.0) + e[i]
    rw = np.cumsum(r_noise.normal(0, SD_RW, n))
    seg = np.stack([r_shock.normal(0, SD_SEG[s], n) for s in SEGS], axis=1)
    fam = np.stack([r_shock.normal(0, SD_FAM[f], n) for f in FAMILIES], axis=1)
    item = r_shock.normal(0, SD_ITEM, (n, len(ITEMS)))
    pop_rw = np.cumsum(r_shock.normal(0, SD_POP_RW, (n, len(ITEMS))), axis=0)   # 품목 인기의 느린 떠돌이
    u_rain = r_ops.uniform(0.35, 1.25, n)
    u_rain_big = r_ops.uniform(0.70, 1.25, n)
    u_conc, m_conc = r_ops.uniform(0, 1, n), r_ops.uniform(0.05, 0.18, n)
    u_staff, m_staff = r_ops.uniform(0, 1, n), r_ops.uniform(0.80, 0.90, n)
    u_bulk = r_ops.uniform(0, 1, n)
    q_bulk = r_ops.integers(15, 41, n)
    u_bulk2 = r_ops.uniform(0, 1, n)
    q_bulk2 = r_ops.integers(10, 25, n)
    hid = []
    for i, c in enumerate(ctxs):
        d, dow = c["date"], c["dow"]
        yph = c["school"]["yonsei"]["phase"]
        p_conc = {4: 0.22, 5: 0.30, 6: 0.18}.get(dow, 0.05)
        p_staff = 0.06 if yph in ("exam", "pre_exam") else 0.02   # 알바생도 학생이라 시험철에 구멍이 난다
        if c["off"]:
            p_bulk = 0.01
        elif yph == "vacation":
            p_bulk = 0.02
        else:
            p_bulk = 0.06
        bulk = None
        if u_bulk[i] < p_bulk:
            bulk = {"coffee": int(q_bulk[i])}
            if u_bulk2[i] < 0.5:
                bulk["side_item"] = SALT if u_bulk2[i] < 0.25 else COOKIE
                bulk["side_qty"] = int(q_bulk2[i])
        hid.append({
            "z": float(z[i]), "ar": float(ar[i]), "rw": float(rw[i]),
            "seg": seg[i], "fam": fam[i], "item": item[i], "pop_rw": pop_rw[i],
            "u_rain": float(u_rain_big[i] if c["rain"] >= 40 else u_rain[i]),
            "concert": float(m_conc[i]) if u_conc[i] < p_conc else 0.0,
            "short_staff": float(m_staff[i]) if u_staff[i] < p_staff else 0.0,
            "bulk": bulk,
        })
    return hid


# ---------------------------------------------------------------------------
# 8. 하루치 방문 행렬
# ---------------------------------------------------------------------------
BASEMAT = np.array([[BASE[s] * MIX[s][j] for j in range(len(MISSIONS))] for s in SEGS], dtype=float)
SI = {s: i for i, s in enumerate(SEGS)}
MI = {m: i for i, m in enumerate(MISSIONS)}


def visits_expected(c, h, noisy=True):
    """고객층×방문목적 기대 방문 건수와, 원인별로 고객층 합계가 몇 배가 됐는지를 돌려준다."""
    d, dow = c["date"], c["dow"]
    V = BASEMAT.copy()
    fac, tot = {}, {}

    def apply(name, F):
        nonlocal V
        before = V.sum(axis=1)
        V = V * F
        after = V.sum(axis=1)
        fac[name] = [float(after[i] / before[i]) if before[i] > 0 else 1.0 for i in range(len(SEGS))]
        tot[name] = float(after.sum() / before.sum())

    hol_wd = c["is_holiday"] and dow < 5
    # (1) 요일 리듬
    F = np.ones_like(V)
    for s in SEGS:
        k = HOLIDAY_DOW[s] if hol_wd else dow
        for m in MISSIONS:
            F[SI[s], MI[m]] = DOWP[s][m][k]
    apply("dow", F)

    # (2) 학사 국면
    F = np.ones_like(V)
    exam_x = {}
    for s in STUDENTS:
        f, x = student_factors(c["school"][s])
        exam_x[s] = x
        for m in MISSIONS:
            F[SI[s], MI[m]] = f[m]
    yst = c["school"]["yonsei"]
    in_vac = yst["phase"] == "vacation"
    late_summer = D("2026-07-27") <= d <= D("2026-08-14")
    if in_vac:
        F[SI["resident"], :] *= 0.80       # 자취생 귀향
        if dow < 5:
            F[SI["visitor"], :] *= 1.12    # 방학엔 평일에도 약속을 잡는다
        F[SI["academy"], :] *= 1.55        # 방학 특강
        F[SI["staff"], :] *= 0.90
    if late_summer:                        # 7말8초 휴가철
        F[SI["staff"], :] *= 0.85
        F[SI["office"], :] *= 0.85
        F[SI["hospital"], :] *= 0.95
    apply("academic", F)

    # (3) 휴일 구조·월중 리듬
    F = np.ones_like(V)
    stu_like = ("yonsei", "sogang")
    if hol_wd and c["block_len"] < 3 and not c["mj_block"]:
        for s in stu_like + ("academy",):
            F[SI[s], :] *= 1.5             # 하루짜리 휴일엔 학생이 신촌에 남는다
        F[SI["hospital"], :] *= 1.2
        F[SI["office"], :] *= 1.2
        F[SI["visitor"], :] *= 0.85
    if c["off"] and c["block_len"] >= 3 and not c["mj_block"]:
        for s in stu_like:
            F[SI[s], :] *= 0.95 if in_vac else 0.80   # 연휴엔 본가로 간다
        F[SI["resident"], :] *= 0.88
        F[SI["visitor"], :] *= 0.92
    if c["mj_block"]:
        if c["mj_core"]:
            mult = {"yonsei": 0.35, "sogang": 0.35, "ewha": 0.35, "resident": 0.50, "visitor": 0.50,
                    "tourist": 0.90, "hospital": 0.70, "office": 0.50, "academy": 0.20}
        else:
            mult = {"yonsei": 0.60, "sogang": 0.60, "ewha": 0.60, "resident": 0.70, "visitor": 0.75}
        for s, x in mult.items():
            F[SI[s], :] *= x
    if c["eve"]:
        for s in stu_like:
            F[SI[s], :] *= 0.90
        F[SI["visitor"], :] *= 1.08
    if c["eve_mj"]:
        for s in stu_like:
            F[SI[s], :] *= 0.75
        F[SI["staff"], :] *= 0.90
        F[SI["office"], :] *= 0.95
        F[SI["visitor"], :] *= 0.90
        F[:, MI["bakery_run"]] *= 1.15     # 귀성길 빵 선물
    if c["sandwich"]:
        for s in stu_like:
            F[SI[s], :] *= 0.75            # 휴강이 많다
        F[SI["staff"], :] *= 0.80
        F[SI["office"], :] *= 0.88
        F[SI["visitor"], :] *= 1.10
    if d.day <= 7:                         # 월초 용돈
        for s in STUDENTS:
            F[SI[s], MI["social"]] *= 1.04
            F[SI[s], MI["bakery_run"]] *= 1.04
    elif d.day >= 23:
        for s in STUDENTS:
            F[SI[s], MI["social"]] *= 0.97
            F[SI[s], MI["bakery_run"]] *= 0.97
    apply("calendar", F)

    # (4) 날씨
    rt = rain_term(c["rain"], c["snow"], c["streak"]) * (h["u_rain"] if noisy else 0.8)
    tt = temp_term(c["t_day"], c["contrast"], d.month)
    F = np.ones_like(V)
    for s in SEGS:
        for m in MISSIONS:
            F[SI[s], MI[m]] = math.exp(W_SEG[s] * (W_RAIN_MIS[m] * rt + W_TEMP_MIS[m] * tt))
    apply("weather", F)

    # (5) 공개 문화행사
    F = np.ones_like(V)
    E = c["event_log"]
    if E > 0:
        F[SI["visitor"], :] *= math.exp(E)
        F[SI["tourist"], :] *= math.exp(0.6 * E)
        F[SI["resident"], :] *= math.exp(0.3 * E)
        for s in STUDENTS:
            F[SI[s], MI["social"]] *= math.exp(0.35 * E)
    apply("public_event", F)

    # (6) 기념일·학교 행사·관광 계절
    F = np.ones_like(V)
    for sp in c["specials"]:
        for (s, m), x in sp[4].items():
            if m == "*":
                F[SI[s], :] *= x
            else:
                F[SI[s], MI[m]] *= x
    years = (d - START).days / 365.0
    F[SI["tourist"], :] *= TOURIST_MONTH[d.month] * (1.0 + 0.10 * years)
    apply("special_day", F)

    # (7) 공개 자료에 없는 구조적 변화 (성장·경쟁점·공사·공연·단축영업)
    F = np.ones_like(V)
    F *= math.exp(ANNUAL_GROWTH * years + (h["rw"] if noisy else 0.0))
    if d >= COMPETITOR_OPEN:
        k = (d - COMPETITOR_OPEN).days
        x = 1.0 - 0.06 - 0.07 * math.exp(-k / 14.0)
        for s in ("yonsei", "sogang", "academy", "office"):
            F[SI[s], MI["commute"]] *= x
            F[SI[s], MI["lunch"]] *= x
    if CONSTRUCTION[0] <= d <= CONSTRUCTION[1]:
        for s in ("visitor", "tourist", "resident"):
            F[SI[s], :] *= 0.92
    if noisy and h["concert"] > 0:
        F[SI["visitor"], MI["social"]] *= 1.0 + h["concert"]
        F[SI["visitor"], MI["lunch"]] *= 1.0 + h["concert"]
    sh = SHORT_HOURS.get(d.isoformat())
    if sh:
        F *= sh[0]
    apply("hidden_structural", F)

    # (8) 그날의 운 (전체 공통 + 고객층별)
    F = np.ones_like(V)
    if noisy:
        common = math.exp(h["z"] + h["ar"])
        for s in SEGS:
            F[SI[s], :] *= common * math.exp(float(h["seg"][SI[s]]))
    apply("noise", F)
    return V, fac, exam_x, {"rain_term": rt, "temp_term": tt, "total": tot}


# ---------------------------------------------------------------------------
# 9. 방문 → 품목 수요
# ---------------------------------------------------------------------------
def nc_weights(c):
    """논커피 음료의 그날 매력도."""
    d, t = c["date"], c["t_eff"]
    w = {CHOCO: 0.50 * (0.55 + 0.95 * sig((11.0 - t) / 5.0)),
         ADE: 0.18 + 1.60 * sig((t - 19.0) / 4.0)}
    if available(STRAW, d):
        a, b = AVAIL[STRAW]
        k = (d - a).days
        season = {12: 1.00, 1: 1.10, 2: 1.25, 3: 1.25, 4: 1.00}[d.month]
        left = (b - d).days
        fade = 0.75 + 0.25 * min(1.0, left / 21.0)       # 철이 끝나갈수록 시든다
        w[STRAW] = 1.35 * season * fade * (1.0 + 0.30 * math.exp(-k / 7.0))
    if available(WMELON, d):
        k = (d - AVAIL[WMELON][0]).days
        w[WMELON] = 1.25 * sig((t - 21.0) / 3.5) * (1.0 + 0.25 * math.exp(-k / 7.0))
    if available(MATCHA, d):
        k = (d - AVAIL[MATCHA][0]).days
        w[MATCHA] = 0.75 * (1.0 + 0.90 * math.exp(-k / 12.0)) * (1.0 - 0.12 * min(k, 200) / 200.0)
    return w


def popularity(c, h, noisy):
    """품목 인기의 느린 변화 (빵·디저트)."""
    d = c["date"]
    y = (d - START).days / 365.0
    pop = {SALT: 1.0 + 0.12 * y, CROI: 1.0 - 0.07 * y, SAND: 1.0, CAKE: 1.0, COOKIE: 1.0 + 0.05 * y}
    k_end = (AVAIL[SCONE][1] - START).days
    pop[SCONE] = 1.0 - 0.40 * min(1.0, (d - START).days / k_end)
    if d >= VIRAL_START:
        pop[SALT] *= 1.0 + 0.40 * math.exp(-(d - VIRAL_START).days / 9.0)
    if noisy:
        for it in pop:
            pop[it] *= math.exp(float(h["pop_rw"][ITEMS.index(it)]))
    return pop


def item_means(c, h, N, exam_x, noisy=True):
    """방문 건수 행렬 N 에서 품목별 기대 수요를 만든다."""
    d = c["date"]
    mu = {it: 0.0 for it in ITEMS}
    ncw = nc_weights(c)
    pop = popularity(c, h, noisy)
    heat, cold, t = c["heat"], c["cold"], c["t_eff"]
    for s in SEGS:
        x = exam_x.get(s, 0.0)
        taste = dict(zip(NC_ITEMS, TASTE[s]))
        for m in MISSIONS:
            n = float(N[SI[s], MI[m]])
            if n <= 0:
                continue
            # --- 음료
            drinks = n * DPV[m] * (1.0 + HEAT_THIRST * heat)
            cs = CS[m] + CS_OFF[s]
            if m == "study":
                drinks *= 1.0 + 0.12 * x       # 오래 앉아 한 잔 더
                cs += 0.08 * x
            cs = clip(cs, 0.2, 0.97)
            want_nc = drinks * (1.0 - cs)
            w = {j: ncw[j] * taste[j] for j in ncw}
            A = sum(w.values())
            p_buy = A / (A + NC_NONE)
            for j in w:
                mu[j] += want_nc * p_buy * w[j] / A
            coffee = drinks * cs + 0.5 * want_nc * (1.0 - p_buy)   # 못 고른 손님 절반은 커피로
            a_w = AW[s] * (1.0 + 0.2 * x if m in ("study", "commute") else 1.0)
            l_w = (1.0 - AW[s]) * (1.0 + 0.3 * cold)
            sa = a_w / (a_w + l_w)
            ts = t + T_SHIFT[s]
            pia, pil = p_ice_americano(ts), p_ice_latte(ts)
            mu[AME_I] += coffee * sa * pia
            mu[AME_H] += coffee * sa * (1.0 - pia)
            mu[LAT_I] += coffee * (1.0 - sa) * pil
            mu[LAT_H] += coffee * (1.0 - sa) * (1.0 - pil)
            # --- 빵
            wb = {j: BW[m][i] * pop[j] for i, j in enumerate(BK_ITEMS) if available(j, d)}
            Ab = sum(wb.values())
            bk = n * BPV[m] * BAFF[s] * (1.0 - 0.12 * heat) * (1.0 + 0.05 * cold) * Ab ** 0.4
            for j in wb:
                mu[j] += bk * wb[j] / Ab
            # --- 디저트
            wd = {CAKE: DW[m][0] * pop[CAKE], COOKIE: DW[m][1] * pop[COOKIE]}
            if m == "study":
                wd[COOKIE] *= 1.0 + 0.6 * x    # 시험 기간 당 충전
            Ad = sum(wd.values())
            ds = n * DSV[m] * DAFF[s] * (1.0 - 0.05 * heat) * Ad ** 0.6
            for j in wd:
                mu[j] += ds * wd[j] / Ad
    # --- 품목 단위 배수
    mult = {it: {} for it in ITEMS}
    for sp in c["specials"]:
        for it, xv in sp[5].items():
            mult[it][sp[2]] = xv
    for pr in c["promos"]:
        for it, xv in pr[3].items():
            mult[it][pr[4]] = xv
    if d >= COFFEE_PRICE_UP:
        k = (d - COFFEE_PRICE_UP).days
        xv = 1.0 - 0.03 - 0.03 * math.exp(-k / 20.0)
        for it in (AME_H, AME_I, LAT_H, LAT_I):
            mult[it]["가격 인상(+300원) 반응"] = xv
    if d >= SALT_PRICE_UP:
        k = (d - SALT_PRICE_UP).days
        mult[SALT]["가격 인상(+300원) 반응"] = 1.0 - 0.03 - 0.04 * math.exp(-k / 20.0)
    inc = INCIDENTS.get(d.isoformat())
    if inc and noisy:
        for it, xv in inc[1].items():
            mult[it][inc[0]] = xv
    if noisy and h["short_staff"] > 0:
        for it in ITEMS:
            mult[it]["일손 부족"] = h["short_staff"]
    if noisy:
        for it in ITEMS:
            mult[it]["noise"] = math.exp(float(h["fam"][FAMILIES.index(FAMILY[it])]) + float(h["item"][ITEMS.index(it)]))
    out = {}
    for it in ITEMS:
        v = mu[it] if available(it, d) else 0.0
        for xv in mult[it].values():
            v *= xv
        out[it] = v
    return out, mult


# ---------------------------------------------------------------------------
# 10. 점주의 준비량 결정 (과거 판매만 보고 정한다)
# ---------------------------------------------------------------------------
class Owner:
    def __init__(self, ctxs, exp_mu):
        self.level, self.idx = {}, {}
        for it in CAPPED:
            days = [i for i, c in enumerate(ctxs) if available(it, c["date"]) and not c["closed"]]
            first = days[:28]
            base = sum(exp_mu[i][it] for i in first[:14]) / max(1, len(first[:14]))
            bias = 0.80 if it == STRAW else 1.0     # 신메뉴는 처음에 적게 준비한다
            self.level[it] = max(1.0, base * bias)
            idx = []
            for k in range(7):
                v = [exp_mu[i][it] for i in first if self.dow_eff(ctxs[i]) == k]
                idx.append((sum(v) / len(v)) / base if v and base > 0 else 1.0)
            self.idx[it] = idx

    @staticmethod
    def dow_eff(c):
        return 6 if (c["is_holiday"] and c["dow"] < 5) else c["dow"]

    @staticmethod
    def known_adjust(it, c):
        """점주가 달력을 보고 미리 아는 조정."""
        d = c["date"]
        a = 1.0
        y = c["school"]["yonsei"]
        if c["mj_block"]:
            a *= 0.55 if c["mj_core"] else 0.80
        if y["phase"] == "vacation" and y["d_in"] < 7:
            a *= 0.80
        if y["phase"] in ("early_semester",) and y["d_sem"] < 7:
            a *= 1.20
        if y["phase"] == "exam":
            a *= 0.95
        if c["rain"] >= 20:
            a *= 0.92          # 큰비 예보가 있으면 조금 덜 굽는다
        if c["event_log"] > 0.15:
            a *= 1.20          # 가게 앞 거리 축제
        md = d.strftime("%m-%d")
        if md in ("12-23", "12-24", "12-25"):
            a *= {CAKE: 1.7, COOKIE: 1.2, STRAW: 1.2}.get(it, 1.0)
        if md in ("02-14", "03-14"):
            a *= {COOKIE: 1.25, CAKE: 1.15}.get(it, 1.0)
        return a

    def plan(self, it, c):
        batch, safety = CAPPED[it]
        raw = self.level[it] * self.idx[it][self.dow_eff(c)] * self.known_adjust(it, c) * safety
        return max(batch, int(math.floor(raw / batch + 0.5)) * batch)

    def learn(self, it, c, sold, lost):
        # 품절 시각과 "다 나갔어요?" 묻는 손님 수로 놓친 수요의 절반쯤은 짐작한다
        est = sold + 0.6 * lost
        k = self.dow_eff(c)
        adj = self.known_adjust(it, c)
        old = self.level[it]
        des = est / max(0.05, self.idx[it][k] * adj)
        self.level[it] = max(1.0, old + 0.12 * (des - old))
        self.idx[it][k] += 0.10 * (est / max(1.0, old * adj) - self.idx[it][k])
        self.idx[it][k] = clip(self.idx[it][k], 0.2, 3.0)


# ---------------------------------------------------------------------------
# 11. 전체 시뮬레이션
# ---------------------------------------------------------------------------
def r3(x):
    return round(float(x), 3)


def simulate():
    ext = load_external()
    events = load_events()
    schools = build_schools(events)
    ctxs = build_contexts(ext, events, schools)
    hid = draw_hidden(ctxs, schools)
    rng = np.random.default_rng(np.random.SeedSequence(SEED + 1))

    # 점주의 초기 감각: 잡음 없는 기대 수요로 잡는다 (개업 후 쌓인 경험을 대신함)
    exp_mu = []
    for c, h in zip(ctxs, hid):
        V, _, ex, _ = visits_expected(c, h, noisy=False)
        mu, _ = item_means(c, h, V, ex, noisy=False)
        exp_mu.append(mu)
    owner = Owner(ctxs, exp_mu)

    rows, truth_days = [], []
    for i_day, (c, h) in enumerate(zip(ctxs, hid)):
        d = c["date"]
        ds = d.isoformat()
        V, fac, exam_x, wt = visits_expected(c, h, noisy=True)
        # 난수 소비 순서를 휴무일에도 똑같이 유지한다
        N = rng.poisson(V)
        # 등굣길·식후 커피는 단골의 습관이라 포아송보다 규칙적이다 (분산이 절반)
        for m in HABIT_MISSIONS:
            lam = V[:, MI[m]]
            n_try = np.ceil(2.0 * lam).astype(int)
            p_try = np.divide(lam, n_try, out=np.zeros_like(lam), where=n_try > 0)
            N[:, MI[m]] = rng.binomial(n_try, p_try)
        mu, mult = item_means(c, h, N, exam_x, noisy=True)
        gam = rng.gamma(NB_K, 1.0 / NB_K, len(ITEMS))
        demand = {it: int(rng.poisson(mu[it] * gam[i])) for i, it in enumerate(ITEMS)}

        rec = {
            "date": ds, "dow": c["dow"], "closed": bool(c["closed"]),
            "closed_reason": c["closed"],
            "calendar": {"day_type": c["day_type"], "is_holiday": c["is_holiday"],
                         "holiday_name": c["holiday_name"] or None, "off_block_len": c["block_len"]},
            "academic": {s: c["school"][s]["phase"] for s in STUDENTS},
            "weather": {"temp_mean": c["tmean"], "temp_max": c["tmax"], "rain_mm": c["rain"],
                        "t_day": r3(c["t_day"]), "t_eff": r3(c["t_eff"]), "contrast": r3(c["contrast"]),
                        "snow": bool(c["snow"]), "rain_log_effect": r3(wt["rain_term"]),
                        "temp_log_effect": r3(wt["temp_term"]),
                        "hidden_rain_timing": r3(h["u_rain"]) if c["rain"] > 0 else None},
            "public_events": c["events"],
            "special_days": [{"label": sp[2], "source": sp[3]} for sp in c["specials"]],
            "promotions": [p[4] for p in c["promos"]],
        }
        if c["closed"]:
            truth_days.append(rec)
            continue

        inc = INCIDENTS.get(ds)
        hidden = {"day_noise": r3(math.exp(h["z"])), "slow_noise": r3(math.exp(h["ar"])),
                  "trend": r3(math.exp(ANNUAL_GROWTH * (d - START).days / 365.0 + h["rw"]))}
        if h["concert"] > 0:
            hidden["nearby_concert_boost"] = r3(1 + h["concert"])
        if h["short_staff"] > 0:
            hidden["short_staffed"] = r3(h["short_staff"])
        if inc:
            hidden["incident"] = inc[0]
        if ds in SHORT_HOURS:
            hidden["short_hours"] = SHORT_HOURS[ds][1]
        if d >= COMPETITOR_OPEN:
            hidden["competitor"] = r3(1.0 - 0.06 - 0.07 * math.exp(-(d - COMPETITOR_OPEN).days / 14.0))
        if CONSTRUCTION[0] <= d <= CONSTRUCTION[1]:
            hidden["construction"] = 0.92
        rec["hidden"] = hidden
        rec["segments"] = {
            s: {"expected_visits": r3(V[SI[s]].sum()), "visits": int(N[SI[s]].sum()),
                "factors": {k: r3(v[SI[s]]) for k, v in fac.items()}}
            for s in SEGS}
        rec["total_factors"] = {k: r3(v) for k, v in wt["total"].items()}
        rec["missions"] = {m: int(N[:, MI[m]].sum()) for m in MISSIONS}

        # --- 준비량 상한과 품절
        cap = {}
        for it in CAPPED:
            if available(it, d):
                q = owner.plan(it, c)
                if inc and it in inc[2]:
                    q = max(1, int(q * inc[2][it]))
                cap[it] = q
        sold = {it: (min(demand[it], cap[it]) if it in cap else demand[it]) for it in ITEMS}
        spill_in = {it: 0 for it in ITEMS}
        # 품절된 빵의 일부 수요는 남아 있는 다른 빵으로 옮겨 간다
        pool = sum(demand[it] - sold[it] for it in BREADS if it in cap) * BREAD_SPILL
        if pool > 0:
            room = {it: cap[it] - sold[it] for it in BREADS if it in cap and cap[it] > sold[it]}
            tot = sum(demand[it] for it in room)
            for it in room:
                extra = int(min(room[it], round(pool * demand[it] / tot))) if tot > 0 else 0
                sold[it] += extra
                spill_in[it] = extra
        lost_cake = demand[CAKE] - sold[CAKE]
        if lost_cake > 0 and cap[COOKIE] > sold[COOKIE]:
            extra = int(min(cap[COOKIE] - sold[COOKIE], round(lost_cake * CAKE_SPILL)))
            sold[COOKIE] += extra
            spill_in[COOKIE] = extra
        # --- 단체 주문 (사전 예약이라 준비량과 무관)
        bulk = {it: 0 for it in ITEMS}
        if h["bulk"]:
            q = h["bulk"]["coffee"]
            qi = int(round(q * p_ice_americano(c["t_eff"] + 1.0)))
            bulk[AME_I] += qi
            bulk[AME_H] += q - qi
            if "side_item" in h["bulk"]:
                bulk[h["bulk"]["side_item"]] += h["bulk"]["side_qty"]
            rec["hidden"]["bulk_order"] = {k: v for k, v in bulk.items() if v > 0}

        items = {}
        any_out = False
        for it in ITEMS:
            if not available(it, d):
                continue
            price = unit_price(it, c)
            own_sold = sold[it] - spill_in[it]
            lost = demand[it] - own_sold
            out = it in cap and demand[it] >= cap[it] and lost > 0
            any_out = any_out or out
            qty = sold[it] + bulk[it]
            ir = {"price": price, "systematic": r3(exp_mu[i_day][it]), "mean_demand": r3(mu[it]),
                  "demand": demand[it], "sold": qty}
            if it in cap:
                ir["cap"] = cap[it]
                ir["sold_out"] = bool(out)
                ir["lost"] = int(lost)
            if spill_in[it]:
                ir["spill_in"] = spill_in[it]
            if bulk[it]:
                ir["bulk"] = bulk[it]
            mm = {k: r3(v) for k, v in mult[it].items() if k != "noise"}
            if mm:
                ir["mult"] = mm
            ir["noise"] = r3(mult[it]["noise"])
            items[it] = ir
            if qty > 0:
                rows.append((ds, it, qty, qty * price))
            if it in cap and not inc and not c["mj_block"]:
                owner.learn(it, c, sold[it], lost if out else 0)
        rec["items"] = items
        rec["any_sold_out"] = bool(any_out)
        truth_days.append(rec)
    return rows, truth_days, ctxs


# ---------------------------------------------------------------------------
# 12. 파일 쓰기
# ---------------------------------------------------------------------------
def write_pos(rows):
    path = os.path.join(HERE, "pos_raw.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["판매일자", "상품명", "수량", "판매금액"])
        for r in rows:
            w.writerow(r)
    return path


def menu_truth():
    out = []
    for it in ITEMS:
        a, b = AVAIL.get(it, (None, None))
        e = {"name": it, "family": FAMILY[it],
             "price_history": [{"from": s, "price": p} for s, p in PRICE[it]],
             "launch_date": a.isoformat() if a else None,
             "discontinue_date": b.isoformat() if b else None,
             "seasonal": it in (STRAW, WMELON),
             "daily_stock_cap": it in CAPPED,
             "note": ITEM_NOTE[it]}
        if it in CAPPED:
            e["batch_size"], e["owner_safety_factor"] = CAPPED[it]
        out.append(e)
    return out


def write_truth_json(truth_days):
    obj = {
        "meta": {
            "store_id": "campus-a", "period": [START.isoformat(), END.isoformat()], "seed": SEED,
            "note": "가상 매장의 시뮬레이션 정답지. factors 는 고객층별 방문 합계가 원인별로 몇 배가 됐는지(순서대로 곱함)이다.",
            "factor_order": ["dow", "academic", "calendar", "weather", "public_event", "special_day",
                             "hidden_structural", "noise"],
            "item_fields": {"systematic": "난수(그날의 운·사고·단체주문)를 뺀 기대 수요. 공개 요인 + 구조적 숨은 요인만 반영",
                            "mean_demand": "그날 실제 방문객 구성과 잡음까지 반영한 기대 수요", "demand": "실제로 사려던 수량(잠재)",
                            "cap": "점주가 준비한 수량", "sold": "POS 에 찍힌 수량(단체 주문 포함)",
                            "lost": "품절로 못 판 수량", "spill_in": "다른 품목 품절로 넘어온 수량"},
        },
        "segments": {s: {"label": SEG_LABEL[s], "base_weekday_visits": BASE[s],
                         "mission_mix": dict(zip(MISSIONS, MIX[s])),
                         "weather_sensitivity": W_SEG[s]} for s in SEGS},
        "missions": {m: {"label": MIS_LABEL[m], "drinks_per_visit": DPV[m], "bakery_per_visit": BPV[m],
                         "dessert_per_visit": DSV[m], "coffee_share": CS[m],
                         "rain_sensitivity": W_RAIN_MIS[m], "temp_sensitivity": W_TEMP_MIS[m]}
                     for m in MISSIONS},
        "menu": menu_truth(),
        "closures": CLOSURES,
        "promotions": [{"start": p[0], "end": p[1], "discount": p[2], "demand_mult": p[3], "label": p[4]}
                       for p in PROMOS],
        "special_days": [{"start": sp[0], "end": sp[1], "label": sp[2], "source": sp[3],
                          "segment_mult": {"%s/%s" % k: v for k, v in sp[4].items()}, "item_mult": sp[5]}
                         for sp in SPECIALS],
        "hidden_shocks": {
            "incidents": {k: {"label": v[0], "item_mult": v[1], "cap_mult": v[2]} for k, v in INCIDENTS.items()},
            "competitor_open": COMPETITOR_OPEN.isoformat(),
            "construction": [CONSTRUCTION[0].isoformat(), CONSTRUCTION[1].isoformat()],
            "viral_salt_bread_start": VIRAL_START.isoformat(),
            "short_hours": {k: v[1] for k, v in SHORT_HOURS.items()},
        },
        "days": truth_days,
    }
    path = os.path.join(HERE, "truth.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    return path


# ---------------------------------------------------------------------------
# 13. 점검 통계 (산출물만 가지고 계산)
# ---------------------------------------------------------------------------
def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out


def f0(x):
    return "-" if x != x else "%d" % int(round(x))


def f1(x):
    return "-" if x != x else "%.1f" % x


def f2(x):
    return "-" if x != x else "%.2f" % x


def pct(x):
    return "-" if x != x else "%.0f%%" % (100.0 * x)


def sanity_stats(truth_days):
    recs = []
    for d in truth_days:
        if d["closed"]:
            continue
        it = d["items"]

        def q(names):
            return sum(it[n]["sold"] for n in names if n in it)

        fam = {f: sum(v["sold"] for k, v in it.items() if FAMILY[k] == f) for f in FAMILIES}
        hid = d["hidden"]
        recs.append({
            "date": d["date"], "ym": d["date"][:7], "dow": d["dow"], "dtype": d["calendar"]["day_type"],
            "phase": d["academic"]["yonsei"],
            "regime": "방학" if d["academic"]["yonsei"] == "vacation" else "학기",
            "rain": d["weather"]["rain_mm"], "tday": d["weather"]["t_day"],
            "visits": sum(s["visits"] for s in d["segments"].values()),
            "students": sum(d["segments"][s]["visits"] for s in STUDENTS),
            "units": sum(v["sold"] for v in it.values()),
            "rev": sum(v["sold"] * v["price"] for v in it.values()),
            "coffee": fam["coffee"], "noncoffee": fam["noncoffee"], "bakery": fam["bakery"], "dessert": fam["dessert"],
            "ice": q([AME_I, LAT_I]), "hot": q([AME_H, LAT_H]), "ame": q([AME_H, AME_I]),
            "cool": q([ADE, WMELON]), "warm": q([CHOCO, STRAW]), "cake": q([CAKE]), "cookie": q([COOKIE]),
            "wfac": d["total_factors"]["weather"],
            "demand": sum(v["demand"] for v in it.values()),
            "systematic": sum(v["systematic"] for v in it.values()),
            "any_out": d["any_sold_out"],
            "lost": sum(v.get("lost", 0) for v in it.values()),
            "odd": bool(d["special_days"] or d["promotions"] or "incident" in hid or "short_staffed" in hid
                        or "bulk_order" in hid or any(e["log_effect_visitor"] > 0.05 for e in d["public_events"])),
            "labels": ([s["label"] for s in d["special_days"]] + d["promotions"]
                       + [e["title"] for e in d["public_events"] if e["log_effect_visitor"] > 0.05]),
        })
    df = pd.DataFrame(recs)
    L = []
    dn = ["월", "화", "수", "목", "금", "토", "일"]

    L.append("### 16.1 월별 일평균 (영업일 기준)")
    L.append("")
    rows = []
    for ym, g in df.groupby("ym", sort=True):
        rows.append([ym, len(g), f0(g["visits"].mean()), f0(g["units"].mean()), f0(g["rev"].mean() / 10000.0),
                     f0(g["coffee"].mean()), f0(g["noncoffee"].mean()), f0(g["bakery"].mean()), f0(g["dessert"].mean())])
    L += md_table(["월", "영업일", "방문(건)", "판매수량", "매출(만원)", "커피", "논커피", "빵", "디저트"], rows)
    L.append("")

    normal = df[df["dtype"].isin(["평일", "주말"])]
    L.append("### 16.2 요일별 일평균 판매수량 (공휴일·연휴·징검다리 제외)")
    L.append("")
    rows = []
    for rg in ("학기", "방학"):
        g = normal[normal["regime"] == rg].groupby("dow")["units"].mean()
        rows.append([rg] + [f0(g.get(k, float("nan"))) for k in range(7)])
    L += md_table(["구분"] + dn, rows)
    L.append("")

    L.append("### 16.3 학사 국면별 (연세대 기준, 평범한 평일만)")
    L.append("")
    wk = df[df["dtype"] == "평일"]
    names = [("early_semester", "개강 후 3주"), ("semester", "학기 중 평상시"), ("pre_exam", "시험 전 10일"),
             ("exam", "시험 기간"), ("post_exam", "시험 직후 5일"), ("vacation", "방학")]
    rows = []
    for k, lab in names:
        g = wk[wk["phase"] == k]
        if len(g) == 0:
            continue
        rows.append([lab, len(g), f0(g["students"].mean()), f0(g["visits"].mean()), f0(g["units"].mean()),
                     f0(g["ame"].mean()), f1(g["cookie"].mean()), f1(g["cake"].mean())])
    L += md_table(["국면", "일수", "학생 방문", "전체 방문", "판매수량", "아메리카노", "르뱅쿠키", "케이크"], rows)
    L.append("")
    ex, ne = wk[wk["phase"] == "exam"], wk[wk["phase"].isin(["semester", "early_semester", "post_exam"])]
    L.append("- 시험 기간 평일 판매수량은 비시험 학기 평일의 **%s** (학생 방문은 %s)."
             % (pct(ex["units"].mean() / ne["units"].mean()), pct(ex["students"].mean() / ne["students"].mean())))
    L.append("")

    L.append("### 16.4 학기와 방학")
    L.append("")
    rows = []
    for lab, sel in (("평일", normal["dow"] < 5), ("주말", normal["dow"] >= 5)):
        a = normal[sel & (normal["regime"] == "학기")]["units"].mean()
        b = normal[sel & (normal["regime"] == "방학")]["units"].mean()
        rows.append([lab, f0(a), f0(b), pct(b / a)])
    L += md_table(["구분", "학기 일평균", "방학 일평균", "방학/학기"], rows)
    L.append("")

    L.append("### 16.5 휴일 유형별 일평균")
    L.append("")
    rows = []
    for k in ["평일", "주말", "단독 공휴일", "연휴", "연휴 전날", "징검다리 평일", "명절 연휴 전날", "명절 연휴", "명절 당일 전후"]:
        g = df[df["dtype"] == k]
        if len(g):
            rows.append([k, len(g), f0(g["visits"].mean()), f0(g["units"].mean())])
    L += md_table(["유형", "일수", "방문", "판매수량"], rows)
    L.append("")

    # 기준선: 같은 (학기/방학, 요일)의 맑고 사건 없는 날 평균
    base_days = normal[(normal["rain"] < 1) & (~normal["odd"])]
    base = base_days.groupby(["regime", "dow"])["units"].mean().to_dict()
    df["ratio"] = [u / base.get((r, k), float("nan")) for u, r, k in zip(df["units"], df["regime"], df["dow"])]
    nd = df[df["dtype"].isin(["평일", "주말"])]

    L.append("### 16.6 비 오는 날과 맑은 날 (평범한 평일·주말만)")
    L.append("")
    L.append("기준선은 같은 학기/방학·같은 요일의 맑고 사건 없는 날 평균이다. 계절(기온)은 통제하지 않았다.")
    L.append("")
    rows = []
    for lab, lo, hi in (("0mm", -1, 0), ("0~1mm", 0, 1), ("1~5mm", 1, 5), ("5~20mm", 5, 20),
                        ("20~40mm", 20, 40), ("40mm 이상", 40, 1e9)):
        g = nd[(nd["rain"] > lo) & (nd["rain"] <= hi)]
        if len(g):
            rows.append([lab, len(g), f0(g["units"].mean()), f2(g["ratio"].mean()), f2(g["wfac"].mean())])
    L += md_table(["일강수량", "일수", "판매수량", "기준선 대비", "모형의 날씨 배수(방문)"], rows)
    L.append("")
    dry, wet = nd[nd["rain"] < 1], nd[nd["rain"] >= 10]
    L.append("- 10mm 이상 온 날(%d일)의 기준선 대비 비율 평균 **%s**, 1mm 미만인 날(%d일) **%s**."
             % (len(wet), f2(wet["ratio"].mean()), len(dry), f2(dry["ratio"].mean())))
    L.append("")

    L.append("### 16.7 기온대별 품목 계열 (전 영업일, 방문 100건당 수량)")
    L.append("")
    rows = []
    for lab, lo, hi in (("0도 미만", -99, 0), ("0~10도", 0, 10), ("10~20도", 10, 20),
                        ("20~28도", 20, 28), ("28도 이상", 28, 99)):
        g = df[(df["tday"] >= lo) & (df["tday"] < hi)]
        if len(g) == 0:
            continue
        v = g["visits"].sum() / 100.0
        rows.append([lab, len(g), f0(g["units"].mean()), f1(g["ice"].sum() / v), f1(g["hot"].sum() / v),
                     pct(g["ice"].sum() / (g["ice"].sum() + g["hot"].sum())),
                     f1(g["cool"].sum() / v), f1(g["warm"].sum() / v), f1(g["bakery"].sum() / v),
                     f1(g["dessert"].sum() / v)])
    L += md_table(["낮 기온(평균·최고의 중간)", "일수", "일 판매수량", "ICE 커피", "HOT 커피", "아이스 비중",
                   "에이드·수박", "초코·딸기", "빵", "디저트"], rows)
    L.append("")

    L.append("### 16.8 품절")
    L.append("")
    rows = []
    for it in CAPPED:
        n = out = cap = dem = lost = 0
        for d in truth_days:
            if d["closed"] or it not in d["items"]:
                continue
            v = d["items"][it]
            n += 1
            out += 1 if v["sold_out"] else 0
            cap += v["cap"]
            dem += v["demand"]
            lost += v["lost"]
        rows.append([it, n, pct(out / n), f1(cap / n), f1(dem / n), "%.1f%%" % (100.0 * lost / dem)])
    L += md_table(["품목", "판매일수", "품절일 비중", "평균 준비량", "평균 수요", "놓친 수요 비중"], rows)
    L.append("")
    L.append("- 한 품목이라도 품절된 날: 영업일의 **%s**. 놓친 수량이 10개 이상인 날: **%s**."
             % (pct(df["any_out"].mean()), pct((df["lost"] >= 10).mean())))
    L.append("")

    L.append("### 16.9 잡음 크기")
    L.append("")
    r = np.log(df["demand"] / df["systematic"])
    L.append("- 하루 총수요를 '난수를 뺀 기대 수요(systematic)'와 견준 로그 비율의 표준편차: **%.3f** "
             "(가장 작은 날 %.2f배, 가장 큰 날 %.2f배)."
             % (float(r.std()), math.exp(float(r.min())), math.exp(float(r.max()))))
    L.append("")
    rows = []
    for lab, names_ in (("아메리카노(HOT+ICE)", [AME_H, AME_I]), ("소금빵", [SALT]), ("바스크치즈케이크", [CAKE]),
                        ("자몽에이드", [ADE]), ("햄치즈샌드위치", [SAND])):
        x = []
        for d in truth_days:
            if d["closed"]:
                continue
            a = sum(d["items"][n]["demand"] for n in names_)
            b = sum(d["items"][n]["systematic"] for n in names_)
            x.append(math.log(max(1, a) / b))
        rows.append([lab, "%.2f" % float(np.std(x))])
    L += md_table(["품목", "로그 비율 표준편차"], rows)
    L.append("")

    big = [AME_I, AME_H, LAT_I, LAT_H, ADE, SALT, CROI, CAKE, COOKIE, SAND]
    res = []
    for d in truth_days:
        if d["closed"]:
            continue
        res.append([math.log(max(1, d["items"][n]["demand"]) / d["items"][n]["systematic"]) for n in big])
    cm = np.corrcoef(np.array(res).T)
    iu = np.triu_indices(len(big), 1)
    L.append("- 주요 10개 품목의 잔차(로그 수요 - 로그 systematic) 사이 상관: 평균 **%.2f** (최소 %.2f, 최대 %.2f). "
             "잡음을 빼기 전의 원 판매량끼리는 요일·학기·날씨를 함께 타므로 훨씬 높다."
             % (float(cm[iu].mean()), float(cm[iu].min()), float(cm[iu].max())))
    L.append("")

    L.append("### 16.10 주요 사건일 (판매수량 ÷ 같은 요일 기준선)")
    L.append("")
    keys = ["2025-11-15", "2025-12-24", "2025-12-25", "2025-12-31", "2026-02-14", "2026-02-18", "2026-03-04",
            "2026-03-10", "2026-04-04", "2026-05-30", "2026-07-18", "2026-08-06", "2026-09-12", "2026-09-18",
            "2026-10-10"]
    notes = {"2026-02-14": "밸런타인데이 (설 연휴 첫날과 겹침)", "2026-02-18": "설 연휴 마지막 날",
             "2026-03-10": "에스프레소 머신 고장(숨김)",
             "2026-07-18": "일강수량 119.7mm", "2026-08-06": "폭염 중 제빙기 고장(숨김)"}
    rows = []
    byd = {r_["date"]: r_ for r_ in df.to_dict("records")}
    for k in keys:
        if k in byd:
            r_ = byd[k]
            lab = notes.get(k) or " / ".join(r_["labels"]) or r_["dtype"]
            b_ = base.get((r_["regime"], r_["dow"]), float("nan"))
            rows.append([k, dn[r_["dow"]], lab, f2(r_["systematic"] / b_), r_["units"], f2(r_["ratio"])])
    L += md_table(["날짜", "요일", "무슨 날", "설계상 기대(난수 제외) ÷ 기준선", "실제 판매수량", "실제 ÷ 기준선"], rows)
    L.append("")
    L.append("- '설계상 기대'는 품절 전 수요 기준이라 실제 판매보다 몇 % 높게 잡힌다. "
             "둘의 차이가 그날의 운·숨은 사건·품절이다.")
    L.append("")
    return L


# ---------------------------------------------------------------------------
# 14. truth.md (생성 모형 설명서)
# ---------------------------------------------------------------------------
def write_truth_md(rows, truth_days):
    n_open = sum(1 for d in truth_days if not d["closed"])
    n_closed = len(truth_days) - n_open
    L = []
    A = L.append
    A("# campus-a 시뮬레이션 정답지 (truth)")
    A("")
    A("이 문서는 `generate.py` 가 자동으로 쓴다. 손으로 고치지 말고 `generate.py` 를 고친 뒤 다시 돌린다.")
    A("")
    A("## 1. 한눈에 보기")
    A("")
    A("- 대상: 서울 서대문구 연세로 12 의 **가상** 베이커리카페 (신촌역 2호선 160m, 연세대 정문 430m, 서강대 정문 560m).")
    A("- 기간: %s ~ %s (%d일 중 영업 %d일, 휴무 %d일)." % (START, END, len(truth_days), n_open, n_closed))
    A("- `pos_raw.csv`: %d행, 품목 %d개. 하루·품목마다 한 줄이고 수량이 0 이면 줄이 없다. 휴무일도 줄이 없다."
      % (len(rows), len(ITEMS)))
    A("- `truth.json`: 날짜별 잠재 요인. 구조는 17절.")
    A("- 난수 씨앗 %d. 같은 환경에서 다시 돌리면 세 파일이 바이트 단위로 같다." % SEED)
    A("- 예측 모델 쪽 코드·문서는 전혀 보지 않았다. 효과 크기는 실제 매장 자료로 맞춘 것이 아니라 "
      "캠퍼스 상권 카페에 대한 일반 상식으로 정한 값이다.")
    A("")
    A("## 2. 실제 자료에서 그대로 가져온 것")
    A("")
    A("`drivers/` 폴더의 공개 자료를 '실제로 일어난 일'로 쓴다.")
    A("")
    A("- `external_daily.csv`: 요일, 공휴일, 서울 일별 기온(평균·최저·최고)과 강수량. 2025-10-22 부터 읽는다"
      "(직전 10일 평균 기온이 필요해서).")
    A("- `events.json` 학사일정: 연세대·서강대·이화여대의 개강일, 시험 기간, 방학 기간, 서강대 축제. "
      "연세대 축제와 이화여대 기말시험은 자료에 없다.")
    A("- `events.json` 문화행사: 매장 반경 800m 안의 서울시 문화행사 (기간 안에 걸치는 것은 15건).")
    A("- `external_daily.csv` 의 `exam_period`·`vacation`·`festival`·`nearby_event` 열은 **쓰지 않았다.** "
      "같은 정보를 `events.json` 원본에서 직접 읽었다.")
    A("- `campus-a_nearby.json` 은 고객층을 정할 때 참고만 했다 (세브란스병원 500m, 공연장·영화관 300m 안쪽, "
      "초·중학교는 카페 수요와 무관하다고 보고 제외).")
    A("")
    A("## 3. 고객층과 방문 목적")
    A("")
    A("판매량을 '평균 × 배수'로 만들지 않고, **누가 왜 왔는지**에서 출발한다. "
      "방문 1건은 결제 1건(일행 한 팀)이다.")
    A("")
    A("### 3.1 고객층 10개")
    A("")
    A("기준 방문은 '학기 중 평범한 평일'의 하루 결제 건수다.")
    A("")
    why = {
        "yonsei": "신촌역에서 정문으로 가는 길목. 가장 큰 층. 신입생은 송도 캠퍼스에 있어 3월 효과가 다른 학교보다 약하다고 봄",
        "sogang": "통학로가 반대편이라 등굣길 구매는 적고 약속 위주",
        "ewha": "1.1km 떨어져 있어 신촌으로 놀러 올 때만 옴",
        "staff": "평일 출근길·점심 뒤. 주말엔 거의 없음",
        "hospital": "학사일정과 무관. 토요일 오전 외래까지. 병문안용 빵 포장이 많음",
        "office": "신촌 상가·사무실. 방학과 무관, 휴가철에만 줄어듦",
        "resident": "빵 포장이 중심. 주말에 더 옴. 자취생이 많아 방학·명절에 줄어듦",
        "visitor": "금·토·일에 몰림. 날씨와 행사에 가장 민감",
        "tourist": "봄·가을 성수기. 날마다 변동이 큼",
        "academy": "방학 특강 때 오히려 늘어남",
    }
    rws = []
    for s in SEGS:
        rws.append([SEG_LABEL[s], BASE[s]] + ["%d%%" % round(100 * x) for x in MIX[s]] + [W_SEG[s], why[s]])
    L.extend(md_table(["고객층", "기준 방문"] + [MIS_LABEL[m] for m in MISSIONS] + ["날씨 민감도", "특징"], rws))
    A("")
    A("합계 %d건. 학생 3개 층이 평일 방문의 약 %d%%를 차지한다."
      % (sum(BASE.values()), round(100.0 * sum(BASE[s] for s in STUDENTS) / sum(BASE.values()))))
    A("")
    A("### 3.2 방문 목적 5개와 장바구니")
    A("")
    rws = []
    for m in MISSIONS:
        rws.append([MIS_LABEL[m], DPV[m], BPV[m], DSV[m], "%d%%" % round(100 * CS[m]),
                    W_RAIN_MIS[m], W_TEMP_MIS[m]])
    L.extend(md_table(["방문 목적", "음료(잔)", "빵(개)", "디저트(개)", "음료 중 커피", "비 민감도", "기온 민감도"], rws))
    A("")
    A("- 빵 품목 선택 무게(소금빵/크루아상/스콘/샌드위치)와 디저트 선택 무게(케이크/쿠키)도 방문 목적마다 다르다. "
      "예: 식후 커피 손님은 샌드위치 50%, 약속 손님은 케이크 70%, 카공 손님은 쿠키 70%.")
    A("- 고객층마다 커피 안의 아메리카노 비중(학생 72%, 관광객 50%), 빵·디저트 선호, 논커피 취향이 다르다. "
      "값은 `generate.py` 의 `AW`, `BAFF`, `DAFF`, `TASTE` 에 있다.")
    A("")
    A("### 3.3 요일 리듬")
    A("")
    A("고객층·방문 목적마다 요일 지수가 다르다(`DOWP`). 핵심만 적으면:")
    A("")
    A("- 학생: 금요일 등굣길 0.78(공강), 주말 등굣길 0.05 이하, 주말 카공 0.65~0.70, 금요일 약속 1.15.")
    A("- 교직원: 토 0.08, 일 0.03. 직장인: 토 0.28, 일 0.18. 병원: 토 0.50, 일 0.25.")
    A("- 방문객: 월 0.62 → 목 0.82 → 금 1.15 → **토 2.25** → 일 1.75.")
    A("- 거주자: 주말 1.4~1.45. 관광객: 주말 1.25~1.35. 학원: 토 0.60, 일 0.25.")
    A("- 그 결과 학기 중에는 금요일이 가장 많이 팔리고 토요일은 평일과 비슷하며 일요일이 가장 적다. "
      "방학에는 평일이 꺼지면서 금·토가 상대적으로 더 두드러진다.")
    A("")
    A("## 4. 학사 리듬 (공개 자료로 관측 가능)")
    A("")
    A("실제 학사일정의 날짜를 쓰고, 학교별로 따로 계산한다. 학생 층에만 직접 작용한다.")
    A("")
    L.extend(md_table(["국면", "모형", "근거"], [
        ["개강 직후", "r = exp(-개강 후 일수/10). 약속 ×(1+1.0r), 식후 ×(1+0.3r), 등굣길 ×(1+0.15r), 카공 ×(1-0.5r). 첫 주 학생 방문 약 +15%",
         "개강 모임·동아리 모집·수업이 일찍 끝나는 오리엔테이션 주간. 과제가 없어 카공은 준다"],
        ["학기 후반", "개강 70일 뒤부터 등굣길 ×0.96", "출석률이 서서히 떨어진다"],
        ["시험 전 10일", "카공 ×1.0→1.7 (선형), 약속 ×1.0→0.8", "벼락치기. 놀 약속은 미룬다"],
        ["시험 기간", "시험이 남은 학생 비율 rem 이 1.0→0.3 으로 줄어든다. 등굣길 ×0.62, 식후 ×0.75×(0.6+0.4rem), "
         "카공 ×(1+0.9rem)×(0.55+0.45rem) (기말은 0.9 대신 1.1), 약속 ×(0.45+0.75(1-rem)), 포장 ×0.9",
         "수업이 없어 등굣길 구매가 줄고, 시험이 끝난 학생부터 캠퍼스를 떠난다. 첫날은 평소의 약 0.9배, 마지막 날은 약 0.75배"],
        ["시험 기간 장바구니", "카공 방문의 음료 +12%, 커피 비중 +8%p, 아메리카노 무게 ×1.2, 쿠키 무게 ×1.6 (모두 시험 강도에 비례)",
         "오래 앉아 한 잔 더 시키고, 달달한 라떼·케이크보다 카페인과 간단한 당 충전"],
        ["중간고사 직후 5일", "카공 ×0.6, 약속 ×1.12", "풀려난 주간"],
        ["방학", "신촌에 남은 학생 비율 p: 종강 직후 4일 0.50 → 계절학기(약 3주) 0.40 → 한가운데 0.27 → 개강 전 10일 동안 0.50 까지 회복. "
         "등굣길 0.8p, 식후 p, 카공 1.5p, 약속 1.3p, 포장 p", "계절학기·취업 준비생만 남고, 개강 전에 자취방으로 돌아온다"],
        ["방학 중 다른 고객층", "거주자 ×0.80, 방문객 평일 ×1.12, 학원 수강생 ×1.55, 교직원 ×0.90. "
         "7/27~8/14 휴가철엔 교직원·직장인 ×0.85, 병원 ×0.95", "자취생 귀향, 방학 특강, 휴가"],
    ]))
    A("")
    A("- 이화여대는 자료에 기말시험이 없어 **종강일까지 5일을 기말로 가정**했다. 이화여대 층은 작아서 영향은 미미하다.")
    A("- 자료상 기말시험 종료와 방학 시작 사이에 하루 비는 날(예: 2025-12-21)은 방학으로 처리했다.")
    A("- 전체 효과는 생각보다 작다. 시험 기간 학생 방문은 약 -15% 지만 매장 전체로는 -6~8% 수준이다. "
      "역 앞 상권이라 학생이 아닌 손님이 절반을 넘기 때문이다.")
    A("")
    A("## 5. 휴일·연휴·명절 (공개 자료로 관측 가능)")
    A("")
    A("`is_holiday` 와 요일로 '연속으로 쉬는 날이 며칠인가'를 계산해 날을 분류한다.")
    A("")
    L.extend(md_table(["날의 종류", "모형", "근거"], [
        ["평일 공휴일 공통", "수업·근무에 묶인 층(연세·서강·교직원·병원·직장인·학원)은 일요일 리듬, 놀러 오는 층(방문객·관광객·거주자·이화)은 토요일 리듬",
         "수업과 출근이 없다"],
        ["단독 공휴일 (연속 휴일 3일 미만)", "연세·서강·학원 ×1.5, 병원·직장인 ×1.2, 방문객 ×0.85", "하루만 쉬면 학생이 본가로 가지 않고 신촌에 남는다"],
        ["연휴 (3일 이상, 명절 제외)", "연세·서강 ×0.80 (방학 중이면 0.95), 거주자 ×0.88, 방문객 ×0.92", "학생은 본가로, 서울 사람은 여행으로 빠진다"],
        ["명절 연휴 중 설날·추석으로 표시된 3일", "학생 ×0.35, 거주자·방문객·직장인 ×0.50, 병원 ×0.70, 관광객 ×0.90, 학원 ×0.20", "신촌이 텅 빈다"],
        ["명절 연휴에 붙은 주말", "학생 ×0.60, 거주자 ×0.70, 방문객 ×0.75", "귀성 행렬"],
        ["명절 연휴 전날", "연세·서강 ×0.75, 교직원 ×0.90, 직장인 ×0.95, 방문객 ×0.90, 포장 구매 ×1.15", "오후부터 귀성. 선물용 빵"],
        ["연휴 전날", "연세·서강 ×0.90, 방문객 ×1.08", "일찍 떠나는 학생, 저녁 약속"],
        ["징검다리 평일", "연세·서강 ×0.75, 교직원 ×0.80, 직장인 ×0.88, 방문객 ×1.10", "휴강과 연차"],
        ["월초·월말", "학생의 약속·포장 구매: 1~7일 ×1.04, 23일 이후 ×0.97", "용돈 주기"],
    ]))
    A("")
    A("- 공휴일 여부는 `external_daily.csv` 를 그대로 따랐다 (2026-05-01 노동절, 2026-07-17 제헌절 포함).")
    A("")
    A("## 6. 날씨 (공개 자료로 관측 가능, 단 비 오는 시간대는 숨김)")
    A("")
    A("### 6.1 방문에 주는 효과")
    A("")
    A("- 낮 기온 `t_day` = (일평균 + 일최고)/2. 대비 `contrast` = t_day - 직전 10일 평균.")
    A("- 비(로그 효과, 민감도 1.0 기준): `-0.40 × (1 - exp(-r/22)) - 0.03` (0.5mm 이상일 때). "
      "보슬비는 거의 무시되고 폭우에서 포화한다. 3mm -0.08, 10mm -0.18, 30mm -0.33, 80mm -0.42.")
    A("  - 평균기온 0.5도 미만의 강수는 눈으로 보고 강수량을 2.5배로 친다.")
    A("  - 직전 이틀도 3mm 이상 왔으면 ×0.85 (장마 사흘째면 사람들이 익숙해진다).")
    A("  - **숨은 요인**: 그날 비가 영업시간에 왔는지를 뜻하는 계수 U(0.35, 1.25) 를 곱한다 (40mm 이상이면 U(0.70, 1.25)). "
      "일강수량만으로는 알 수 없는 부분이다.")
    A("- 기온(로그 효과): 5도 미만은 1도마다 -0.013, 5~13도는 0 → +0.05, 13~25도는 +0.05(쾌적), "
      "25~29도는 +0.05 → -0.02, 29도 이상은 1도마다 -0.012 추가. 역 U자다.")
    A("  - 갑자기 추워진 날(contrast < -5)은 -0.04. 봄(2~5월)에 갑자기 포근해진 날(contrast > +5, 10도 초과)은 +0.05.")
    A("- 실제 배수 = exp(고객층 민감도 × (목적별 비 민감도 × 비 효과 + 목적별 기온 민감도 × 기온 효과)). "
      "방문객의 약속은 10mm 비에 약 -16%, 교직원의 출근길 커피는 약 -2% 다.")
    A("")
    A("### 6.2 무엇을 사는지에 주는 효과 (아이스·핫 대체)")
    A("")
    A("- 체감 기온 `t_eff` = t_day + 0.3 × contrast(±8도로 제한) - 1.5 × min(1, 강수량/10). "
      "같은 10도라도 가을 첫 추위에는 더 춥게, 봄 첫 더위에는 더 덥게 느낀다.")
    A("- 아메리카노가 아이스일 확률 = 0.22 + 0.74 × σ((T - 10)/6). 라떼는 0.08 + 0.84 × σ((T - 14)/5.5). "
      "T 는 t_eff 에 고객층 보정(학생·학원 +3도, 병원 -4도, 교직원 -3도 등)을 더한 값이다.")
    A("  - 즉 총 커피 수요는 기온에 거의 평평하고 **HOT 과 ICE 가 서로 자리를 바꾼다.** 한겨울에도 학생은 3~4할이 아이스다.")
    A("- 추울수록 커피 안에서 라떼 무게가 최대 +30% (따뜻한 우유 음료 선호).")
    A("- 논커피는 매력도 경쟁이다. 초코라떼 0.50 × (0.55 + 0.95σ((11-T)/5)), 자몽에이드 0.18 + 1.60σ((T-19)/4), "
      "생딸기라떼 1.35 × 월 계수(12월 1.0, 1월 1.1, 2~3월 1.25, 4월 1.0) × 끝물 감쇠, 수박주스 1.25σ((T-21)/3.5), 말차라떼 0.75 안팎. "
      "'마실 게 없다'는 선택지 무게 0.70 과 경쟁하며, 못 고른 손님의 절반은 커피로 간다. "
      "그래서 신메뉴·계절 메뉴가 생기면 논커피 전체가 조금 늘고 기존 논커피는 조금 잠식된다.")
    A("- 폭염 지수 = (일최고 - 28)/7 을 0~1 로 자른 값. 폭염일에는 방문 1건당 음료 +12%, 빵 -12%, 디저트 -5%. "
      "사람은 덜 다니지만 들어온 손님은 찬 음료를 더 시키므로 음료 판매는 버티고 빵이 준다.")
    A("- 추운 날에는 빵이 최대 +5%.")
    A("")
    A("## 7. 행사")
    A("")
    A("### 7.1 공개 문화행사 (`events.json`, 관측 가능)")
    A("")
    A("방문객 층의 로그 효과 = 규모(분류) × exp(-거리/250m). 규모는 거리 축제 0.45, 자연·경관 축제 0.25, 콘서트 0.10, "
      "연극·무용 0.05, 전시 0.02. 같은 효과가 관광객 60%, 거주자 30%, 학생의 약속 35% 만큼 번진다.")
    A("")
    seen = {}
    for d in truth_days:
        for e in d["public_events"]:
            k = e["title"]
            if k not in seen:
                seen[k] = [d["date"], d["date"], e["category"], e["distance_m"], e["log_effect_visitor"]]
            seen[k][1] = d["date"]
    rws = []
    for k, v in seen.items():
        rws.append([v[0], v[1], k, v[2], v[3], "%+.1f%%" % (100.0 * (math.exp(v[4]) - 1.0))])
    L.extend(md_table(["시작", "끝", "행사", "분류", "거리(m)", "방문객 효과"], rws))
    A("")
    A("- 15건 가운데 의미 있는 것은 가게 앞에서 열린 3건(카운트다운 콘서트, 벚꽃 버스킹, 신촌글로벌대학문화축제)뿐이다. "
      "500m 밖 소규모 전시·연극은 1% 미만이다. `nearby_event` 건수가 2~3 으로 찍힌 2026-11 초순도 실제 효과는 거의 없다.")
    A("- 카운트다운 콘서트는 자정을 넘겨 끝나 종료일이 1월 1일로 찍혀 있지만 효과는 12월 31일에만 준다.")
    A("")
    A("### 7.2 기념일과 학교 행사")
    A("")
    A("`출처` 열: **고정** = 해마다 날짜가 같은 기념일, **자료** = `events.json` 에 있는 실제 일정, "
      "**가정** = 일반 상식으로 넣었고 **날짜는 확인하지 못함** (assumed from general knowledge, date not verified).")
    A("")
    src = {"fixed": "고정", "file": "자료", "assumed": "가정"}
    rws = []
    for sp in sorted(SPECIALS, key=lambda x: (x[0], x[1])):
        seg = ", ".join("%s/%s ×%.2f" % (s, m, x)
                        for (s, m), x in sp[4].items())
        itm = ", ".join("%s ×%.2f" % (k, x) for k, x in sp[5].items())
        rws.append([sp[0] if sp[0] == sp[1] else sp[0] + "~" + sp[1][5:], sp[2], src[sp[3]], seg or "-", itm or "-"])
    L.extend(md_table(["날짜", "무슨 날", "출처", "고객층/방문목적 배수", "품목 배수"], rws))
    A("")
    A("- 고객층 이름은 코드의 키(yonsei, sogang, visitor …)이고 `*` 는 모든 방문 목적이다.")
    A("- 관광객 층에는 월별 계절 계수(1월 0.70 ~ 10월 1.30)와 연 10% 증가를 곱한다.")
    A("- 서강대 축제는 공개 자료에 있지만 효과는 서강대 층 안의 구성 변화뿐이라 매장 전체로는 거의 0 이다. "
      "반대로 효과가 큰 연세대 축제·연고전·논술고사는 공개 자료에 없다.")
    A("")
    A("## 8. 메뉴")
    A("")
    rws = []
    for it in ITEMS:
        a, b = AVAIL.get(it, (None, None))
        pr = " → ".join("%s원%s" % (format(p, ","), "" if i == 0 else "(%s~)" % s) for i, (s, p) in enumerate(PRICE[it]))
        period = "전 기간"
        if a and b:
            period = "%s ~ %s (계절 한정)" % (a, b)
        elif a:
            period = "%s 출시" % a
        elif b:
            period = "%s 까지 판매 후 단종" % b
        rws.append([it, {"coffee": "커피", "noncoffee": "논커피", "bakery": "빵", "dessert": "디저트"}[FAMILY[it]],
                    pr, period, "있음" if it in CAPPED else "-", ITEM_NOTE[it]])
    L.extend(md_table(["상품명", "계열", "정가", "판매 기간", "하루 준비량 상한", "특징"], rws))
    A("")
    A("- 가격 인상: 2026-02-02 커피 4종 +300원 (수요 -6% 로 시작해 20일쯤 뒤 -3% 로 안정), "
      "2026-07-01 소금빵 +300원 (-7% → -3%).")
    A("- 신메뉴 말차라떼: 출시 직후 매력도 1.9배에서 12일 시상수로 가라앉고, 이후 200일에 걸쳐 12% 더 식는다.")
    A("- 단종 플레인스콘: 인기가 기간 내내 줄어 단종 시점에 처음의 60%. 단종 뒤 스콘 수요의 일부만 다른 빵으로 간다 "
      "(빵 전체 수요 ∝ 남은 품목 무게 합의 0.4제곱).")
    A("- 느린 인기 변화: 소금빵 연 +12%%, 크루아상 연 -7%%, 르뱅쿠키 연 +5%%. 여기에 품목마다 숨은 떠돌이(하루 표준편차 %.1f%%)가 얹힌다." % (100 * SD_POP_RW))
    A("- POS 표기: 커피 2종만 HOT/ICE 가 따로 등록되어 있고 나머지 음료는 온도 구분 없이 한 줄이다 "
      "(점주가 버튼을 그렇게 등록했다는 설정).")
    A("")
    A("## 9. 운영")
    A("")
    A("### 9.1 하루 준비량과 품절")
    A("")
    A("- 빵 4종·디저트 2종·계절 음료 2종은 점주가 아침에 준비한 수량만 판다. **품절로 못 판 수요는 POS 에 남지 않는다.**")
    A("- 점주는 정답(수요)을 모른다. 자기 판매 기록만 보고 정한다: "
      "준비량 = 수준(지수평활 α=0.12) × 요일 지수(α=0.10) × 달력 조정 × 여유율 을 굽는 단위로 반올림.")
    A("")
    rws = [[it, CAPPED[it][0], "%.2f" % CAPPED[it][1]] for it in CAPPED]
    L.extend(md_table(["품목", "한 번에 만드는 단위", "여유율"], rws))
    A("")
    A("- 달력 조정(점주가 미리 아는 것): 명절 당일 전후 ×0.55·명절 연휴에 붙은 주말 ×0.8, 방학 첫 주 ×0.8, 개강 첫 주 ×1.2, 시험 기간 ×0.95, "
      "큰비(20mm 이상) ×0.92, 가게 앞 거리 축제 ×1.2, 12/23~25 케이크 ×1.7·쿠키 ×1.2·딸기 ×1.2, 2/14·3/14 쿠키 ×1.25·케이크 ×1.15.")
    A("- 품절된 날 점주는 놓친 수요의 60%쯤을 짐작해 다음 계획에 반영한다 (품절 시각과 찾는 손님 수로 어림).")
    A("- 품절된 빵(소금빵·크루아상·스콘) 수요의 35%는 남아 있는 다른 빵으로 옮겨 가고, 케이크가 떨어지면 25%가 쿠키로 간다. 나머지는 사라진다.")
    A("- 이 구조 때문에 개강처럼 수요가 갑자기 뛰는 시기에 품절이 몰리고, 방학 초에는 남는다. "
      "소금빵은 일부러 빠듯하게 굽는 간판 품목이라 사흘에 하루꼴로 품절된다.")
    A("")
    A("### 9.2 휴무·단축 영업")
    A("")
    L.extend(md_table(["날짜", "사유"], [[k, v] for k, v in CLOSURES.items()]
                      + [[k, v[1] + " (전체 ×%.2f)" % v[0]] for k, v in SHORT_HOURS.items()]))
    A("")
    A("- 정기 휴무일은 없다. 휴무는 모두 가상의 설정이다 (동파 휴무일만 실제 한파 날짜에 맞췄다).")
    A("")
    A("### 9.3 할인 행사 (POS 의 판매금액 ÷ 수량으로 드러남)")
    A("")
    rws = []
    for p_ in PROMOS:
        rws.append([p_[0] + "~" + p_[1][5:], p_[4],
                    ", ".join("%s ×%.2f" % (k, x) for k, x in p_[3].items())])
    L.extend(md_table(["기간", "내용", "수요 배수"], rws))
    A("")
    A("### 9.4 공개 자료에 없는 운영 충격 (모두 가상)")
    A("")
    rws = [[k, v[0], ", ".join("%s ×%.2f" % (a, b) for a, b in v[1].items()) or "-",
            ", ".join("%s ×%.2f" % (a, b) for a, b in v[2].items()) or "-"] for k, v in INCIDENTS.items()]
    L.extend(md_table(["날짜", "사고", "수요 배수", "준비량 배수"], rws))
    A("")
    A("- 일손 부족: 평소 하루 2%, 시험 전·시험 기간에는 6% 확률 (알바생도 학생이다). 그날 전 품목 ×0.80~0.90.")
    A("- 단체 주문: 학기 중 평일 6%, 방학 평일 2%, 휴일 1% 확률. 아메리카노 15~40잔, 절반은 소금빵이나 르뱅쿠키 10~24개가 붙는다. "
      "예약 주문이라 준비량 상한과 무관하게 판매에 더해진다 (POS 에서는 튀는 값으로 보인다).")
    A("- 근처 공연·개봉(공개 자료에 없는 것): 금 22%, 토 30%, 일 18%, 평일 5% 확률로 방문객의 약속·식후 방문 +5~18%.")
    A("- 저가 커피 매장 개업 (%s): 연세·서강·학원·직장인의 등굣길·식후 방문 ×(1 - 0.06 - 0.07·exp(-일수/14)). "
      "개업 직후 -13%%, 이후 -6%% 로 굳는다." % COMPETITOR_OPEN)
    A("- 매장 앞 보도 공사 (%s ~ %s): 방문객·관광객·거주자 ×0.92." % CONSTRUCTION)
    A("- 소금빵 SNS 화제 (%s): 소금빵 인기 ×(1 + 0.40·exp(-일수/9))." % VIRAL_START)
    A("- 매장 성장: 연 %d%% + 숨은 떠돌이(하루 표준편차 %.1f%%)." % (round(100 * ANNUAL_GROWTH), 100 * SD_RW))
    A("")
    A("## 10. 잡음")
    A("")
    A("- 그날의 운(전 품목 공통): 독립 로그정규 σ=%.3f + 며칠 이어지는 AR(1) (ρ=%.1f, 혁신 σ=%.3f). "
      "미세먼지, 주변 가게 행사 같은 이름 없는 요인이다." % (SD_DAY, RHO_AR, SD_AR))
    A("- 고객층별 운: 로그정규 σ = " + ", ".join("%s %.2f" % (s, SD_SEG[s]) for s in SEGS) + ".")
    A("- 방문 건수: 기대값 주변의 포아송. 단 등굣길·식후 커피는 단골의 습관이라 분산을 절반으로 줄였다(이항).")
    A("- 품목 계열별 운 σ = " + ", ".join("%s %.2f" % (f, SD_FAM[f]) for f in FAMILIES)
      + ", 품목별 운 σ = %.2f, 그 위에 음이항 계수 잡음(k=%d)." % (SD_ITEM, int(NB_K)))
    A("- 공통 요인이 여럿이라 바쁜 날은 모든 품목이 같이 바쁘다. 다만 하루 수십 개 팔리는 품목은 "
      "'어느 손님이 무엇을 골랐나'의 우연이 커서 품목 사이 잔차 상관은 크지 않다 (16.9 참고).")
    A("")
    A("## 11. 무엇이 보이고 무엇이 숨겨져 있나")
    A("")
    L.extend(md_table(["요인", "예측하는 쪽에서 알 수 있는가", "비고"], [
        ["요일, 공휴일, 연휴 길이, 명절", "예 (`external_daily.csv`)", "연휴 길이·징검다리는 직접 계산해야 함"],
        ["기온, 강수량", "예 (관측값. 미래는 예보)", "비선형·대체 효과. 비 시간대는 숨김"],
        ["개강·시험·방학", "예 (`exam_period`, `vacation`, `events.json`)", "시험 전 10일, 개강 직후, 방학 안의 계절학기·개강 전 회복은 날짜에서 유도해야 함"],
        ["서강대 축제", "예 (`festival`)", "효과는 거의 0"],
        ["가게 앞 문화행사 3건", "예 (`nearby_event`, `events.json`)", "건수만 보면 500m 밖 전시와 구분이 안 됨. 거리·분류를 봐야 함"],
        ["크리스마스·밸런타인·화이트데이·빼빼로데이·핼러윈·연말", "달력으로 유도 가능", "drivers 열에는 없음"],
        ["월초·월말 용돈 주기", "달력으로 유도 가능", "작은 효과"],
        ["가격·할인", "POS 의 판매금액 ÷ 수량", "할인 예정은 점주만 앎"],
        ["신메뉴·단종·계절 메뉴·휴무", "POS 에 줄이 있고 없음으로", "예정은 점주만 앎"],
        ["매장 성장, 품목 인기 변화, 경쟁점 개업", "과거 판매의 수준 변화로만", "원인은 숨김"],
        ["품절로 놓친 수요", "아니오", "POS 에는 준비량에서 잘린 값만 남음"],
        ["연세대 축제·아카라카·연고전·논술고사·학위수여식, 수능", "주어진 drivers 에는 없음", "공개 일정이긴 하나 날짜는 가정"],
        ["근처 공연, 단체 주문, 일손 부족, 기기 고장, 공사, SNS 화제", "아니오", "truth.json 의 hidden 에 기록"],
        ["비가 영업시간에 왔는지, 그날의 운", "아니오", "줄일 수 없는 잡음"],
    ]))
    A("")
    A("## 12. 일반 상식으로 넣은 날짜 (확인하지 못함)")
    A("")
    A("아래 날짜는 공개 자료에 없어서 통상적인 시기로 **가정**했다. 실제 날짜와 다를 수 있다.")
    A("")
    for sp in sorted(SPECIALS, key=lambda x: (x[0], x[1])):
        if sp[3] == "assumed":
            A("- %s%s: %s" % (sp[0], "" if sp[0] == sp[1] else " ~ " + sp[1], sp[2]))
    A("- 이화여대 기말시험: 종강일까지 5일로 가정.")
    A("- 딸기 철(12월 초~4월 말), 수박 철(6월 초~9월 초), 7말8초 휴가철도 통상적인 시기로 잡았다.")
    A("")
    A("## 13. 알려진 한계")
    A("")
    A("- 효과 크기는 실제 매장 자료로 보정한 값이 아니다. 방향과 대략의 크기만 상식에 맞췄다.")
    A("- 하루 단위다. 시간대, 품절 시각, 좌석 만석(시험 기간 자리 회전 저하)은 없다.")
    A("- 메뉴가 15개뿐이다. 실제 매장은 30~60개이고 샷 추가·사이즈 같은 옵션, 환불·취소, 배달이 있다.")
    A("- 점주가 그날 강수량을 미리 정확히 안다고 두었다 (예보 오차 없음).")
    A("- 케이크·쿠키의 이월 재고를 다루지 않았다. 남은 것은 그날 버린 것으로 친다.")
    A("- 고객층끼리는 그날의 공통 운 말고는 독립이다. 실제로는 날씨 좋은 날 학생 약속과 방문객이 더 강하게 같이 움직일 수 있다.")
    A("- 폭염에 음료가 느는 정도, 장마 사흘째의 적응, 첫 추위의 대비 효과는 그럴듯한 가정일 뿐이다.")
    A("- 병원 수요는 학사일정과 무관한 상수에 가깝게 두었다. 실제 외래 일정·파업 같은 변수는 없다.")
    A("- 연세로 차 없는 거리 운영 여부, 미세먼지, 눈 온 다음 날 빙판길은 따로 넣지 않았고 잡음에 섞여 있다.")
    A("- 연세대 신입생이 송도에 있다는 점은 '3월 추가 효과를 넣지 않는다'는 식으로만 반영했다.")
    A("- 기간이 1년 남짓이라 같은 계절이 한 번씩만 나온다. 11월 초~중순만 두 번 나온다.")
    A("- 수능·논술·연세대 축제·연고전 날짜는 12절처럼 가정이다.")
    A("")
    A("## 14. 재현 방법")
    A("")
    A("저장소 루트에서 `.venv/Scripts/python.exe data/sample/campus-a/generate.py` 를 돌리면 "
      "`pos_raw.csv`, `truth.json`, `truth.md` 가 다시 만들어진다. 표준 라이브러리와 numpy·pandas 만 쓴다.")
    A("")
    A("## 15. 계산 순서 요약")
    A("")
    A("1. 날짜마다 공개 맥락을 만든다 (휴일 구조, 학교별 학사 국면, 날씨 지표, 그날 걸친 행사).")
    A("2. 고객층 × 방문 목적 기대 방문 = 기준 × 요일 × 학사 × 휴일 × 날씨 × 공개 행사 × 기념일 × 숨은 구조 변화 × 그날의 운.")
    A("3. 방문 건수를 뽑고, 방문 목적별 장바구니와 그날 기온·메뉴 구성으로 품목별 기대 수요를 만든다.")
    A("4. 품목 단위 배수(기념일, 할인, 가격 인상, 사고, 일손 부족, 품목 잡음)를 곱하고 실제 수요를 뽑는다.")
    A("5. 점주의 준비량으로 자르고, 품절 수요 일부를 다른 품목으로 옮긴 뒤, 단체 주문을 더해 POS 수량을 만든다.")
    A("6. 점주가 그날 판매를 보고 다음 준비량 감각을 고친다.")
    A("")
    A("## 16. 점검 통계 (산출물에서 계산)")
    A("")
    L.extend(sanity_stats(truth_days))
    A("## 17. truth.json 구조")
    A("")
    A("- `meta`: 기간, 씨앗, 필드 설명.")
    A("- `segments`, `missions`: 고객층·방문 목적의 기준값.")
    A("- `menu`: 품목별 계열, 가격 이력, 출시일·단종일, 계절 여부, 준비량 단위.")
    A("- `closures`, `promotions`, `special_days`, `hidden_shocks`: 날짜가 박힌 사건 목록.")
    A("- `days[]`: 날짜별 기록.")
    A("  - `calendar`, `academic`(학교별 국면), `weather`(체감 기온, 비·기온 로그 효과, 숨은 비 시간대 계수), "
      "`public_events`, `special_days`, `promotions`.")
    A("  - `hidden`: 그날의 운, 추세, 근처 공연, 일손 부족, 사고, 단체 주문, 경쟁점·공사 배수.")
    A("  - `segments.<고객층>`: 기대 방문, 실제 방문, 원인별 배수(`dow → academic → calendar → weather → public_event → "
      "special_day → hidden_structural → noise` 순서로 곱한 것). `total_factors` 는 전체 합계 기준.")
    A("  - `missions`: 방문 목적별 실제 방문 건수.")
    A("  - `items.<상품명>`: `price`(그날 단가), `systematic`(난수를 뺀 기대 수요), `mean_demand`(그날 방문객·잡음 반영 기대 수요), "
      "`demand`(사려던 수량), `cap`(준비량), `sold`(POS 수량), `lost`(품절로 놓친 수량), `sold_out`, `spill_in`, `bulk`, `mult`(품목 배수와 이유).")
    A("  - 휴무일은 `closed: true` 와 사유만 있고 `segments`·`items` 가 없다.")
    A("")
    path = os.path.join(HERE, "truth.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    return path


if __name__ == "__main__":
    rows, truth_days, ctxs = simulate()
    p1 = write_pos(rows)
    p2 = write_truth_json(truth_days)
    p3 = write_truth_md(rows, truth_days)
    for p in (p1, p2, p3):
        print("%-12s %10d bytes" % (os.path.basename(p), os.path.getsize(p)))
    print("rows=%d days=%d open=%d items=%d" % (
        len(rows), len(truth_days), sum(1 for d in truth_days if not d["closed"]), len(ITEMS)))
