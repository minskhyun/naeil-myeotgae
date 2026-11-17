# 클라우드 공개용 이미지: 화면 빌드 + 백엔드를 한 주소로, 시연 모드(보기 전용)
#   docker build -t naeil-myeotgae . && docker run -p 8000:8000 naeil-myeotgae   → http://localhost:8000
# Render는 이 파일로 알아서 빌드한다 (render.yaml). 노트북 시연은 이 파일 없이 평소처럼 실행한다.

# 1) 화면 빌드 → frontend/dist
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) 파이썬 서버
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEMO_MODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY contracts/ contracts/
COPY ml/ ml/
COPY agent/ agent/
COPY backend/ backend/
COPY run.py ./
COPY --from=web /web/dist frontend/dist
EXPOSE 8000
# Render 등은 PORT 환경 변수로 포트를 알려 준다 (없으면 8000)
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
