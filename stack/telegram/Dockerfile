FROM python:3.12-slim
COPY stack/telegram/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY core /app/core
COPY modules /app/modules
COPY stack/telegram/intents.py /app/
CMD ["python", "-u", "-m", "core"]
