#!/usr/bin/env bash
# Instala/atualiza o Beedle como perfil do Hermes Agent.
# Uso (na VPS):  bash ~/beedle/instalar.sh
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
PERFIL="beedle"
DESTINO="${HERMES_ROOT:-$HOME/.hermes}/profiles/$PERFIL"

command -v hermes >/dev/null || { echo "ERRO: comando 'hermes' não encontrado. Instale o Hermes Agent primeiro."; exit 1; }
command -v python3 >/dev/null || { echo "ERRO: python3 não encontrado."; exit 1; }

if [[ ! -d "$DESTINO" ]]; then
  echo ">> Criando perfil '$PERFIL' (copiando modelo/chaves do perfil padrão)"
  hermes profile create "$PERFIL" --clone \
    --description "Bardo que monta e edita playlists no Spotify"
fi
[[ -d "$DESTINO" ]] || { echo "ERRO: perfil não encontrado em $DESTINO"; exit 1; }

echo ">> Copiando personalidade (SOUL.md)"
[[ -f "$DESTINO/SOUL.md" && ! -f "$DESTINO/SOUL.md.original" ]] && cp "$DESTINO/SOUL.md" "$DESTINO/SOUL.md.original"
cp "$AQUI/SOUL.md" "$DESTINO/SOUL.md"

echo ">> Copiando skill spotify-playlists"
mkdir -p "$DESTINO/skills/media"
rm -rf "$DESTINO/skills/media/spotify-playlists"
cp -r "$AQUI/skills/media/spotify-playlists" "$DESTINO/skills/media/"
chmod +x "$DESTINO/skills/media/spotify-playlists/scripts/spotify.py"

if ! python3 -c "import PIL" 2>/dev/null; then
  echo ">> Pillow não encontrado (usado só para gerar capas). Tentando instalar..."
  python3 -m pip install --user --quiet pillow 2>/dev/null \
    || echo "   Não deu; instale depois com: sudo apt install python3-pil  (o resto funciona sem ele)"
fi

ENV="$DESTINO/.env"
touch "$ENV" && chmod 600 "$ENV"
if ! grep -q '^SPOTIFY_CLIENT_ID=.\+' "$ENV"; then
  echo
  read -rp "Cole o Client ID do seu app do Spotify (ou Enter para pular): " CID
  if [[ -n "$CID" ]]; then
    sed -i '/^SPOTIFY_CLIENT_ID=/d' "$ENV"
    echo "SPOTIFY_CLIENT_ID=$CID" >> "$ENV"
  else
    echo "   (depois coloque SPOTIFY_CLIENT_ID=... em $ENV)"
  fi
fi

echo
echo ">> Pronto! Próximos passos:"
echo "   1. Conectar o Spotify:"
echo "        python3 $DESTINO/skills/media/spotify-playlists/scripts/spotify.py setup-url"
echo "      (ou só converse: '$PERFIL chat' e peça uma playlist — ele te guia)"
echo "   2. Testar:   $PERFIL chat"
echo "   3. Telegram: $PERFIL gateway setup   e depois   $PERFIL gateway install"
