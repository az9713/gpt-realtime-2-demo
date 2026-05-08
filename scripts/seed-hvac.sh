#!/usr/bin/env bash
# Idempotent HVAC seed: copies fixtures into /data/hvac and ensures the
# directory layout the post_call hook expects exists. Fixtures are
# checked-in JSON; this script just lays them out for the running stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/verticals/hvac/fixtures"
DEST="${ROOT}/data/hvac"

mkdir -p "${DEST}"
mkdir -p "${ROOT}/data/post-call"

for f in parts trucks customers warranties jobs; do
  cp "${SRC}/${f}.json" "${DEST}/${f}.json"
done

echo "seed-hvac: copied fixtures to ${DEST}"
