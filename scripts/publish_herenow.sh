#!/usr/bin/env bash
# Publish the static redirect site in public/ to here.now (https://here.now).
#
# here.now hosts static files only, so — exactly like the Vercel target — it
# serves the landing/redirect page that points at the Streamlit app on Render.
# The Streamlit server itself cannot run there.
#
# Usage:
#   scripts/publish_herenow.sh [dir]            # default dir: public
#
# Environment:
#   HERENOW_API_KEY      Personal API key (hnk_...). Without it the Site is
#                        anonymous and expires after 24 h (a claim URL is
#                        printed so the owner can keep it).
#   HERENOW_SLUG         Existing Site slug to update instead of creating a
#                        new one. Falls back to the slug saved in
#                        .herenow/state.json from a previous run.
#   HERENOW_CLAIM_TOKEN  Claim token for updating an anonymous Site.
#
# API flow (https://here.now/docs): POST/PUT /api/v1/publish -> PUT each file
# to its presigned URL -> POST .../finalize. The Site is not live until the
# finalize call succeeds. Requires curl, jq, sha256sum.
set -euo pipefail

BASE_URL="${HERENOW_BASE_URL:-https://here.now}"
TARGET="${1:-public}"
API_KEY="${HERENOW_API_KEY:-}"
SLUG="${HERENOW_SLUG:-}"
CLAIM_TOKEN="${HERENOW_CLAIM_TOKEN:-}"
STATE_FILE=".herenow/state.json"
DISPLAY_NAME="Acoustic Diagnostic Agent"
DISPLAY_DESCRIPTION="Static entry page redirecting to the Streamlit app on Render."

die() { echo "error: $*" >&2; exit 1; }

for cmd in curl jq sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || die "requires $cmd"
done
[[ -d "$TARGET" ]] || die "not a directory: $TARGET"

if [[ -z "$API_KEY" && -f "$HOME/.herenow/credentials" ]]; then
  API_KEY="$(tr -d '[:space:]' < "$HOME/.herenow/credentials")"
fi
if [[ -z "$SLUG" && -f "$STATE_FILE" ]]; then
  SLUG="$(jq -r '.slug // empty' "$STATE_FILE")"
fi
if [[ -n "$SLUG" && -z "$CLAIM_TOKEN" && -f "$STATE_FILE" ]]; then
  CLAIM_TOKEN="$(jq -r '.claimToken // empty' "$STATE_FILE")"
fi

content_type() {
  case "${1##*.}" in
    html|htm) echo "text/html; charset=utf-8" ;;
    css) echo "text/css; charset=utf-8" ;;
    js|mjs) echo "text/javascript; charset=utf-8" ;;
    json) echo "application/json; charset=utf-8" ;;
    txt|md) echo "text/plain; charset=utf-8" ;;
    svg) echo "image/svg+xml" ;;
    png) echo "image/png" ;;
    ico) echo "image/x-icon" ;;
    *) file --brief --mime-type "$1" 2>/dev/null || echo "application/octet-stream" ;;
  esac
}

# Manifest: path, size, contentType, sha256 for every file under TARGET.
FILES_JSON="[]"
while IFS= read -r -d '' f; do
  rel="${f#"$TARGET"/}"
  FILES_JSON="$(jq --arg p "$rel" --argjson s "$(wc -c < "$f")" \
    --arg c "$(content_type "$f")" --arg h "$(sha256sum "$f" | cut -d' ' -f1)" \
    '. + [{path: $p, size: $s, contentType: $c, hash: $h}]' <<<"$FILES_JSON")"
done < <(find "$TARGET" -type f ! -name .DS_Store -print0 | sort -z)
[[ "$(jq length <<<"$FILES_JSON")" -gt 0 ]] || die "no files under $TARGET"

BODY="$(jq --arg n "$DISPLAY_NAME" --arg d "$DISPLAY_DESCRIPTION" \
  '{files: ., displayName: $n, displayDescription: $d, viewer: {title: $n, description: $d}}' \
  <<<"$FILES_JSON")"
[[ -n "$SLUG" && -n "$CLAIM_TOKEN" ]] && BODY="$(jq --arg t "$CLAIM_TOKEN" '.claimToken = $t' <<<"$BODY")"

