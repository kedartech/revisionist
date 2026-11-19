#!/usr/bin/env bash
# Nightly backup: pg_dump -Fc into a local directory, prune by age, then copy
# the new dump off the box. Fails loudly on anything missing.
#
#   REVISIONIST_ADMIN_DSN          postgresql:// URL of the revisionist database, as the admin role
#   REVISIONIST_BACKUP_DEST        off-box target: an rsync destination (user@host:/path)
#                           or rclone:<remote>:<path>
#   REVISIONIST_BACKUP_DIR         local dumps (default ~/.local/share/revisionist/backups)
#   REVISIONIST_BACKUP_KEEP_DAYS   local retention in days (default 14)
#   REVISIONIST_BIN                the revisionist command (default: revisionist on PATH)
#   REVISIONIST_MAP_OBJECTS        the map-objects directory the served room reads
#                                  (default: worlds/maps/objects/ of the checkout)
# Every map object is copied, hash-checked, into map-objects/ beside the dumps and off
# the box with them (no database read, so a sealed database needs no key here). Map objects are immutable and never pruned.
set -euo pipefail

: "${REVISIONIST_ADMIN_DSN:?REVISIONIST_ADMIN_DSN is not set}"
: "${REVISIONIST_BACKUP_DEST:?REVISIONIST_BACKUP_DEST is not set: name an rsync or rclone target}"
dir="${REVISIONIST_BACKUP_DIR:-$HOME/.local/share/revisionist/backups}"
keep="${REVISIONIST_BACKUP_KEEP_DAYS:-14}"
revisionist="${REVISIONIST_BIN:-revisionist}"

mkdir -p "$dir"
chmod 700 "$dir"
out="$dir/revisionist-$(date -u +%Y%m%dT%H%M%SZ).dump"

pg_dump --format=custom --file="$out.partial" --dbname="$REVISIONIST_ADMIN_DSN"
pg_restore --list "$out.partial" >/dev/null # the archive reads back
mv "$out.partial" "$out"
echo "dumped $out ($(stat -c %s "$out") bytes)"

mkdir -p "$dir/map-objects"
"$revisionist" db map-objects copy --all --to "$dir/map-objects"

find "$dir" -maxdepth 1 -name 'revisionist-*.dump' -mtime +"$keep" -print -delete

case "$REVISIONIST_BACKUP_DEST" in
rclone:*)
	rclone copy "$out" "${REVISIONIST_BACKUP_DEST#rclone:}"
	rclone copy "$dir/map-objects" "${REVISIONIST_BACKUP_DEST#rclone:}/map-objects"
	;;
*)
	rsync --archive "$out" "$REVISIONIST_BACKUP_DEST/"
	rsync --archive "$dir/map-objects" "$REVISIONIST_BACKUP_DEST/"
	;;
esac
echo "copied to $REVISIONIST_BACKUP_DEST"
