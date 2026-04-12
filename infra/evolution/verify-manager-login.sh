#!/usr/bin/env bash
# Comprueba el mismo flujo que el Manager (verifyServer + verifyCreds).
# Uso: cd infra/evolution && ./verify-manager-login.sh
# Opcional: BASE=http://127.0.0.1:8080 ./verify-manager-login.sh
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:3001}"
KEY="${AUTHENTICATION_API_KEY:-}"
if [[ -z "$KEY" && -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a || true
  KEY="${AUTHENTICATION_API_KEY:-}"
fi
if [[ -z "$KEY" ]]; then
  echo "Def AUTHENTICATION_API_KEY o ten .env en infra/evolution/" >&2
  exit 1
fi

fail() { echo "FAIL: $*" >&2; exit 1; }

check_json_version() {
  local url="$1"
  local label="$2"
  local extra="${3:-}"
  local body code
  code=$(curl -sS -o /tmp/evo-v.json -w "%{http_code}" $extra \
    -H "Accept: application/json, text/plain, */*" \
    "$url") || fail "curl $label"
  [[ "$code" == "200" ]] || fail "$label HTTP $code body=$(head -c 200 /tmp/evo-v.json)"
  python3 - "$label" <<'PY' || fail "$label JSON sin version"
import json, sys
label = sys.argv[1]
with open("/tmp/evo-v.json") as f:
    d = json.load(f)
v = d.get("version")
if not v:
    print(f"{label}: falta version: {d}", file=sys.stderr)
    sys.exit(1)
print(f"OK {label}: version={v}")
PY
}

echo "=== verifyServer (GET base/) ==="
check_json_version "${BASE}/" "GET ${BASE}/"
check_json_version "${BASE}//" "GET ${BASE}// (redirect 302→/)" "-L"

echo "=== verifyCreds (POST /verify-creds) ==="
code=$(curl -sS -o /tmp/evo-c.json -w "%{http_code}" \
  -X POST "${BASE}/verify-creds" \
  -H "apikey: ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{}') || fail "curl verify-creds"
[[ "$code" == "200" ]] || fail "verify-creds HTTP $code $(cat /tmp/evo-c.json)"

echo "Todo OK (Manager no debería mostrar Invalid server con esta BASE)."
