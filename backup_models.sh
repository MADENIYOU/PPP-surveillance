#!/usr/bin/env bash
# =============================================================================
# backup_models.sh — Sauvegarde/Restauration des modèles ML entraînés
#
# Usage:
#   ./backup_models.sh save              Sauvegarde les modèles dans backups/
#   ./backup_models.sh restore [date]    Restaure le dernier backup (ou un spécifique)
#   ./backup_models.sh list              Liste les backups disponibles
#   ./backup_models.sh clean [keep=5]    Supprime les vieux backups (garde les N plus récents)
#
# Les modèles sont stockés dans ./pipeline/models/ (bind mount docker-compose).
# Les backups sont archivés dans ./pipeline/models/backups/ avec horodatage.
# =============================================================================
set -euo pipefail

MODELS_DIR="./pipeline/models"
BACKUP_DIR="${MODELS_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ACTION="${1:-save}"

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }

mkdir -p "$MODELS_DIR" "$BACKUP_DIR"

case "$ACTION" in
  save)
    BACKUP_NAME="models_${TIMESTAMP}.tar.gz"
    info "Sauvegarde des modèles → ${BACKUP_NAME}"

    # Liste les fichiers à sauvegarder (modèles, scalers, config, état de retrain)
    FILES_TO_BACKUP=$(find "$MODELS_DIR" -maxdepth 1 \( \
      -name "*.pt" -o -name "*.pkl" -o -name "*.json" \
    \) -type f 2>/dev/null || true)

    if [ -z "$FILES_TO_BACKUP" ]; then
      warn "Aucun modèle à sauvegarder dans $MODELS_DIR"
      exit 0
    fi

    tar -czf "${BACKUP_DIR}/${BACKUP_NAME}" \
      -C "$MODELS_DIR" \
      $(find "$MODELS_DIR" -maxdepth 1 \( -name "*.pt" -o -name "*.pkl" -o -name "*.json" \) -type f -exec basename {} \; 2>/dev/null) \
      2>/dev/null

    BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}" | cut -f1)
    info "Backup créé : ${BACKUP_DIR}/${BACKUP_NAME} (${BACKUP_SIZE})"

    # Crée un manifeste
    echo "backup: ${TIMESTAMP}" > "${BACKUP_DIR}/MANIFEST.txt"
    echo "files:" >> "${BACKUP_DIR}/MANIFEST.txt"
    find "$MODELS_DIR" -maxdepth 1 \( -name "*.pt" -o -name "*.pkl" -o -name "*.json" \) -type f \
      -exec basename {} \; >> "${BACKUP_DIR}/MANIFEST.txt"
    ;;

  restore)
    if [ ! -d "$BACKUP_DIR" ]; then
      warn "Aucun backup trouvé dans $BACKUP_DIR"
      exit 1
    fi

    BACKUP_FILE="${2:-}"
    if [ -z "$BACKUP_FILE" ]; then
      # Dernier backup
      BACKUP_FILE=$(ls -t "${BACKUP_DIR}"/models_*.tar.gz 2>/dev/null | head -1 || true)
      if [ -z "$BACKUP_FILE" ]; then
        warn "Aucun backup .tar.gz trouvé"
        exit 1
      fi
    else
      # Backup spécifique par date
      BACKUP_FILE="${BACKUP_DIR}/models_${2}.tar.gz"
      if [ ! -f "$BACKUP_FILE" ]; then
        warn "Backup introuvable : $BACKUP_FILE"
        echo "  Disponibles :"
        ls -1 "${BACKUP_DIR}"/models_*.tar.gz 2>/dev/null || echo "  (aucun)"
        exit 1
      fi
    fi

    info "Restauration depuis : $(basename "$BACKUP_FILE")"
    ARCHIVE_DIR="$MODELS_DIR/archive"
    mkdir -p "$ARCHIVE_DIR"

    # Sauvegarde de sécurité des modèles actuels avant restauration
    if ls "$MODELS_DIR"/*.pt "$MODELS_DIR"/*.pkl 2>/dev/null | head -1 >/dev/null 2>&1; then
      SAFETY_BACKUP="${ARCHIVE_DIR}/pre_restore_${TIMESTAMP}.tar.gz"
      info "  Sauvegarde de sécurité → $(basename "$SAFETY_BACKUP")"
      tar -czf "$SAFETY_BACKUP" -C "$MODELS_DIR" \
        $(find "$MODELS_DIR" -maxdepth 1 \( -name "*.pt" -o -name "*.pkl" -o -name "*.json" \) -type f -exec basename {} \; 2>/dev/null) \
        2>/dev/null
    fi

    tar -xzf "$BACKUP_FILE" -C "$MODELS_DIR"
    info "Modèles restaurés dans $MODELS_DIR"
    ;;

  list)
    info "Backups disponibles dans $BACKUP_DIR :"
    if ls "${BACKUP_DIR}"/models_*.tar.gz 2>/dev/null | head -1 >/dev/null 2>&1; then
      for f in $(ls -1t "${BACKUP_DIR}"/models_*.tar.gz); do
        SIZE=$(du -h "$f" | cut -f1)
        NAME=$(basename "$f" .tar.gz | sed 's/models_//')
        echo "  ${NAME}  (${SIZE})"
      done
    else
      echo "  (aucun backup)"
    fi

    # Modèles actifs
    info "Modèles actifs dans $MODELS_DIR :"
    find "$MODELS_DIR" -maxdepth 1 \( -name "*.pt" -o -name "*.pkl" \) -type f \
      -exec basename {} \; 2>/dev/null | sort || echo "  (aucun)"
    ;;

  clean)
    KEEP="${2:-5}"
    info "Nettoyage des backups (garde les ${KEEP} plus récents)"
    BACKUPS=$(ls -1t "${BACKUP_DIR}"/models_*.tar.gz 2>/dev/null || true)
    COUNT=$(echo "$BACKUPS" | wc -l | tr -d ' ')
    if [ "$COUNT" -le "$KEEP" ]; then
      info "Rien à supprimer (${COUNT} backups, seuil=${KEEP})"
      exit 0
    fi
    TO_DELETE=$(echo "$BACKUPS" | tail -n +$((KEEP + 1)))
    echo "$TO_DELETE" | while read -r f; do
      rm -f "$f"
      info "Supprimé : $(basename "$f")"
    done
    ;;

  *)
    echo "Usage: $0 {save|restore [date]|list|clean [keep=5]}"
    exit 1
    ;;
esac
