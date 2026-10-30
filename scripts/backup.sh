#!/usr/bin/env bash
# Consistent backup: PostgreSQL dump first, then the data volume (documents/chunks/reports). Qdrant is derived data (re-index) unless you snapshot it separately.
#   MKA_DATABASE_URL=postgresql://... MKA_DATA_DIR=/data scripts/backup.sh /backups
set -euo pipefail
out="${1:?usage: backup.sh <target-dir>}"; ts=$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$out/$ts"
pg_dump -Fc -f "$out/$ts/mka.dump" "${MKA_DATABASE_URL/postgresql+psycopg2/postgresql}"
tar -C "${MKA_DATA_DIR:?}" -czf "$out/$ts/data.tgz" .
sha256sum "$out/$ts/"* > "$out/$ts/SHA256SUMS"
echo "backup written to $out/$ts"
