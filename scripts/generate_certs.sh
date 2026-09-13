#!/bin/bash
# Generate self-signed TLS certificates for Traefik (local dev)
# For production, use Let's Encrypt via Traefik ACME.
#
# Prerequisites: openssl (or mkcert for trusted local CA)
# Usage: bash scripts/generate_certs.sh

set -euo pipefail

CERT_DIR="docker/traefik/certs"
DOMAIN="${DOMAIN:-lis.local}"

mkdir -p "$CERT_DIR"

if command -v mkcert &>/dev/null; then
    echo "Using mkcert for trusted local CA..."
    mkcert -install 2>/dev/null || true
    mkcert \
        -cert-file "$CERT_DIR/cert.pem" \
        -key-file "$CERT_DIR/key.pem" \
        "$DOMAIN" "*.$DOMAIN" localhost 127.0.0.1 ::1
else
    echo "mkcert not found, using openssl self-signed cert..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$CERT_DIR/key.pem" \
        -out "$CERT_DIR/cert.pem" \
        -subj "/CN=$DOMAIN" \
        -addext "subjectAltName=DNS:$DOMAIN,DNS:*.$DOMAIN,DNS:localhost,IP:127.0.0.1"
fi

echo "Certificates written to $CERT_DIR/"
ls -la "$CERT_DIR/"
