#!/bin/sh
# Generate the secret files the production stack mounts. Run once; existing files are kept.
# The LLM API key is NOT generated: put it in deploy/secrets/copilot_gemini_api_key yourself
# (an empty file runs the assistant in retrieval-only mode).
set -eu
dir="$(dirname "$0")/secrets"
mkdir -p "$dir"
chmod 700 "$dir"

rand() { openssl rand -hex "$1"; }

make() { # name value
  if [ -e "$dir/$1" ]; then echo "keep   $1"; else printf '%s' "$2" > "$dir/$1"; chmod 600 "$dir/$1"; echo "create $1"; fi
}

if [ ! -e "$dir/copilot_db_password" ]; then pw="$(rand 24)"; else pw="$(cat "$dir/copilot_db_password")"; fi
make copilot_db_password "$pw"
make copilot_database_url "postgresql+psycopg://copilot:${pw}@db:5432/copilot"
make copilot_jwt_secret "$(rand 32)"
make copilot_metrics_token "$(rand 24)"
make copilot_gemini_api_key ""
echo "done. Keep deploy/secrets/ out of version control (it is git-ignored) and back it up separately."
