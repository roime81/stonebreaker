FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd -m app && mkdir /data && chown app /data
COPY app ./app
USER app
ENV STONEBREAKER_DUCKDB_PATH=/data/analytics.duckdb
EXPOSE 8000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
