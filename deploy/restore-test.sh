#!/bin/sh
# Prove a backup can be restored: load it into a scratch database next to the live one, compare
# row counts and re-verify the audit hash chain on the restored copy, then drop the scratch DB.
#
#   DB_CONTAINER=<postgres container> deploy/restore-test.sh backups/copilot-<stamp>.dump
#
# The audit chain is verified with the application's own code. Set VERIFY_URL to a database URL
# for the scratch DB as seen from where `copilot` runs (default: the dev port on localhost), or
# API_CONTAINER to run the check inside the API container instead.
set -eu
DUMP="$1"
DB_CONTAINER="${DB_CONTAINER:-compliance-copilot-db}"
DB_USER="${DB_USER:-copilot}"
DB_NAME="${DB_NAME:-copilot}"
SCRATCH="restore_test_$(date -u +%Y%m%d%H%M%S)"

(cd "$(dirname "$DUMP")" && sha256sum -c "$(basename "$DUMP").sha256") || { echo "checksum mismatch"; exit 1; }

psql() { docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -v ON_ERROR_STOP=1 -qAt "$@"; }
cleanup() { psql -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

psql -d postgres -c "CREATE DATABASE $SCRATCH"
# roles are cluster-wide; the reader role used by row-level security already exists in this cluster
docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$SCRATCH" --no-owner --exit-on-error < "$DUMP"

status=0
for t in documents chunks users audit_log conversations conversation_messages; do
  live="$(psql -d "$DB_NAME" -c "SELECT count(*) FROM $t")"
  restored="$(psql -d "$SCRATCH" -c "SELECT count(*) FROM $t")"
  # the live DB may have grown since the dump; fewer rows in the copy is expected, more is not
  if [ "$restored" -gt "$live" ] || { [ "$restored" -eq 0 ] && [ "$live" -gt 0 ]; }; then flag="MISMATCH"; status=1; else flag="ok"; fi
  printf '%-22s live=%-8s restored=%-8s %s\n' "$t" "$live" "$restored" "$flag"
done
rls="$(psql -d "$SCRATCH" -c "SELECT count(*) FROM pg_policies WHERE tablename IN ('documents','chunks')")"
echo "row-level security policies restored: $rls"; [ "$rls" -ge 2 ] || status=1

if [ -n "${API_CONTAINER:-}" ]; then
  url="postgresql+psycopg://$DB_USER@db:5432/$SCRATCH"
  docker exec -e COPILOT_DATABASE_URL="${VERIFY_URL:-$url}" "$API_CONTAINER" copilot audit-verify | tee /tmp/verify.$$
else
  COPILOT_DATABASE_URL="${VERIFY_URL:-postgresql+psycopg://copilot:copilot@localhost:5433/$SCRATCH}" \
    uv run copilot audit-verify | tee /tmp/verify.$$
fi
grep -q "'valid': True" /tmp/verify.$$ || status=1
rm -f /tmp/verify.$$

[ "$status" -eq 0 ] && echo "RESTORE TEST PASSED" || echo "RESTORE TEST FAILED"
exit "$status"
