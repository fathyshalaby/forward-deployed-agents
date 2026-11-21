FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/fda \
    FDA_STATE=/var/lib/fda/state.db \
    FDA_AGENTS=/var/lib/fda/agents \
    FDA_AUDIT=/var/lib/fda/audit.jsonl \
    FDA_APPROVAL_MODE=external

WORKDIR /app
COPY pyproject.toml setup.py setup.cfg README.md ./
COPY src/ ./src/
RUN python3 -m pip install --no-cache-dir .

# Unprivileged runtime user with writable state volumes.
RUN useradd --create-home --uid 10001 fda \
    && mkdir -p /var/lib/fda/agents \
    && chown -R fda:fda /var/lib/fda /home/fda
USER fda

VOLUME ["/var/lib/fda"]
EXPOSE 8787

ENTRYPOINT ["fda"]
CMD ["serve", "--no-examples"]
