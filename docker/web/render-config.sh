#!/bin/sh
# Renders the right nginx config from /etc/nginx/templates based on
# SSL_ENABLED. Runs as part of the nginx:alpine entrypoint chain before
# nginx itself starts.

set -eu

SSL_ENABLED="${SSL_ENABLED:-false}"
FQDN="${FQDN:-localhost}"

case "$SSL_ENABLED" in
    true|1|yes|on)
        TEMPLATE=/etc/nginx/templates/https.conf.template
        mode="HTTPS"
        ;;
    *)
        TEMPLATE=/etc/nginx/templates/http.conf.template
        mode="HTTP-only"
        ;;
esac

export FQDN
envsubst '${FQDN}' < "$TEMPLATE" > /etc/nginx/conf.d/default.conf

echo "render-config: ${mode} for FQDN=${FQDN}"
