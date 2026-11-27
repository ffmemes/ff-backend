#!/usr/bin/env bash

set -e

# The Prefect runner uses the same image; PROCESS=flows starts it instead of the API.
if [ "${PROCESS:-}" = "flows" ]; then
    exec python scripts/serve_flows.py
fi

DEFAULT_MODULE_NAME=src.main

MODULE_NAME=${MODULE_NAME:-$DEFAULT_MODULE_NAME}
VARIABLE_NAME=${VARIABLE_NAME:-app}
export APP_MODULE=${APP_MODULE:-"$MODULE_NAME:$VARIABLE_NAME"}

DEFAULT_GUNICORN_CONF=/src/gunicorn/gunicorn_conf.py
export GUNICORN_CONF=${GUNICORN_CONF:-$DEFAULT_GUNICORN_CONF}
export WORKER_CLASS=${WORKER_CLASS:-"uvicorn.workers.UvicornWorker"}

# Start Gunicorn
exec gunicorn --forwarded-allow-ips "*" -k "$WORKER_CLASS" -c "$GUNICORN_CONF" "$APP_MODULE"
