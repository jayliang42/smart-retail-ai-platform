#!/bin/sh
set -eu

alembic upgrade head
smart-retail-ingest-knowledge data/knowledge/manifest.json
