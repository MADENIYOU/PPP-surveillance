#!/usr/bin/env sh
# ============================================================================
# Génération PKI MQTT 3 niveaux — Surveillance Pollution Dakar (DIC2)
# Référence : 03_securite/PKI_SPEC.md (S3.3)
#
# Chaîne : Root CA → Intermediate CA → Server + 9 clients
#
# Génère : Root CA (offline, 10 ans), Intermediate CA (5 ans), certificat
# serveur Mosquitto, certificats clients (pipeline + capteurs simulés),
# puis active le listener TLS 8883 en écrivant
# infra/mosquitto/config/conf.d/tls.conf.
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
DAYS_ROOT=3650     # Root CA : 10 ans (offline)
DAYS_INTER=1825    # Intermediate CA : 5 ans
DAYS_LEAF=825      # Server/Clients : < 27 mois
SUBJ_BASE="/C=SN/ST=Dakar/O=ESP-DIC2/OU=PPP-Pollution"

cd "$CERT_DIR"

# ── 1. Root CA (offline, 10 ans) ─────────────────────────────────────────────
if [ ! -f dakar-root-ca.key ]; then
    openssl genrsa -out dakar-root-ca.key 4096
    openssl req -new -x509 -days "$DAYS_ROOT" -key dakar-root-ca.key -sha256 \
        -subj "$SUBJ_BASE/CN=Dakar-Root-CA" -out dakar-root-ca.crt
    echo "Root CA créée : dakar-root-ca.crt"
else
    echo "Root CA existante réutilisée : dakar-root-ca.crt"
fi

# ── 2. Intermediate CA (signée par Root, 5 ans) ─────────────────────────────
if [ ! -f dakar-intermediate-ca.key ]; then
    openssl genrsa -out dakar-intermediate-ca.key 4096
    openssl req -new -key dakar-intermediate-ca.key -sha256 \
        -subj "$SUBJ_BASE/CN=Dakar-Intermediate-CA" -out dakar-intermediate-ca.csr
    openssl x509 -req -days "$DAYS_INTER" -in dakar-intermediate-ca.csr \
        -CA dakar-root-ca.crt -CAkey dakar-root-ca.key -CAcreateserial \
        -sha256 -out dakar-intermediate-ca.crt
    rm -f dakar-intermediate-ca.csr
    echo "Intermediate CA créée : dakar-intermediate-ca.crt"
else
    echo "Intermediate CA existante réutilisée : dakar-intermediate-ca.crt"
fi

# ── 3. Certificat serveur Mosquitto (signé par Intermediate) ─────────────────
if [ ! -f mosquitto-server.key ]; then
    openssl genrsa -out mosquitto-server.key 2048
    openssl req -new -key mosquitto-server.key -sha256 \
        -subj "$SUBJ_BASE/CN=mosquitto" -out mosquitto-server.csr
    cat > mosquitto-server.ext <<EOF
subjectAltName = DNS:mosquitto, DNS:localhost, IP:127.0.0.1
extendedKeyUsage = serverAuth
EOF
    openssl x509 -req -days "$DAYS_LEAF" -in mosquitto-server.csr \
        -CA dakar-intermediate-ca.crt -CAkey dakar-intermediate-ca.key -CAcreateserial \
        -sha256 -extfile mosquitto-server.ext -out mosquitto-server.crt
    rm -f mosquitto-server.csr mosquitto-server.ext
    # Chaîne complète pour le serveur (certificat + intermédiaire)
    cat mosquitto-server.crt dakar-intermediate-ca.crt > mosquitto-server-chain.crt
    echo "Certificat serveur créé : mosquitto-server.crt (chaîne : mosquitto-server-chain.crt)"
fi

# ── 4. Certificats clients mTLS (signés par Intermediate) ────────────────────
gen_client() {
    name="$1"
    [ -f "clients/$name.key" ] && return 0
    mkdir -p clients
    openssl genrsa -out "clients/$name.key" 2048
    openssl req -new -key "clients/$name.key" -sha256 \
        -subj "$SUBJ_BASE/CN=$name" -out "clients/$name.csr"
    openssl x509 -req -days "$DAYS_LEAF" -in "clients/$name.csr" \
        -CA dakar-intermediate-ca.crt -CAkey dakar-intermediate-ca.key -CAcreateserial \
        -sha256 -out "clients/$name.crt"
    rm -f "clients/$name.csr"
    echo "Certificat client créé : clients/$name.crt"
}

gen_client pipeline-ingestion
for z in MEDINA PLATEAU PIKINE ALMADIES RUFISQUE PORT PARCELLES GUEDIAWAYE FANN LORA; do
    gen_client "ESP32-DK-$z-001"
done

# Mosquitto (non-root dans le conteneur) doit pouvoir lire la clé serveur.
chmod 644 dakar-root-ca.crt dakar-intermediate-ca.crt mosquitto-server.crt mosquitto-server-chain.crt mosquitto-server.key 2>/dev/null || true

# ── 5. Activation du listener 8883 (include_dir conf.d) ─────────────────────
mkdir -p "$CONF_DIR/conf.d"
cat > "$CONF_DIR/conf.d/tls.conf" <<'EOF'
# Généré par generate_certs.sh — listener TLS/mTLS (PKI_SPEC.md S3.3)
# Chaîne 3 niveaux : Root CA → Intermediate CA → Server
listener 8883
cafile      /mosquitto/certs/dakar-intermediate-ca.crt
certfile    /mosquitto/certs/mosquitto-server-chain.crt
keyfile     /mosquitto/certs/mosquitto-server.key
require_certificate true
use_identity_as_username true
tls_version tlsv1.2
EOF
echo "Listener 8883 activé : $CONF_DIR/conf.d/tls.conf"
echo "Redémarrer le broker : docker compose -f docker-compose.infra.yml restart mosquitto"
