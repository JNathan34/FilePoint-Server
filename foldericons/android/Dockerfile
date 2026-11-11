FROM python:3.12-slim-bookworm AS build
RUN printf 'deb-src [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian bookworm main\n' > /etc/apt/sources.list.d/source.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libmtp-dev libfuse-dev libmagic-dev autoconf automake
WORKDIR /build
RUN apt-get source jmtpfs
COPY patch_mtp_dates.py /build/patch_mtp_dates.py
RUN python3 patch_mtp_dates.py && cd jmtpfs-* && ./configure && make -j2

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends jmtpfs fuse \
    && rm -rf /var/lib/apt/lists/* \
    && printf 'user_allow_other\n' >> /etc/fuse.conf
COPY --from=build /build/jmtpfs-*/src/jmtpfs /usr/local/bin/jmtpfs
COPY phone_bridge.py /app/phone_bridge.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python3", "-B", "/app/phone_bridge.py"]
