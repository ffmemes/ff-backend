#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ -e .env || -L .env ]]; then
    printf '%s\n' 'Run this QA harness in a checkout without a .env file.' >&2
    exit 1
fi
qa_python=$(command -v "${QA_PYTHON:-python3}")
qa_bin=$(dirname "$qa_python")
if [[ -n "${DOCKER_CONTEXT:-}" || -z "${DOCKER_HOST:-}" ]]; then
    qa_docker_host=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
else
    qa_docker_host=$DOCKER_HOST
fi
if [[ "$qa_docker_host" != unix://* ]]; then
    printf '%s\n' 'The QA runner requires a local Docker Unix socket.' >&2
    exit 1
fi
qa_run=$(mktemp -d)
qa_pg=""
qa_redis=""

stop_services() {
    if [[ -n "$qa_redis" ]]; then docker stop "$qa_redis" >/dev/null; fi
    if [[ -n "$qa_pg" ]]; then docker stop "$qa_pg" >/dev/null; fi
    rm -r "$qa_run"
}
trap stop_services EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

qa_database="first_five_$(basename "$qa_run" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]')"
qa_pg=$(docker run --pull=never --detach --rm \
    --tmpfs /var/lib/postgresql/data --publish 127.0.0.1::5432 \
    --env "POSTGRES_DB=$qa_database" --env POSTGRES_USER=qa --env POSTGRES_PASSWORD=example \
    postgres:14)
qa_redis=$(docker run --pull=never --detach --rm \
    --tmpfs /data --publish 127.0.0.1::6379 redis:6.2 \
    redis-server --save "" --appendonly no)
qa_pg_port=$(docker port "$qa_pg" 5432/tcp)
qa_redis_port=$(docker port "$qa_redis" 6379/tcp)
[[ "$qa_pg_port" == 127.0.0.1:* && "$qa_redis_port" == 127.0.0.1:* ]]
qa_pg_port=${qa_pg_port##*:}
qa_redis_port=${qa_redis_port##*:}

for ((attempt=0; attempt<30; attempt++)); do
    if docker exec "$qa_pg" pg_isready -h 127.0.0.1 -U qa -d "$qa_database" &&
        docker exec "$qa_redis" redis-cli ping; then
        break
    fi
    sleep 1
done
[[ "$(docker exec "$qa_redis" redis-cli dbsize)" == 0 ]]
printf 'Redis 127.0.0.1:%s/0 is empty\n' "$qa_redis_port"

qa_env() {
    env -i "PATH=$qa_bin:/usr/bin:/bin" "TZ=UTC" \
        "FIRST_FIVE_QA_DATABASE=$qa_database" \
        "FIRST_FIVE_QA_PG_PORT=$qa_pg_port" "FIRST_FIVE_QA_REDIS_PORT=$qa_redis_port" \
        "DATABASE_URL=postgresql+asyncpg://qa:example@127.0.0.1:$qa_pg_port/$qa_database" \
        "REDIS_URL=redis://127.0.0.1:$qa_redis_port/0" \
        "ENVIRONMENT=TESTING" "CORS_ORIGINS=[]" "CORS_HEADERS=[]" \
        "TELEGRAM_BOT_TOKEN=12345:offline-test" "TELEGRAM_BOT_USERNAME=first_five_qa_bot" \
        "TELEGRAM_BOT_WEBHOOK_SECRET=offline" "ADMIN_LOGS_CHAT_ID=-1009999999901" \
        "MEME_STORAGE_TELEGRAM_CHAT_ID=-1009999999902" \
        "UPLOADED_MEMES_REVIEW_CHAT_ID=-1009999999903" \
        "PREFECT_HOME=$qa_run/prefect" "PREFECT_SERVER_ANALYTICS_ENABLED=false" \
        "$@"
}

check_empty_schema() {
    qa_env "$qa_python" - "$1" <<'PY'
import os
import sys

import sqlalchemy
from alembic import command
from alembic.config import Config

engine_from_config = sqlalchemy.engine_from_config
checked = []

def check_engine(*args, **kwargs):
    engine = engine_from_config(*args, **kwargs)
    expected = os.environ["FIRST_FIVE_QA_DATABASE"]
    port = int(os.environ["FIRST_FIVE_QA_PG_PORT"])
    assert (engine.url.host, engine.url.port, engine.url.database) == ("127.0.0.1", port, expected)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT current_database()").scalar_one() == expected
        for table in ('"user"', "user_meme_reaction", "v_new_user"):
            assert conn.exec_driver_sql("SELECT to_regclass(%s)", (table,)).scalar_one() is None
        if conn.exec_driver_sql("SELECT to_regclass('alembic_version')").scalar_one() is not None:
            assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").all() == []
    print(f"{sys.argv[1]}: Alembic engine 127.0.0.1:{port}/{expected}; application schema empty")
    checked.append(True)
    return engine

sqlalchemy.engine_from_config = check_engine
command.current(Config("alembic.ini"))
assert checked == [True]
PY
}

check_empty_schema "Before pytest"
if [[ $# -eq 0 ]]; then
    set -- tests/tgbot/test_first_five_reactions.py
fi
qa_status=0
qa_env "$qa_python" -m pytest -q -s -rxf "$@" || qa_status=$?
check_empty_schema "After pytest"
exit "$qa_status"
