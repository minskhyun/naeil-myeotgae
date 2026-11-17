"""파일이 놓이는 곳. 폴더 위치를 바꾸려면 이 파일만 고친다.

    data/sample/{매장}/      가상 매장 (저장소에 들어 있음)
    data/raw/                실제 POS 파일, 웹으로 올린 파일, 주소·행사 글 캐시   ← 커밋 안 함
    data/artifacts/{매장}/   매장별 결과 (store.json, sales_clean.csv, signals.csv, backtest.json, forecast.json …)  ← 커밋 안 함
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # 프로젝트 맨 위 폴더
SAMPLE = ROOT / "data" / "sample"
RAW = ROOT / "data" / "raw"
ARTIFACTS = ROOT / "data" / "artifacts"
