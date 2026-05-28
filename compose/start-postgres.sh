#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export POSTGRES_DATA_ROOT="${PROJECT_ROOT}/assets/db"

export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export POSTGRES_DB="${POSTGRES_DB:-techdoc_rag}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"

mkdir -p "${POSTGRES_DATA_ROOT}"

echo "Starting PostgreSQL..."
echo "PROJECT_ROOT=${PROJECT_ROOT}"
echo "POSTGRES_DATA_DIR=${POSTGRES_DATA_ROOT}"
echo "POSTGRES_DB=${POSTGRES_DB}"
echo "POSTGRES_PORT=${POSTGRES_PORT}"

docker compose \
  -f "${PROJECT_ROOT}/compose/postgresql.yaml" \
  up -d postgres

docker compose \
  -f "${PROJECT_ROOT}/compose/postgresql.yaml" \
  ps