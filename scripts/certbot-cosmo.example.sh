#!/usr/bin/env bash
# Ejemplo: certificado Let's Encrypt para cosmo.codla.co (origen detrás de Cloudflare proxy).
# 1) DNS cosmo.codla.co → IP de la VM (proxy naranja activo está bien).
# 2) Puerto 80 accesible desde Internet (Cloudflare y/o firewall).
# 3) Nginx ya sirve location /.well-known/acme-challenge/ → /var/www/certbot
#
# Uso:
#   sudo mkdir -p /var/www/certbot
#   sudo certbot certonly --webroot -w /var/www/certbot -d cosmo.codla.co --email TU@CORREO --agree-tos --non-interactive
#
# Luego: descomentar el bloque server :443 en scripts/nginx-rag.conf, nginx -t, reload.
# En Cloudflare: SSL/TLS → Overview → Full (strict).

set -euo pipefail
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d cosmo.codla.co "$@"
