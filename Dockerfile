FROM kasramp/calibre-docker:3.13.7-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kindler ./kindler
RUN python -c "import os, urllib.request; base = 'https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/datacenter/'; os.makedirs('/app/kindler/data', exist_ok=True); [(urllib.request.urlretrieve(base + v + '.txt', '/app/kindler/data/datacenter_' + v + '.txt'), (os.path.getsize('/app/kindler/data/datacenter_' + v + '.txt') > 50000 or exit('datacenter_' + v + '.txt is too small'))) for v in ('ipv4', 'ipv6')]"
COPY scripts/index_with_summary.csv ./scripts/

EXPOSE 8181

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8181", "kindler.wsgi:app"]
