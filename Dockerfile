FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY newsletter_agent/ newsletter_agent/
COPY config/ config/

# Cloud Run injects PORT; default to 8080
ENV PORT=8080

EXPOSE ${PORT}

# Run gunicorn with the Flask app
CMD exec gunicorn \
    --bind 0.0.0.0:${PORT} \
    --workers 1 \
    --threads 1 \
    --timeout 1200 \
    --access-logfile - \
    --error-logfile - \
    newsletter_agent.http_handler:app
