FROM kasramp/calibre-docker:3.13.7-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG WORT_VERSION=v0.1.0
COPY util/download_wort_data.py ./util/
RUN python util/download_wort_data.py ${WORT_VERSION} /app/kindler/data/wort
COPY kindler ./kindler
COPY util/download_ip_lists.py ./util/
RUN python util/download_ip_lists.py /app/kindler/data
COPY scripts/index_with_summary.csv ./scripts/

EXPOSE 8181

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8181", "kindler.wsgi:app"]
