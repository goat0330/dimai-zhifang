FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.11.7
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev

EXPOSE 8011
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011"]
