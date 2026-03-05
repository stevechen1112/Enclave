#!/usr/bin/env bash
# ========================================================
# SSL Certificate Setup Script (Let's Encrypt / Certbot)
# ========================================================
# Installs certbot and obtains SSL certificates for both
# client and admin domains.
#
# Prerequisites:
#   - DNS A records pointing to this server
#   - Port 80 open for HTTP-01 challenge
#   - Nginx installed and running
#
# Usage:
#   chmod +x scripts/setup-ssl.sh
#   sudo ./scripts/setup-ssl.sh
# ========================================================

set -euo pipefail

# ── Configuration ──
CLIENT_DOMAIN="${CLIENT_DOMAIN:-app.yourcompany.com}"
ADMIN_DOMAIN="${ADMIN_DOMAIN:-admin.yourcompany.com}"
EMAIL="${CERTBOT_EMAIL:-admin@yourcompany.com}"

echo "════════════════════════════════════════════"
echo "  Enclave SSL Certificate Setup"
echo "════════════════════════════════════════════"
echo "  Client domain: ${CLIENT_DOMAIN}"
echo "  Admin domain:  ${ADMIN_DOMAIN}"
echo "  Email:         ${EMAIL}"
echo "════════════════════════════════════════════"

# ── Step 1: Install certbot ──
echo ""
echo "▸ Installing certbot..."
if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq certbot python3-certbot-nginx
elif command -v dnf &>/dev/null; then
    dnf install -y certbot python3-certbot-nginx
elif command -v brew &>/dev/null; then
    brew install certbot
else
    echo "✗ Unsupported package manager. Please install certbot manually."
    exit 1
fi

echo "✓ Certbot installed"

# ── Step 2: Obtain certificates ──
echo ""
echo "▸ Obtaining SSL certificate for ${CLIENT_DOMAIN}..."
certbot --nginx \
    -d "${CLIENT_DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --redirect

echo "✓ Certificate obtained for ${CLIENT_DOMAIN}"

echo ""
echo "▸ Obtaining SSL certificate for ${ADMIN_DOMAIN}..."
certbot --nginx \
    -d "${ADMIN_DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --redirect

echo "✓ Certificate obtained for ${ADMIN_DOMAIN}"

# ── Step 3: Setup auto-renewal ──
echo ""
echo "▸ Setting up auto-renewal cron job..."
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --deploy-hook 'systemctl reload nginx'") | sort -u | crontab -

echo "✓ Auto-renewal configured (daily at 3 AM)"

# ── Step 4: Test renewal ──
echo ""
echo "▸ Testing renewal..."
certbot renew --dry-run

echo ""
echo "════════════════════════════════════════════"
echo "  ✓ SSL setup complete!"
echo ""
echo "  Certificates:"
echo "    ${CLIENT_DOMAIN}: /etc/letsencrypt/live/${CLIENT_DOMAIN}/"
echo "    ${ADMIN_DOMAIN}:  /etc/letsencrypt/live/${ADMIN_DOMAIN}/"
echo ""
echo "  Auto-renewal: enabled (certbot renew via cron)"
echo "════════════════════════════════════════════"