AUTH=()
[[ -n "$API_KEY" ]] && AUTH=(-H "authorization: Bearer $API_KEY")
CLIENT=(-H "x-herenow-client: acoustic-diagnostic-agent/publish-herenow-sh")

if [[ -n "$SLUG" ]]; then
  METHOD=PUT; URL="$BASE_URL/api/v1/publish/$SLUG"
else
  METHOD=POST; URL="$BASE_URL/api/v1/publish"
fi

echo "here.now: $METHOD $URL ($(jq length <<<"$FILES_JSON") files)" >&2
RESP="$(curl -sS -X "$METHOD" "$URL" "${AUTH[@]+"${AUTH[@]}"}" "${CLIENT[@]}" \
  -H "content-type: application/json" -d "$BODY")"
if jq -e '.error' <<<"$RESP" >/dev/null 2>&1; then
  die "$(jq -r '.error + (.message // "" | if . == "" then "" else ": " + . end)' <<<"$RESP")"
fi

OUT_SLUG="$(jq -r '.slug' <<<"$RESP")"
SITE_URL="$(jq -r '.siteUrl' <<<"$RESP")"
VERSION_ID="$(jq -r '.upload.versionId' <<<"$RESP")"
FINALIZE_URL="$(jq -r '.upload.finalizeUrl' <<<"$RESP")"
[[ "$OUT_SLUG" != "null" && "$FINALIZE_URL" != "null" ]] || die "unexpected response: $RESP"

# Upload every file the server did not already have (unchanged hashes are skipped).
while IFS=$'\t' read -r path url ct; do
  [[ -n "$path" ]] || continue
  CT=()
  [[ -n "$ct" ]] && CT=(-H "Content-Type: $ct")
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X PUT "$url" "${CT[@]+"${CT[@]}"}" \
    --data-binary "@$TARGET/$path")"
  [[ "$code" -ge 200 && "$code" -lt 300 ]] || die "upload failed for $path (HTTP $code)"
  echo "here.now: uploaded $path" >&2
done < <(jq -r '.upload.uploads[] | [.path, .url, (.headers["Content-Type"] // "")] | @tsv' <<<"$RESP")

FIN="$(curl -sS -X POST "$FINALIZE_URL" "${AUTH[@]+"${AUTH[@]}"}" "${CLIENT[@]}" \
  -H "content-type: application/json" -d "{\"versionId\":\"$VERSION_ID\"}")"
if jq -e '.error' <<<"$FIN" >/dev/null 2>&1; then
  die "finalize failed: $(jq -r '.error' <<<"$FIN")"
fi

CLAIM_URL="$(jq -r '.claimUrl // empty' <<<"$RESP")"
NEW_CLAIM_TOKEN="$(jq -r '.claimToken // empty' <<<"$RESP")"
EXPIRES="$(jq -r '.expiresAt // empty' <<<"$RESP")"

# Local state so the next run updates the same Site (never commit this file).
# Merged over the previous entry: an update response carries no claim fields.
mkdir -p "$(dirname "$STATE_FILE")"
PREV="{}"
[[ -f "$STATE_FILE" ]] && PREV="$(cat "$STATE_FILE")"
jq -n --argjson prev "$PREV" --arg slug "$OUT_SLUG" --arg url "$SITE_URL" \
  --arg token "$NEW_CLAIM_TOKEN" --arg claim "$CLAIM_URL" --arg exp "$EXPIRES" \
  --arg ver "$(jq -r '.currentVersionId // empty' <<<"$FIN")" \
  '$prev + ({slug: $slug, siteUrl: $url, claimToken: $token, claimUrl: $claim,
             expiresAt: $exp, versionId: $ver} | with_entries(select(.value != "")))' \
  > "$STATE_FILE"

echo "$SITE_URL"
echo "publish_result.slug=$OUT_SLUG" >&2
if [[ -n "$API_KEY" ]]; then
  echo "publish_result.persistence=permanent" >&2
else
  echo "publish_result.persistence=expires_24h" >&2
  echo "publish_result.expires_at=$(jq -r '.expiresAt // empty' "$STATE_FILE")" >&2
  echo "publish_result.claim_url=$(jq -r --arg b "$BASE_URL" \
    '.claimUrl // (if .claimToken then $b + "/c/" + .claimToken else "" end)' "$STATE_FILE")" >&2
fi
