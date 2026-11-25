# Hakoniwa engine + viewer. World models never run in this container:
# they run in the sandbox service (see docker-compose.yml).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27"
COPY prices.json ./
COPY sandbox ./sandbox
COPY hakoniwa ./hakoniwa
EXPOSE 8787
CMD ["python", "-m", "hakoniwa", "serve", "--host", "0.0.0.0", "--port", "8787"]
