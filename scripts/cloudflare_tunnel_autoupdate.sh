#!/usr/bin/env bash
# Keeps the free Cloudflare quick tunnel (src/api -> public URL) alive and
# keeps GitHub Pages pointed at whatever its current URL is.
#
# Why this exists: quick tunnels (no owned domain, see docs/gaps.md) get a
# brand-new random URL every time the tunnel process restarts (container
# restart, host reboot, Cloudflare recycling the session). Nothing else
# updates automatically, so login on the public site silently breaks
# whenever that happens. This script is meant to run on a schedule (cron)
# and is idempotent: if the tunnel is missing it starts one; if the URL in
# the container's logs doesn't match the current VITE_API_BASE_URL GitHub
# secret, it updates the secret and redeploys Pages.
set -euo pipefail

REPO="CogniLec/CogniLec"
CONTAINER=lis-cloudflared
STATE_FILE="$HOME/.cache/lis_tunnel_url"
GH="$HOME/.local/bin/gh"

mkdir -p "$(dirname "$STATE_FILE")"

# Ensure a tunnel container is running at all.
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$CONTAINER" --network lis-edge --restart unless-stopped \
        cloudflare/cloudflared:latest tunnel --url http://lis-api:8123 >/dev/null
    sleep 8
fi

CURRENT_URL=$(docker logs "$CONTAINER" 2>&1 | grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' | tail -1)

if [ -z "$CURRENT_URL" ]; then
    echo "no tunnel URL found yet in $CONTAINER logs" >&2
    exit 1
fi

LAST_URL=""
[ -f "$STATE_FILE" ] && LAST_URL=$(cat "$STATE_FILE")

if [ "$CURRENT_URL" = "$LAST_URL" ]; then
    exit 0
fi

# Confirm the tunnel actually answers before pointing the public site at it.
if ! curl -sf -m 8 -o /dev/null "$CURRENT_URL/health"; then
    echo "tunnel URL $CURRENT_URL not reachable yet, skipping update" >&2
    exit 1
fi

"$GH" secret set VITE_API_BASE_URL --repo "$REPO" --body "$CURRENT_URL"
"$GH" workflow run "Deploy frontend to GitHub Pages" --repo "$REPO"
echo "$CURRENT_URL" > "$STATE_FILE"
echo "updated VITE_API_BASE_URL to $CURRENT_URL and triggered redeploy"
