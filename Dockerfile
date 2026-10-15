FROM python:3.12-slim
WORKDIR /app
COPY bot.py .
ENV PYTHONUNBUFFERED=1 BOT_DATA_DIR=/data
CMD ["python", "bot.py"]
