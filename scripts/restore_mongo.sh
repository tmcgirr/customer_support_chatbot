#!/usr/bin/env bash
# Restore a Cadre MongoDB archive produced by backup_mongo.sh.
#
#   MONGO_URI="mongodb+srv://..." ./scripts/restore_mongo.sh <archive.gz> [extra mongorestore args]
#
# DESTRUCTIVE to the target database — it prompts for confirmation. To restore into a
# SCRATCH database for a restore-drill (non-destructive), remap the namespace:
#   MONGO_URI=... ./scripts/restore_mongo.sh cadre.archive.gz \
#     --nsFrom='cadre_chatbot.*' --nsTo='cadre_restore_test.*'
#
# To overwrite the live DB in a real recovery, pass --drop.
set -euo pipefail

: "${MONGO_URI:?set MONGO_URI}"
ARCHIVE="${1:?usage: restore_mongo.sh <archive.gz> [mongorestore args]}"
shift || true
[ -f "$ARCHIVE" ] || { echo "archive not found: $ARCHIVE" >&2; exit 1; }

echo "About to restore '$ARCHIVE' into the target MongoDB."
echo "Extra args: $*"
read -r -p "This can overwrite data. Type 'restore' to proceed: " CONFIRM
[ "$CONFIRM" = "restore" ] || { echo "aborted"; exit 1; }

mongorestore --uri="$MONGO_URI" --gzip --archive="$ARCHIVE" "$@"
echo "restore complete"
