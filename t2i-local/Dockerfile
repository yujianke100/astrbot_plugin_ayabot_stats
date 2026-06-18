FROM python:3.11-slim

WORKDIR /app

# 安装 Chromium + 依赖
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 6199

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "6199"]
