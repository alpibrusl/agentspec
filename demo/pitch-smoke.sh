#!/usr/bin/env bash
#
# demo/pitch-smoke.sh
#
# End-to-end "Docker of agents" smoke test. Validates that the six
# pieces shipped through v0.4.x → v0.5.0 actually compose as a system:
#
#   push (multi-tenant)           — PR #13
#   pull (anonymous public read)  — PR #13
#   lock (Ed25519-signed)         — PR #18
#   run  (bwrap-isolated)         — PR #17
#   run  (--require-signed)       — PR #18
#   records (tamper-evident log)  — PR #16
#
# The ``test-echo`` pseudo-runtime stands in for a real LLM CLI so
# the pipeline can be exercised without installing claude-code /
# gemini-cli / etc.
#
# Usage:
#   ./demo/pitch-smoke.sh            # runs end-to-end, prints 8/8 pass
#   AGENTSPEC=<cmd> ./demo/pitch-smoke.sh  # override the CLI entry point
#
# Prereqs: bwrap, python3, curl, the agentspec package importable.

set -Eeuo pipefail

# ── Helpers ──────────────────────────────────────────────────────────
red()   { printf '\033[31m%s\033[0m' "$*"; }
green() { printf '\033[32m%s\033[0m' "$*"; }
dim()   { printf '\033[2m%s\033[0m' "$*"; }

