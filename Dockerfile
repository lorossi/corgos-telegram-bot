FROM python:3.13-slim

ARG INSTALL_EXTRAS=""

WORKDIR /app
COPY . /app
RUN if [ -n "$INSTALL_EXTRAS" ]; then \
  pip install --no-cache-dir --root-user-action=ignore ".[$INSTALL_EXTRAS]"; \
  else \
  pip install --no-cache-dir --root-user-action=ignore .; \
  fi

CMD ["python", "corgos_telegram_bot/main.py"]