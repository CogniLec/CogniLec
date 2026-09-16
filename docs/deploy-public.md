# Deploying the frontend publicly

Today the stack is LAN-only: `DOMAIN=lis.local` doesn't resolve on the
public internet, and Traefik's routers referenced a `local` cert resolver
that was never actually defined (self-signed/undefined TLS). This doc
covers what changed to make a real public domain work, and the steps to
run once you have one.

## What changed (already committed)

- `docker-compose.yml`: Traefik now defines a real `letsencrypt`
  certresolver (HTTP-01 challenge on port 80, cert storage in the
  `traefik-letsencrypt` volume). All routers (`client`, `dozzle`,
  `portainer`, `label-studio`, `mlflow`) point at it instead of the
  nonexistent `local` resolver.
- `docker-compose.yml` / `docker/traefik/dynamic.yml.template`: the API
  (still a bare uvicorn process on host port 8123, not its own container)
  is now routable through Traefik at `api.${DOMAIN}`, over the same public
  TLS cert, via Traefik's file provider and
  `extra_hosts: host.docker.internal:host-gateway`.
- `.env.example`: documents the public values you need to set.

## Steps to actually go public

1. **Own a domain** and be able to edit its DNS. Point an `A` (and `AAAA`
   if you have IPv6) record for both `app.<yourdomain>` and
   `api.<yourdomain>` at this machine's **public** IP. (A wildcard
   `*.<yourdomain>` record also works, since every router here is a
   subdomain of `DOMAIN`.)

2. **Make ports 80 and 443 reach this machine from the internet.** These
   machines are on a private LAN (`192.168.9.x`, see `ansible/inventory.yml`)
   behind NAT. You need either:
   - Router port-forwarding: forward external 80/443 to this machine's
     LAN IP, or
   - A public IP directly on this machine, or
   - A reverse tunnel/relay (e.g. Cloudflare Tunnel) if you can't open
     inbound ports — in that case skip the Let's Encrypt HTTP-01 setup
     below and terminate TLS at the tunnel instead.
   Port 80 specifically must work for the Let's Encrypt HTTP-01 challenge
   to succeed, even though end users only ever see 443.

3. **Set the real values in `.env`** (copy from `.env.example` if you
   haven't):
   ```
   DOMAIN=yourdomain.com
   TRAEFIK_EMAIL=you@yourdomain.com
   VITE_API_BASE_URL=https://api.yourdomain.com
   ```

4. **Render the Traefik dynamic config** (this file isn't templated by
   Docker Compose, so render it once now and again any time `DOMAIN`
   changes):
   ```
   DOMAIN=yourdomain.com envsubst '${DOMAIN}' \
     < docker/traefik/dynamic.yml.template > docker/traefik/dynamic.yml
   ```

5. **Build and start.** The client bakes `VITE_API_BASE_URL` in at build
   time, so a rebuild is required, not just a restart:
   ```
   docker compose build client
   docker compose up -d traefik client
   ```
   (Traefik will request/renew the cert automatically on first request to
   `app.yourdomain.com` — check `docker compose logs traefik` if it
   doesn't show up within a minute or two.)

6. **Verify from outside your network** (phone on cellular data, or
   https://www.ssllabs.com/ssltest/, works better than testing from the
   same LAN, which can hide NAT/firewall issues):
   - `https://app.yourdomain.com` loads the client with a valid cert.
   - `https://api.yourdomain.com/<a real endpoint>` responds (not a
     Traefik 404/502 — 502 means Traefik can't reach the host's uvicorn
     process on :8123, e.g. because it's not running or bound to
     `127.0.0.1` only instead of `0.0.0.0`).
   - Register/login end-to-end through the public URL.

## Known gaps to be aware of

- **The API is still a bare host process**, not a container — it has no
  restart policy, no resource limits, and nothing keeps it running across
  a reboot. Fine for now since scope here was "deploy the frontend," but
  worth containerizing before real users depend on uptime.
- **CORS is wide open** (`allow_origins=["*"]` in `src/api/main.py`) —
  intentional for LAN dev, but worth tightening to just
  `https://app.yourdomain.com` once you're public, especially since the
  API also handles auth.
- **Let's Encrypt rate limits**: don't loop `docker compose up`/`down` on
  a broken DNS/port-forward setup — 5 failures per account/hostname per
  hour will get you temporarily blocked. Fix DNS/port-forwarding first,
  confirm with `curl -I http://app.yourdomain.com` from outside your
  network, then start Traefik.
