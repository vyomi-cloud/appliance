FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLOUDLEARN_STATE_FILE=/data/cloudlearn_state.pkl

WORKDIR /app

# Node.js so Cloud Functions with a nodejs runtime can execute for real.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 9000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
