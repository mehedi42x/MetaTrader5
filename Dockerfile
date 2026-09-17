# MT5 Web Console - plain Linux image (control plane only).
#
# To ALSO host MetaTrader 5 in the same container you need Wine + Xvfb. That is
# deliberately opt-in: uncomment the MT5 stage at the bottom and build with
#   docker build --build-arg WITH_MT5=1 -t mt5-console .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MT5WEB_DATA=/var/lib/mt5web-data

WORKDIR /srv/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /var/lib/mt5web-data

# --- optional: Wine + MetaTrader 5 (see agents/setup-mt5-wine.sh) ----------
ARG WITH_MT5=0
RUN if [ "$WITH_MT5" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends wget curl gnupg ca-certificates \
        xauth xvfb cabextract unzip dpkg && rm -rf /var/lib/apt/lists/* ; \
      dpkg --add-architecture i386 ; \
      echo "Wine + MetaTrader 5 must be installed at RUNTIME (the installer is a Windows exe and needs a display):" ; \
      echo "  docker exec -it <name> bash -lc 'bash agents/setup-mt5-wine.sh'" ; \
    fi

EXPOSE 8000
VOLUME ["/var/lib/mt5web-data"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
