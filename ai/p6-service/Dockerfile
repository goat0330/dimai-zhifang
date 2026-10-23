FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 P6_RUNTIME_PROFILE=/data/P6_runtime_profile.json
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api.py ./api.py
COPY dynamic_rainfall ./dynamic_rainfall

EXPOSE 8017
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8017"]
