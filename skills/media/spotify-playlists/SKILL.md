---
name: spotify-playlists
description: Monta, edita e decora playlists no Spotify, consulta o gosto musical do usuário, gerencia a biblioteca (curtir, seguir) e controla o que está tocando.
version: 2.0.0
author: vitormanunciato/beedle
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Spotify, Música, Playlist, Player]
---

# Spotify — playlists, biblioteca e player

Todas as ações passam por um script que responde sempre em JSON
(`"ok": false` + `"erro"` quando algo falha).

```bash
SPOTIFY="python3 ${HERMES_HOME:-$HOME/.hermes}/skills/media/spotify-playlists/scripts/spotify.py"
```

Se o caminho não existir, ache com
`find ~/.hermes -path '*spotify-playlists/scripts/spotify.py'`.
Veja todas as opções com `$SPOTIFY -h` ou `$SPOTIFY <comando> -h`.

**Onde pede `<playlist>`** pode ir o nome ("Rock de Estrada"), o ID ou o link.
**Músicas** podem ser `Artista - Título`, link ou URI do Spotify.

## Conectar a conta

Se a resposta disser "Spotify não conectado" ou "refaça o setup":
1. `$SPOTIFY setup-url` → mande o `link` e as `instrucoes` ao usuário.
2. Ele devolve um endereço `http://127.0.0.1:8888/callback?code=...`.
3. `$SPOTIFY setup-finish "<endereço completo>"`.

`$SPOTIFY auth-status` mostra a conta, o plano (free/premium) e permissões
faltando. Nunca mostre `spotify_token.json` nem o `.env`.

## Conhecer o gosto

| Comando | O quê |
|---|---|
| `top-tracks --range short_term\|medium_term\|long_term --limit 50` | mais ouvidas (4 semanas / 6 meses / sempre) |
| `top-artists --range ... --limit 50` | artistas mais ouvidos + gêneros |
| `saved --limit 100` | curtidas |
| `recent --limit 50` | tocadas recentemente |
| `following` | artistas que segue |

## Descobrir músicas

| Comando | O quê |
|---|---|
| `search "consulta" --type track\|artist\|album\|playlist` | busca; aceita filtros `artist:"X"`, `album:"X"`, `year:1985-1989`, `genre:"samba"` |
| `artist-top "Artista" --limit 10` | sucessos de um artista |
| `album-tracks "Álbum"` | faixas de um álbum |

O Spotify não oferece mais "recomendações automáticas" para apps novos.
**Você** escolhe as músicas com seu conhecimento + o gosto do usuário; use
`search`, `artist-top` e `album-tracks` para descobrir e conferir faixas.

## Criar playlist

```bash
$SPOTIFY build --name "Estrada ao Entardecer" --description "Rock nacional pra viagem — por Beedle" <<'EOF'
Legião Urbana - Tempo Perdido
Titãs - Epitáfio
spotify:track:4uLU6hMCjMI75M1A2tKUQC
EOF
```

- Opções: `--public` (padrão é privada), `--collaborative`.
- Peça ~20–30% a mais do que o tamanho desejado: algumas podem não ser achadas.
- Confira `musicas` na resposta (às vezes vem versão ao vivo/cover) e
  corrija com `remove` + `add`. Informe `nao_encontradas` ao usuário.
- Depois crie a capa: `$SPOTIFY cover "<playlist>" --subtitle "frase curta" --colors "#ff7e5f,#2b1055"`
  (escolha duas cores que combinem com o clima da playlist; o título padrão é o nome da playlist).
  Se você tiver uma ferramenta de gerar imagens, pode gerar uma e usar `--image arquivo.png`.

## Editar playlists

| Comando | O quê |
|---|---|
| `playlists` | lista as playlists (nome, id, nº de músicas) |
| `show <playlist>` | músicas com `posicao` (começa em 0) e `uri` |
| `stats <playlist>` | duração total, artistas mais presentes, décadas, repetidas |
| `add <playlist> [--position N] [--skip-existing]` (stdin) | adiciona |
| `add-current <playlist>` | adiciona a música que está tocando agora |
| `remove <playlist> <música> [...]` | remove (todas as ocorrências) |
| `move <playlist> --from I --to J [--count N]` | muda posição |
| `replace <playlist>` (stdin) | regrava a playlist inteira na nova ordem |
| `dedupe <playlist> [--dry-run]` | tira repetidas |
| `edit <playlist> --name/--description/--public/--private/--collaborative` | detalhes |
| `delete <playlist>` | tira da biblioteca do usuário |
| `cover <playlist> [...]` | gera/envia capa |
| `export` | backup completo em JSON (playlists, curtidas, tops) |

- Para reordenar muita coisa (ex.: "organiza como um show"), use `show`,
  monte a nova ordem e aplique com `replace` passando os URIs.
- **Confirme com o usuário antes de**: `remove`, `replace`, `dedupe` (rode
  `--dry-run` primeiro e mostre), `delete`, `--public`, e qualquer mudança em
  playlist que não foi você que criou.

## Biblioteca

`like [música ...]` (sem argumento curte a que está tocando), `unlike <música>`,
`follow <artista>`, `unfollow <artista>`.

## Player (exige Spotify Premium e um aparelho com o Spotify aberto)

| Comando | O quê |
|---|---|
| `now` | o que está tocando, aparelho, volume |
| `devices` | aparelhos disponíveis |
| `play ["música" \| <playlist> --type playlist \| --type album \| --type artist] [--device nome]` | toca (sem argumento: retoma) |
| `pause`, `next`, `prev` | controles |
| `queue "música"` / `queue-show` | fila |
| `transfer <aparelho>` | muda o aparelho |
| `volume 0-100`, `shuffle true\|false`, `repeat track\|context\|off`, `seek <segundos>` | ajustes |

## Erros

O campo `erro` já traz uma dica. Os mais comuns:
- **401 / "refaça o setup"**: conecte de novo (setup-url/setup-finish).
- **403**: conta não liberada em User Management do app, recurso só Premium
  (player), ou permissão faltando (rode `auth-status`).
- **404 no player**: nenhum aparelho ativo; peça para abrir o Spotify.
- **"Mais de uma playlist com esse nome"**: use o `id` da lista que veio no erro.
