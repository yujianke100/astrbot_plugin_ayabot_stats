FROM python:3.12-slim

WORKDIR /app

# 安装 Playwright + Chromium（仅 Chromium，不含 Firefox/WebKit）
RUN pip install --no-cache-dir playwright>=1.40.0 fastapi>=0.100.0 uvicorn>=0.23.0 python-multipart>=0.0.9 \
    && playwright install --with-deps chromium

COPY server.py .

EXPOSE 6199

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "6199"]
