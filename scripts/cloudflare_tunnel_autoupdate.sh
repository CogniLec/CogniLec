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

# Health checks resolve DNS over HTTPS (1.1.1.1) instead of the system
# resolver: confirmed live that this host's router/ISP resolver fails to
# resolve fresh *.trycloudflare.com names for a while (tunnel healthy, curl
# exit 6), which made the check declare a working tunnel dead and churn
# through new URLs.
CURL_HEALTH=(curl -sf -m 10 -o /dev/null --doh-url https://1.1.1.1/dns-query)

REPO="CogniLec/CogniLec"
CONTAINER=lis-cf-tunnel
STATE_FILE="$HOME/.cache/lis_tunnel_url"
GH="$(command -v gh || echo "$HOME/.local/bin/gh")"

mkdir -p "$(dirname "$STATE_FILE")"

start_fresh_tunnel() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$CONTAINER" --network host --restart unless-stopped \
        cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://127.0.0.1:8123 >/dev/null
    sleep 15
}

# Ensure a tunnel container is running at all.
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    start_fresh_tunnel
fi

CURRENT_URL=$(docker logs "$CONTAINER" 2>&1 | grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' | tail -1)

if [ -z "$CURRENT_URL" ]; then
    echo "no tunnel URL found yet in $CONTAINER logs" >&2
    exit 1
fi

# Always health-check, not just when the URL string changed -- confirmed
# live: Cloudflare can revoke/expire a quick tunnel's registration
# ("Unauthorized: Tunnel not found") server-side while the container keeps
# running and its logged URL stays the same. The old version of this
# script only re-checked reachability when CURRENT_URL != LAST_URL, so a
# tunnel that died this way was silently never detected or recovered --
# the public site stayed broken indefinitely despite this script "running
# fine" every 5 minutes. If the current URL is dead, force a completely
# fresh tunnel (new registration, new URL) rather than waiting on the
# existing, broken one to recover on its own.
if ! "${CURL_HEALTH[@]}" "$CURRENT_URL/health"; then
    echo "tunnel URL $CURRENT_URL not reachable, forcing a fresh tunnel" >&2
    start_fresh_tunnel
    CURRENT_URL=$(docker logs "$CONTAINER" 2>&1 | grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' | tail -1)
    if [ -z "$CURRENT_URL" ] || ! "${CURL_HEALTH[@]}" "$CURRENT_URL/health"; then
        echo "fresh tunnel still not reachable, giving up this run" >&2
        exit 1
    fi
fi

LAST_URL=""
[ -f "$STATE_FILE" ] && LAST_URL=$(cat "$STATE_FILE")

if [ "$CURRENT_URL" = "$LAST_URL" ]; then
    exit 0
fi

printf '%s' "$CURRENT_URL" | "$GH" secret set VITE_API_BASE_URL --repo "$REPO"
"$GH" workflow run "Deploy frontend to GitHub Pages" --repo "$REPO"
echo "$CURRENT_URL" > "$STATE_FILE"
echo "updated VITE_API_BASE_URL to $CURRENT_URL and triggered redeploy"
