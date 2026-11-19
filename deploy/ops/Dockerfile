FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# The service only reads; run it unprivileged with a read-only root filesystem
# (set in compose) and no shell tooling beyond the Python runtime.
USER 65532:65532
EXPOSE 8099

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099", "--no-access-log"]