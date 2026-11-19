#!/usr/bin/env bash
# Decifra um artefato .gpg gerado por scripts/cifrar_artefato.sh. Uso: scripts/decifrar_artefato.sh <entrada .gpg> <pasta de destino>
# A senha vem do secret ARTEFATO_CHAVE (variável de ambiente), pelo descritor 3 — nunca na linha de comando nem no log.
set -euo pipefail
entrada="$1"; destino="$2"
[ -n "${ARTEFATO_CHAVE:-}" ] || { echo "❌ secret ARTEFATO_CHAVE vazio"; exit 1; }
[ -f "$entrada" ] || { echo "ℹ️ $entrada não existe"; exit 1; }
mkdir -p "$destino"
gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 3 -d "$entrada" 3< <(printf '%s' "$ARTEFATO_CHAVE") | tar -C "$destino" -xf -
echo "🔓 $(basename "$entrada") decifrado em $destino"
