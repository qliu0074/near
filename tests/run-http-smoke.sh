#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
test_python="${NEAR_TEST_PYTHON:-$repo_dir/.venv/bin/python}"
test_data=$(mktemp -d)
(
  cd "$repo_dir/api"
  export AI_PROVIDER=mock EMAIL_MODE=development AUTO_SCHEMA=true
  export DATABASE_URL="sqlite:///$test_data/smoke.db"
  exec "$test_python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
api_pid=$!
(
  cd "$repo_dir/web"
  exec node scripts/start.mjs
) &
web_pid=$!
trap 'kill "$api_pid" "$web_pid" 2>/dev/null || true; rm -rf "$test_data"' EXIT
"$test_python" - <<'PY'
import time
import httpx
for attempt in range(40):
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert client.get('http://127.0.0.1:3000/v1/health').status_code == 200
        break
    except Exception:
        time.sleep(0.25)
else:
    raise RuntimeError('Local services did not become ready')
PY
cd "$repo_dir"
"$test_python" tests/http_smoke.py
