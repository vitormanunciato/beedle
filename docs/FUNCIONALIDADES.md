# Funcionalidades do Beedle e de onde vieram

Base para o futuro repositório único. O código do Beedle foi escrito do
zero (Python, só biblioteca padrão); os repositórios abaixo serviram de
referência de funcionalidades.

| Repositório | Licença | Linguagem |
|---|---|---|
| [fabioc-aloha/spotify-skill](https://github.com/fabioc-aloha/spotify-skill) | Apache-2.0 | Python |
| [lukegeel101/Spotify-AI-Agent](https://github.com/lukegeel101/Spotify-AI-Agent) | sem licença declarada | Python |
| [zcaceres/spotify-cli](https://github.com/zcaceres/spotify-cli) | MIT | TypeScript |
| [UffaModey/spotify-ai-agent-playlist-curator](https://github.com/UffaModey/spotify-ai-agent-playlist-curator) | CC0 | Python |

## Mapa

| Funcionalidade | Origem | Comando no Beedle |
|---|---|---|
| Playlist a partir de descrição em linguagem natural | curator, spotify-skill | o agente escolhe + `build` |
| Playlist a partir de lista de músicas | spotify-skill, curator | `build` |
| Playlist por artista | spotify-skill | `artist-top`, `album-tracks` + `build` |
| Playlist por tema / palavras / filtros de busca | spotify-skill | `search` com `genre:`, `year:` etc. |
| Playlist pelo gosto do usuário (tops, curtidas, recentes) | spotify-skill | `top-tracks`, `top-artists`, `saved`, `recent` |
| Capa personalizada da playlist | spotify-skill | `cover` (gera com Pillow ou usa `--image`) |
| Estatísticas da playlist | spotify-skill | `stats` |
| Exportar dados (backup) | spotify-skill | `export` |
| Apagar playlist | spotify-skill | `delete` |
| Listar playlists (com paginação) | spotify-skill, spotify-cli, Spotify-AI-Agent | `playlists` |
| Achar playlist pelo nome | Spotify-AI-Agent | qualquer `<playlist>` aceita nome |
| Adicionar a música que está tocando | Spotify-AI-Agent | `add-current` |
| O que está tocando | Spotify-AI-Agent, spotify-cli | `now` |
| Controle do player (play, pause, próxima, anterior, volume, aleatório, repetir, seek) | spotify-cli, spotify-skill | `play`, `pause`, `next`, `prev`, `volume`, `shuffle`, `repeat`, `seek` |
| Fila e aparelhos | spotify-cli | `queue`, `queue-show`, `devices`, `transfer` |
| Curtir/descurtir, seguir artistas | spotify-cli, spotify-skill | `like`, `unlike`, `follow`, `unfollow`, `following` |
| Adicionar em posição, regravar playlist, colaborativa | spotify-cli | `add --position`, `replace`, `edit --collaborative` |
| Nomes legíveis em vez de IDs; códigos de saída | spotify-cli | saída JSON com nomes; códigos 0–4 |
| Login PKCE sem client secret, renovação automática | spotify-cli | `setup-url` / `setup-finish` |
| Endpoints novos do Spotify (2026) | spotify-cli | `/items`, `/me/playlists`, `/me/library` com reserva para os antigos |

## Melhorias do Beedle (não existem nos originais)

- Pula música repetida ao montar e `add --skip-existing`; `dedupe` limpa repetidas.
- Confere se o artista encontrado bate com o pedido antes de aceitar a faixa.
- Funciona com a API nova e a antiga do Spotify (testado nas duas).
- Mensagens de erro com dica do que fazer (401, 403, sem aparelho...).
- Personalidade, regras de confirmação e de "nunca inventar" no `SOUL.md`.
- Testes automáticos com Spotify falso: `python3 -m unittest discover -s tests`.

## Ficou de fora (por quê)

| Item | Origem | Motivo |
|---|---|---|
| Recomendações automáticas, artistas relacionados, características de áudio | spotify-skill, spotify-cli | Spotify bloqueou para apps novos desde nov/2024 |
| Voz (microfone/fala) | Spotify-AI-Agent | deve ficar a cargo do Hermes/Telegram (áudio); verificar se o Hermes já transcreve mensagens de voz |
| Chamada própria à OpenAI | curator, Spotify-AI-Agent | o próprio Hermes é o cérebro; não precisa de outra IA |
| Álbuns salvos (salvar/remover álbum) | spotify-cli | pouco útil para playlists; fácil de incluir no repo único |
