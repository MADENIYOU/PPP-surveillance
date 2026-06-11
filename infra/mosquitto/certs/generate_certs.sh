#!/usr/bin/env sh
# ============================================================================
# Génération PKI MQTT — Surveillance Pollution Dakar (DIC2)
# Référence : 03_securite/PKI_SPEC.md (S3.3)
#
# Génère : CA racine, certificat serveur Mosquitto, certificats clients
# (pipeline + 10 capteurs simulés), puis active le listener TLS 8883 en
# écrivant infra/mosquitto/config/conf.d/tls.conf (lu via include_dir).
#
# Usage (depuis implementation/, Git Bash / WSL / Linux) :
#   sh infra/mosquitto/certs/generate_certs.sh
# Ou sans openssl local, via Docker :
#   docker run --rm -v "$PWD/infra/mosquitto:/m" alpine/openssl sh /m/certs/generate_certs.sh /m/certs /m/config
#
# Les clés privées restent dans ce répertoire (gitignoré — ne jamais committer).
# ============================================================================
set -eu

CERT_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
CONF_DIR="${2:-$CERT_DIR/../config}"
DAYS_CA=1825      # 5 ans
DAYS_LEAF=825     # < 27 mois (bonne pratique navigateurs/clients)
SUBJ_BASE="/C=SN/ST=Dakar/O=ESP-DIC2/OU=PPP-Pollution"

cd "$CERT_DIR"

# ── 1. CA racine ─────────────────────────────────────────────────────────────
if [ ! -f ca.key ]; then
    openssl genrsa -out ca.key 4096
    openssl req -x509 -new -key ca.key -sha256 -days "$DAYS_CA" \
        -subj "$SUBJ_BASE/CN=PPP-Dakar-Root-CA" -out ca.crt
    echo "CA créée : ca.crt"
else
    echo "CA existante réutilisée : ca.crt"
fi

# ── 2. Certificat serveur Mosquitto (SAN : mosquitto, localhost) ─────────────
if [ ! -f server.key ]; then
    openssl genrsa -out server.key 2048
    openssl req -new -key server.key -subj "$SUBJ_BASE/CN=mosquitto" -out server.csr
    cat > server.ext <<EOF
subjectAltName = DNS:mosquitto, DNS:localhost, IP:127.0.0.1
extendedKeyUsage = serverAuth
EOF
    openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
        -sha256 -days "$DAYS_LEAF" -extfile server.ext -out server.crt
    rm -f server.csr server.ext
    echo "Certificat serveur créé : server.crt"
fi

# ── 3. Certificats clients (mTLS) : pipeline + capteurs simulés ──────────────
gen_client() {
    name="$1"
    [ -f "clients/$name.key" ] && return 0
    mkdir -p clients
    openssl genrsa -out "clients/$name.key" 2048
    openssl req -new -key "clients/$name.key" -subj "$SUBJ_BASE/CN=$name" -out "clients/$name.csr"
    openssl x509 -req -in "clients/$name.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
        -sha256 -days "$DAYS_LEAF" -out "clients/$name.crt"
    rm -f "clients/$name.csr"
    echo "Certificat client créé : clients/$name.crt"
}

gen_client pipeline-ingestion
for z in MEDINA PLATEAU PIKINE ALMADIES RUFISQUE PORT PARCELLES GUEDIAWAYE FANN LORA; do
    gen_client "ESP32-DK-$z-001"
done

# Mosquitto (non-root dans le conteneur) doit pouvoir lire la clé serveur.
chmod 644 ca.crt server.crt server.key 2>/dev/null || true

# ── 4. Activation du listener 8883 (include_dir conf.d) ─────────────────────
mkdir -p "$CONF_DIR/conf.d"
cat > "$CONF_DIR/conf.d/tls.conf" <<'EOF'
# Généré par generate_certs.sh — listener TLS/mTLS (PKI_SPEC.md S3.3)
listener 8883
cafile      /mosquitto/certs/ca.crt
certfile    /mosquitto/certs/server.crt
keyfile     /mosquitto/certs/server.key
require_certificate true
use_identity_as_username true
tls_version tlsv1.2
EOF
echo "Listener 8883 activé : $CONF_DIR/conf.d/tls.conf"
echo "Redémarrer le broker : docker compose -f docker-compose.infra.yml restart mosquitto"
