#!/usr/bin/env bash
set -euo pipefail

LEAF_CERT="${LEAF_CERT:-/srv/caddy/internal/data/certificates/local/omada-controller.svc.abhaile.home.arpa/omada-controller.svc.abhaile.home.arpa.crt}"
LEAF_KEY="${LEAF_KEY:-/srv/caddy/internal/data/certificates/local/omada-controller.svc.abhaile.home.arpa/omada-controller.svc.abhaile.home.arpa.key}"
ROOT_CERT="${ROOT_CERT:-/srv/caddy/internal/data/pki/authorities/local/root.crt}"
OMADA_ENV="${OMADA_ENV:-/etc/omada-controller/omada-controller.env}"
OUT_DIR="${OUT_DIR:-/srv/omada-controller/omada-controller/cert}"
CERT_NAME="${SSL_CERT_NAME:-tls.crt}"
KEY_NAME="${SSL_KEY_NAME:-tls.key}"

log() { printf '[rebuild-omada-cert] %s\n' "$*" >&2; }

if [[ -f "$OMADA_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$OMADA_ENV"
    CERT_NAME="${SSL_CERT_NAME:-$CERT_NAME}"
    KEY_NAME="${SSL_KEY_NAME:-$KEY_NAME}"
fi

for path in "$LEAF_CERT" "$LEAF_KEY" "$ROOT_CERT"; do
    if [[ ! -r "$path" ]]; then
        log "ERROR: required certificate input is missing or unreadable: $path"
        exit 1
    fi
done

install -d -m 0750 -o root -g root "$OUT_DIR"

cert_tmp="$(mktemp "$OUT_DIR/.${CERT_NAME}.XXXXXX")"
key_tmp="$(mktemp "$OUT_DIR/.${KEY_NAME}.XXXXXX")"

cleanup() {
    rm -f "$cert_tmp" "$key_tmp"
}
trap cleanup EXIT

cat "$LEAF_CERT" "$ROOT_CERT" >"$cert_tmp"
cat "$LEAF_KEY" >"$key_tmp"

chmod 0644 "$cert_tmp"
chmod 0640 "$key_tmp"
chown root:root "$cert_tmp" "$key_tmp"

mv "$cert_tmp" "$OUT_DIR/$CERT_NAME"
mv "$key_tmp" "$OUT_DIR/$KEY_NAME"
trap - EXIT

log "Rebuilt Omada certificate bundle in $OUT_DIR"
systemctl try-restart omada-controller-app-omada-controller.service
