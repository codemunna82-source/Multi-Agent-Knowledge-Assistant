#!/usr/bin/env bash
# Restore into an EMPTY database and an EMPTY data directory, then migrate.   scripts/restore.sh /backups/20261030T020000Z
set -euo pipefail
src="${1:?usage: restore.sh <backup-dir>}"
(cd "$src" && sha256sum -c SHA256SUMS)
pg_restore --clean --if-exists -d "${MKA_DATABASE_URL/postgresql+psycopg2/postgresql}" "$src/mka.dump"
tar -C "${MKA_DATA_DIR:?}" -xzf "$src/data.tgz"
python -m app.cli migrate
echo "restored. Re-index sources if the vector store was not restored: POST /sources/{id}/reindex"
