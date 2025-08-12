FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# default if not provided (Railway sets PORT automatically)
ENV PORT=8080
EXPOSE 8080

# add the start script
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
