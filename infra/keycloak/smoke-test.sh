#!/usr/bin/env bash
#
# Smoke-test для local-dev Keycloak setup.
# Проверяет:
#   1. Keycloak ready (health endpoint)
#   2. Realm `rehome` discovery URL
#   3. m2m client credentials grant returns valid JWT
#   4. JWT содержит `realm_access.roles` с правильным составом (staff_admin)
#
# Использование: cd infra && docker compose up -d && ./keycloak/smoke-test.sh
#
set -euo pipefail

KC_URL="${KC_URL:-http://localhost:8080}"
REALM="${REALM:-rehome}"
CLIENT_ID="${CLIENT_ID:-rehome-platform-m2m}"
CLIENT_SECRET="${CLIENT_SECRET:-rehome-platform-m2m-local-dev-secret}"
EXPECTED_ROLE="${EXPECTED_ROLE:-staff_admin}"
HEALTH_RETRIES="${HEALTH_RETRIES:-60}"

log() { printf '\033[36m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
pass() { printf '\033[32m✓ %s\033[0m\n' "$*"; }

# Step 1: wait for Keycloak ready
log "Wait for Keycloak ready at ${KC_URL}/health/ready"
for i in $(seq 1 "$HEALTH_RETRIES"); do
  # Keycloak 26 exposes health on management port 9000 by default.
  if curl -fsS "${KC_URL%:8080}:9000/health/ready" >/dev/null 2>&1; then
    pass "Keycloak ready (attempt $i)"
    break
  fi
  # Fallback: check :8080 in case management port disabled
  if curl -fsS "${KC_URL}/realms/master" >/dev/null 2>&1; then
    pass "Keycloak responsive (attempt $i, fallback master realm probe)"
    break
  fi
  if [ "$i" -eq "$HEALTH_RETRIES" ]; then
    fail "Keycloak did not become ready after ${HEALTH_RETRIES} attempts"
  fi
  sleep 2
done

# Step 2: realm discovery
log "Discover realm ${REALM}"
DISCOVERY="${KC_URL}/realms/${REALM}/.well-known/openid-configuration"
if ! curl -fsS "$DISCOVERY" >/dev/null; then
  fail "Realm discovery failed: ${DISCOVERY}"
fi
pass "Realm discovery OK"

# Step 3: m2m client credentials grant
log "Get m2m access_token (client_credentials grant)"
TOKEN_URL="${KC_URL}/realms/${REALM}/protocol/openid-connect/token"
TOKEN_RESPONSE=$(curl -fsS -X POST \
  -d "grant_type=client_credentials" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  "$TOKEN_URL")
ACCESS_TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
if [ -z "$ACCESS_TOKEN" ]; then
  fail "Empty access_token in response: $TOKEN_RESPONSE"
fi
pass "Token received (length: ${#ACCESS_TOKEN})"

# Step 4: decode JWT payload and verify roles
log "Decode JWT payload and verify ${EXPECTED_ROLE} in realm_access.roles"
PAYLOAD=$(printf '%s' "$ACCESS_TOKEN" | python3 -c '
import sys, json, base64
parts = sys.stdin.read().strip().split(".")
if len(parts) < 2:
    sys.exit("malformed JWT")
payload = parts[1] + "=" * (-len(parts[1]) % 4)
data = json.loads(base64.urlsafe_b64decode(payload))
print(json.dumps(data))
')
ROLES=$(printf '%s' "$PAYLOAD" | python3 -c 'import sys, json; print(",".join(json.load(sys.stdin).get("realm_access", {}).get("roles", [])))')
echo "    roles in token: ${ROLES}"
if ! printf '%s' "$ROLES" | tr ',' '\n' | grep -q "^${EXPECTED_ROLE}$"; then
  fail "Expected role '${EXPECTED_ROLE}' not found in realm_access.roles. Got: ${ROLES}"
fi
pass "JWT contains expected role: ${EXPECTED_ROLE}"

printf '\n\033[32m==> Smoke-test PASS\033[0m\n'
