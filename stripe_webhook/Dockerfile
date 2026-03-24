FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stripe_webhook_app.py .

ENV PORT=8080

CMD ["gunicorn", "--bind=:8080", "stripe_webhook_app:app"]
