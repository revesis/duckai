# duck.ai OpenAI-compatible bridge
#
#   docker build -t duckai-bridge .
#   docker run -d --name duckai-bridge -p 127.0.0.1:8765:8765 --restart unless-stopped duckai-bridge
#
# Set DUCKAI_API_KEY to require `Authorization: Bearer <key>` (do this whenever
# the port is reachable from anywhere but localhost):
#   docker run -d -p 8765:8765 -e DUCKAI_API_KEY=change-me duckai-bridge
#
# The challenge solver is JavaScript (jsdom), so the runtime needs both Node and
# Python; the bridge itself is stdlib + requests. jsdom 30 requires Node >= 22.22.
#
# podman: build with `podman build --format docker .` — the default OCI format
# silently drops the HEALTHCHECK instruction.

# ── jsdom ────────────────────────────────────────────────────────────────────
FROM node:24-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# ── runtime ──────────────────────────────────────────────────────────────────
FROM node:24-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DUCKAI_HOST=0.0.0.0 \
    DUCKAI_PORT=8765 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv passwd \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY --from=deps /app/node_modules ./node_modules
COPY duckai_client.py duckai_server.py jsa_jsdom.js ./

# ``solve()`` writes the per-request challenge next to the solver, so /app must
# stay writable for the unprivileged user.
RUN useradd --create-home --uid 10001 duckai \
 && chown -R duckai:duckai /app
USER duckai

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["python3", "duckai_server.py"]
CMD ["--host", "0.0.0.0", "--port", "8765"]
