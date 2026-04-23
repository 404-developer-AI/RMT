#!/bin/sh
# Renders the right nginx config from /etc/rmt/templates based on
# SSL_ENABLED. Runs as part of the nginx:alpine entrypoint chain before
# nginx itself starts.
#
# Templates live under /etc/rmt/templates (NOT /etc/nginx/templates) so
# the upstream envsubst hook does not render the unused template too.

set -eu

SSL_ENABLED="${SSL_ENABLED:-false}"
FQDN="${FQDN:-localhost}"

case "$SSL_ENABLED" in
    true|1|yes|on)
        TEMPLATE=/etc/rmt/templates/https.conf.template
        mode="HTTPS"
        ;;
    *)
        TEMPLATE=/etc/rmt/templates/http.conf.template
        mode="HTTP-only"
        ;;
esac

export FQDN
envsubst '${FQDN}' < "$TEMPLATE" > /etc/nginx/conf.d/default.conf

echo "render-config: ${mode} for FQDN=${FQDN}"
