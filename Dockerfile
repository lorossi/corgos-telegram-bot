FROM python:3.13-slim

WORKDIR /app
COPY . /app
RUN pip install . --root-user-action=ignore

CMD ["python", "corgos_telegram_bot/main.py"]