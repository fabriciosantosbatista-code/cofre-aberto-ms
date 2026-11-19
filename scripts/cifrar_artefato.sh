#!/usr/bin/env bash
# Cifra uma pasta para virar artefato do Actions (artefato de repositório público é baixável por qualquer usuário
# logado no GitHub). Uso: scripts/cifrar_artefato.sh <pasta de origem> <saída .gpg>
# A senha vem do secret ARTEFATO_CHAVE (variável de ambiente) e entra no gpg pelo descritor 3 — nunca na linha de
# comando nem no log. Depois de cifrar, confere que a pasta de saída só tem o .gpg e que ele está de fato cifrado
# (pacote OpenPGP simétrico, sem o conteúdo legível); se não, apaga a saída e falha — nada é enviado.
set -euo pipefail
origem="$1"; saida="$2"
[ -n "${ARTEFATO_CHAVE:-}" ] || { echo "❌ secret ARTEFATO_CHAVE vazio: nada é cifrado nem enviado"; exit 1; }
[ -d "$origem" ] && [ -n "$(ls -A "$origem")" ] || { echo "ℹ️ $origem vazio: nada a enviar"; exit 0; }
case "$saida" in *.gpg) ;; *) echo "❌ a saída precisa terminar em .gpg"; exit 1;; esac
dir=$(dirname "$saida"); mkdir -p "$dir"
tar -C "$origem" -cf - . | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 \
  --symmetric --cipher-algo AES256 -o "$saida" 3< <(printf '%s' "$ARTEFATO_CHAVE")
falha() { echo "❌ $1 — saída apagada, nada é enviado"; rm -rf "$dir"; exit 1; }
[ "$(find "$dir" -type f ! -name '*.gpg' | wc -l)" -eq 0 ] || falha "há arquivo não cifrado em $dir"
file -b "$saida" | grep -qi "PGP symmetric key encrypted" || falha "$saida não é um arquivo OpenPGP cifrado"
! grep -qaE '%PDF|"nome"|"remuneracao' "$saida" || falha "conteúdo legível dentro de $saida"
echo "🔒 $(basename "$saida"): $(du -h "$saida" | cut -f1) cifrado (AES-256)"
