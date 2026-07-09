#!/usr/bin/env bash
# Back up the Cadre MongoDB to a timestamped, compressed archive.
#
#   MONGO_URI="mongodb+srv://..." ./scripts/backup_mongo.sh [output_dir]
#
# Requires the MongoDB Database Tools (mongodump). If the host lacks them, run via the
# mongo image, e.g.:
#   docker run --rm -e MONGO_URI -v "$PWD/backups":/backups mongo:7 \
#     bash -c 'mongodump --uri="$MONGO_URI" --gzip --archive=/backups/cadre.archive.gz'
#
# In production, schedule this (cron/systemd timer) AND verify a restore regularly —
# an untested backup is not a backup (docs/RUNBOOK_PROD.md). Managed Atlas provides
# continuous backups; this script is the self-hosted / portable path and the restore-
# test tool for either.
set -euo pipefail

: "${MONGO_URI:?set MONGO_URI (never hard-code credentials in the repo)}"
OUT_DIR="${1:-backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$OUT_DIR/cadre-${STAMP}.archive.gz"

mongodump --uri="$MONGO_URI" --gzip --archive="$ARCHIVE"
echo "backup written: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
