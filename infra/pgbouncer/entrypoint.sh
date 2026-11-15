#!/bin/sh
# Transaction pooling: a server connection is held only for the length of a transaction, so a few dozen
# Postgres connections serve thousands of clients. Session state does not survive between transactions,
# which is why the application sets the tenant with SET LOCAL and disables prepared statements.
set -e
cat > /tmp/userlist.txt <<USERS
"voiceops_owner" "${VOICEOPS_OWNER_PASSWORD:-voiceops_owner}"
"voiceops_app" "${VOICEOPS_APP_PASSWORD:-voiceops_app}"
USERS
cat > /tmp/pgbouncer.ini <<INI
[databases]
* = host=${DB_HOST:-db} port=5432
[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = plain
auth_file = /tmp/userlist.txt
pool_mode = transaction
max_client_conn = ${MAX_CLIENT_CONN:-5000}
default_pool_size = ${DEFAULT_POOL_SIZE:-40}
reserve_pool_size = 10
server_reset_query = DISCARD ALL
ignore_startup_parameters = extra_float_digits,options
INI
exec pgbouncer /tmp/pgbouncer.ini
