# syntax=docker/dockerfile:1.7

# ---- Build the frontend --------------------------------------------------
FROM node:20-alpine AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---- Runtime: nginx serves static files + reverse-proxies /api ----------
FROM nginx:1.27-alpine AS runtime

# envsubst (from gettext) is used by the entrypoint hook to render the
# FQDN-specific nginx config.
RUN apk add --no-cache gettext wget \
 && rm -f /etc/nginx/conf.d/default.conf

# Config templates — one for HTTP-only, one for HTTPS. The entrypoint
# script picks the right one at runtime based on SSL_ENABLED.
COPY docker/web/nginx/http.conf.template  /etc/nginx/templates/http.conf.template
COPY docker/web/nginx/https.conf.template /etc/nginx/templates/https.conf.template

# Nginx's official image auto-runs every executable in /docker-entrypoint.d/
# before starting nginx. Number prefix controls order.
COPY docker/web/render-config.sh /docker-entrypoint.d/20-render-config.sh
RUN chmod +x /docker-entrypoint.d/20-render-config.sh

COPY --from=frontend-builder /build/dist /usr/share/nginx/html

EXPOSE 80 443

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost/ >/dev/null || exit 1
