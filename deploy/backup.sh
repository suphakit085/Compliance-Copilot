#!/bin/sh
# Back up the whole database (documents, vectors, users, chat history and the audit log).
#
#   DB_CONTAINER=<postgres container> deploy/backup.sh [output-dir]
#
# Writes copilot-<UTC timestamp>.dump (pg_dump custom format) plus a .sha256 file, and deletes
# dumps older than RETENTION_DAYS (default 30). A backup is only proven by restoring it:
# run deploy/restore-test.sh on the result. Encrypt the dump before it leaves the host
# (e.g. gpg --encrypt or age) - it contains masked questions, answers and user records.
set -eu
DB_CONTAINER="${DB_CONTAINER:-compliance-copilot-db}"
DB_USER="${DB_USER:-copilot}"
DB_NAME="${DB_NAME:-copilot}"
OUT="${1:-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mkdir -p "$OUT"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$OUT/copilot-$stamp.dump"

docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom --compress=6 > "$file.partial"
mv "$file.partial" "$file"  # never leave a truncated dump under the final name
(cd "$OUT" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256")

find "$OUT" -name 'copilot-*.dump*' -type f -mtime +"$RETENTION_DAYS" -delete
echo "backup: $file ($(du -h "$file" | cut -f1))"
