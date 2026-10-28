FROM python:3.12.4-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 10001 intake \
    && useradd --system --uid 10001 --gid intake --home-dir /app intake

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY CHANGELOG.md ./CHANGELOG.md
COPY .claude/commands/fix-issue.md ./.claude/commands/fix-issue.md
COPY docs/stable/agent-context-template.md ./docs/stable/agent-context-template.md

RUN chown -R intake:intake /app
USER intake

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
