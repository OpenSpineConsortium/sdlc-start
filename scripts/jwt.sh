#!/usr/bin/env bash
# Print a GitHub App's JWT, signed RS256 with the App's private key. The
# form's workflows read an App's installations (GET /app/installations
# and /app/installations/ID, scripts/resolve.py), mint an installation's
# token and ask which repositories the Setup App's installation reaches,
# and GitHub answers those calls to the App's own JWT and nothing else; Python's
# standard library has no RSA, so openssl signs it, and only coreutils
# and openssl are used. The key is read from the environment, as a secret
# gives it, and reaches openssl through process substitution, so it never
# touches a file or the log; the JWT alone goes to stdout, since the caller
# captures it. The token is dated 60 seconds in the past, which GitHub
# advises against clock drift, and lasts nine minutes, under GitHub's
# ceiling of ten.
#
# Usage: APP_ID=... APP_PRIVATE_KEY=... bash scripts/jwt.sh
set -euo pipefail

if [ -z "${APP_ID:-}" ] || [ -z "${APP_PRIVATE_KEY:-}" ]; then
  echo "jwt.sh: APP_ID and APP_PRIVATE_KEY must both be set" >&2
  exit 2
fi
# The id lands inside a JSON string: the App's numeric id or its client id,
# nothing that would break out of the quotes. Bash matches the whole value,
# where grep would pass each line of a value holding a newline.
if ! [[ "$APP_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "jwt.sh: APP_ID must be the App's id or client id" >&2
  exit 2
fi

base64url() {
  openssl base64 -A | tr '+/' '-_' | tr -d '='
}

now=$(date +%s)
header=$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | base64url)
payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$APP_ID" | base64url)
signature=$(printf '%s' "$header.$payload" \
  | openssl dgst -sha256 -binary -sign <(printf '%s\n' "$APP_PRIVATE_KEY") \
  | base64url)
printf '%s\n' "$header.$payload.$signature"
