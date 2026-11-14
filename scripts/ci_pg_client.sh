#!/usr/bin/env bash
# pg_dump, pg_restore and psql for the backup and restore-drill tests, at the
# service's major version: a newer pg_dump writes settings 16 cannot restore.
# The runner image may already carry them; otherwise they come from
# apt.postgresql.org. The key download and the apt calls are retried because that
# download is the step's known network flake.
set -euo pipefail

BIN=/usr/lib/postgresql/16/bin

if [ -x "$BIN/pg_dump" ] && [ -x "$BIN/pg_restore" ] && [ -x "$BIN/psql" ] && command -v rsync >/dev/null; then
  echo "postgresql-client-16 and rsync are already on the runner"
else
  sudo install -d /usr/share/postgresql-common/pgdg
  sudo curl -fsS --retry 5 --retry-all-errors --retry-delay 3 \
    -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    | sudo tee /etc/apt/sources.list.d/pgdg.list
  apt_update() { sudo apt-get -o Acquire::Retries=3 update; }
  apt_install() { sudo apt-get -o Acquire::Retries=3 install -y postgresql-client-16 rsync; }
  apt_update || { sleep 10; apt_update; }
  apt_install || { sleep 10; apt_update && apt_install; }
fi

echo "$BIN" >> "$GITHUB_PATH"
"$BIN/pg_dump" --version
