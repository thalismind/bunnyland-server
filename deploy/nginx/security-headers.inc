# Response hardening shared by every Bunnyland server block. Kept in one file because the
# non-tunnel deployment shapes previously carried no security headers at all: anyone serving
# from frontend-http.conf or frontend-tls.conf silently lost CSP, nosniff and framing
# protection that only the tunnel config had.
#
# nginx add_header is replace-not-extend across levels, so any location that declares its
# own add_header must restate these (see @bunnyland_rate_limited in api-locations.inc).
# Directives at the same level combine, so a server block may add its own header alongside
# this include.
#
# Strict-Transport-Security is deliberately NOT here: it varies by deployment shape. The
# tunnel serves a domain we control end to end and asserts includeSubDomains; the
# self-hosted TLS shapes stay origin-only so a subdomain deployment cannot force HSTS onto
# a parent domain's unrelated siblings.
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;
add_header X-Frame-Options "DENY" always;
