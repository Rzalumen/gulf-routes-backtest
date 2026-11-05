FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/app.py .
# one process (one database copy in memory/disk), threads for concurrency; the database is read-only, so threads are safe
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 60 app:app
