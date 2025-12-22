FROM python:3.13-slim

ARG INSTALL_EXTRAS=""

WORKDIR /app
COPY . /app
RUN pip install .[${INSTALL_EXTRAS}] --root-user-action=ignore

CMD ["python", "corgos_telegram_bot/main.py"]