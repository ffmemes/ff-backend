#!/bin/sh
# Opens a local tunnel to the production Postgres for read-only analysis.
# The database has no public port; it is reachable only from the Docker host.
# Set FF_DB_SSH (user@host of the Docker host) in .env; never commit it.
# Then point ANALYST_DATABASE_URL at 127.0.0.1:${FF_DB_LOCAL_PORT:-15432}.
set -eu
[ -f .env ] && FF_DB_SSH=${FF_DB_SSH:-$(sed -n 's/^FF_DB_SSH=//p' .env)}
: "${FF_DB_SSH:?set FF_DB_SSH=user@host in .env}"
container=${FF_DB_CONTAINER:-fsn1-ff-pg19}
port=${FF_DB_LOCAL_PORT:-15432}
# The container IP changes on restart, so look it up each time.
ip=$(ssh -o BatchMode=yes "$FF_DB_SSH" \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' $container" | cut -d' ' -f1)
echo "tunnel 127.0.0.1:$port -> $container ($ip:5432); Ctrl-C to close"
exec ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L "$port:$ip:5432" "$FF_DB_SSH"
