#!/bin/sh
set -eu

required_directories='apps/api
apps/agent
apps/web
packages/shared
infrastructure/docker/postgres/init
docs'

required_files='.editorconfig
.env.example
.gitignore
.pre-commit-config.yaml
.tool-versions
Makefile
compose.yaml
README.md
apps/api/README.md
apps/agent/README.md
apps/web/README.md
packages/shared/README.md
docs/architecture.md
docs/event-model.md
docs/detection-engine.md
docs/agent.md
docs/api.md
docs/threat-model.md
docs/validation.md
docs/development.md
docs/aegisx-cli-manual.md
docs/progress.md'

for directory in $required_directories; do
  test -d "$directory"
done

for file in $required_files; do
  test -f "$file"
done

for variable in \
  AEGISX_ENV \
  LOG_LEVEL \
  POSTGRES_DB \
  POSTGRES_USER \
  POSTGRES_PASSWORD \
  POSTGRES_HOST_PORT \
  DATABASE_URL; do
  grep -q "^${variable}=" .env.example
done

test -x scripts/check-foundation.sh
grep -q '^    image: docker.io/library/postgres:17-alpine$' compose.yaml
grep -q '^## Current implementation$' README.md
grep -q '^## Milestone 0 — Repository Foundation$' docs/progress.md
grep -q '^Status: complete' docs/progress.md
for command in \
  'aegisx run' \
  'aegisx doctor' \
  'aegisx data-status' \
  'aegisx prune --dry-run' \
  'aegisx prune --apply --yes'; do
  grep -q "$command" docs/aegisx-cli-manual.md
done

printf '%s\n' 'AegisX foundation checks passed.'