die()     { echo "$(red ERROR): $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || die "missing prereq: $1"; }

# ── Prerequisites ────────────────────────────────────────────────────
require bwrap
require python3
require curl

# CLI entry point: default to ``python -m agentspec`` because the
# installed ``agentspec`` console-script shebang can be stale across
# venv relocations. Callers can override with AGENTSPEC=... .
AGENTSPEC="${AGENTSPEC:-python3 -m agentspec}"

# Sanity-check the CLI loads.
eval "$AGENTSPEC --help" >/dev/null 2>&1 \
  || die "agentspec CLI not reachable via: $AGENTSPEC"

# ── Workspace + cleanup ─────────────────────────────────────────────
TMPDIR=$(mktemp -d -t agentspec-smoke.XXXXXX)
SERVER_PID=""

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

cd "$TMPDIR"
echo "workspace: $(dim "$TMPDIR")"
echo

# ── Step 1 — generate Ed25519 signing keypair ────────────────────────
read -r PRIV PUB < <(python3 -c '
from agentspec.profile.signing import generate_keypair
p, P = generate_keypair()
print(p, P)
')
[ ${#PRIV} -eq 64 ] || die "private key wrong length: ${#PRIV}"
[ ${#PUB}  -eq 64 ] || die "public key wrong length: ${#PUB}"
echo "[1/8] $(green ok) signing keypair generated (pub=${PUB:0:16}…)"

# ── Step 2 — start local registry with multi-tenant auth ─────────────
PORT=$(python3 -c '
import socket
s = socket.socket()
s.bind(("", 0))
print(s.getsockname()[1])
s.close()
')
REGISTRY_URL="http://127.0.0.1:$PORT"

export AGENTSPEC_API_KEYS="alice:alice-secret,bob:bob-secret"
export AGENTSPEC_REGISTRY_DIR="$TMPDIR/registry-data"

python3 -m uvicorn agentspec.registry.server:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning \
  > registry.log 2>&1 &
SERVER_PID=$!

# Wait for server readiness (max ~3s).
for _ in $(seq 1 30); do
  curl -sf "$REGISTRY_URL/healthz" > /dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$REGISTRY_URL/healthz" > /dev/null 2>&1 \
  || die "registry didn't come up on $REGISTRY_URL (see $TMPDIR/registry.log)"
echo "[2/8] $(green ok) registry running at $(dim "$REGISTRY_URL") (tenants: alice, bob)"

# ── Step 3 — author an agent manifest ───────────────────────────────
cat > my.agent <<'EOF'
apiVersion: agent/v1
name: pitch-smoke
version: 0.1.0
description: Pitch-smoke demo agent (uses test-echo pseudo-runtime)

runtime: test-echo
model:
  preferred:
    - test-echo/demo

# Permissive trust so the bwrap sandbox can run on any Linux host
# without host-specific bind binds. Isolation still happens — fresh
# namespaces, cap-drop, die-with-parent — but the filesystem is
# passed through so ``echo`` has access to its own binary.
trust:
  filesystem: full
  network: allowed
  exec: full
EOF
echo "[3/8] $(green ok) agent manifest written ($(dim 'runtime=test-echo, trust=full'))"

# ── Step 4 — push as alice ──────────────────────────────────────────
PUSH_OUT=$(AGENTSPEC_API_KEY=alice-secret AGENTSPEC_REGISTRY="$REGISTRY_URL" \
  eval "$AGENTSPEC" push my.agent --output json)
HASH=$(printf '%s' "$PUSH_OUT" | python3 -c '
import sys, json
d = json.load(sys.stdin)
# ACLI envelope shape: {"ok": true, "data": {...}}
print(d.get("data", d).get("hash", ""))
')
[ -n "$HASH" ] || die "push didn't return a hash: $PUSH_OUT"
echo "[4/8] $(green ok) pushed as alice → $(dim "$HASH")"

# ── Step 5 — pull anonymously from a fresh workspace ────────────────
mkdir -p pull-workdir
cd pull-workdir
AGENTSPEC_REGISTRY="$REGISTRY_URL" eval "$AGENTSPEC" pull "$HASH" > /dev/null
[ -f "pitch-smoke.agent" ] \
  || die "pull didn't produce pitch-smoke.agent (ls: $(ls))"
echo "[5/8] $(green ok) pulled anonymously (no API key) → $(dim "$(pwd)/pitch-smoke.agent")"

# ── Step 6 — lock the pulled agent, Ed25519-signed ──────────────────
export AGENTSPEC_LOCK_SIGNING_KEY="$PRIV"
eval "$AGENTSPEC" lock pitch-smoke.agent \
  --sign-key-env AGENTSPEC_LOCK_SIGNING_KEY > /dev/null
[ -f "pitch-smoke.agent.lock" ] || die "lock didn't produce .lock file"

# Confirm it's actually a signed envelope, not plain JSON.
python3 - "$PUB" <<'PYEOF'
import json, sys
expected_pub = sys.argv[1]
with open("pitch-smoke.agent.lock") as f:
    data = json.load(f)
assert data.get("algorithm") == "ed25519", f"lock not signed: {list(data)}"
assert data.get("public_key") == expected_pub, "lock public_key mismatch"
assert len(data.get("signature", "")) == 128, \
    f"signature wrong length: {len(data.get('signature',''))}"
PYEOF
echo "[6/8] $(green ok) locked + signed ($(dim '128-char Ed25519 signature')) "

# ── Step 7 — run under bwrap with --require-signed ──────────────────
RUN_OUT=$(eval "$AGENTSPEC" run pitch-smoke.agent \
  --lock pitch-smoke.agent.lock \
  --require-signed --pubkey "$PUB" \
  --via bwrap)

# Grep for the runtime's marker anywhere in the output. The
# ordering between "Launching…" and the echo line depends on
# stdout buffering; the existence of the line is what we verify.
ECHO_LINE=$(printf '%s\n' "$RUN_OUT" | grep '^\[test-echo\]' || true)
[ -n "$ECHO_LINE" ] \
  || die "runtime didn't emit its [test-echo] marker; got:\n$RUN_OUT"
echo "[7/8] $(green ok) ran via bwrap with signature-verified lock"
echo "       $(dim 'runtime output: ')$ECHO_LINE"

# ── Step 8 — inspect + verify records + negative test ───────────────
RECORDS_OUT=$(eval "$AGENTSPEC" records list --output json)
COUNT=$(printf '%s' "$RECORDS_OUT" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(d.get("data", d).get("count", 0))
')
[ "$COUNT" = "1" ] || die "expected 1 record, got $COUNT"

RUN_ID=$(printf '%s' "$RECORDS_OUT" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(d.get("data", d).get("records", [{}])[0].get("run_id", ""))
')

# Verify the lock's signature explicitly via the CLI.
eval "$AGENTSPEC" verify-lock pitch-smoke.agent.lock --pubkey "$PUB" > /dev/null

echo "[8/8] $(green ok) record captured + lock verified"
echo "       $(dim "run_id=$RUN_ID, records=$COUNT")"

# Negative: tamper the lock's resolved.model, confirm run refuses.
python3 - <<'PYEOF'
import json
with open("pitch-smoke.agent.lock") as f:
    data = json.load(f)
data["payload"]["resolved"]["model"] = "attacker/rogue-model"
with open("pitch-smoke.agent.lock", "w") as f:
    json.dump(data, f)
PYEOF
if eval "$AGENTSPEC" run pitch-smoke.agent \
    --lock pitch-smoke.agent.lock \
    --require-signed --pubkey "$PUB" \
    --via bwrap > /dev/null 2>&1; then
  die "tampered lock accepted — signature check didn't fire!"
fi
echo "       $(dim 'tamper check: run refused tampered lock ✓')"

echo
echo "$(green 'Pitch-smoke: all 8 steps passed.')"
echo "$(dim 'Pipeline validated: push → pull → lock → run --require-signed --via=bwrap → record')"
