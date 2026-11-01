# Beedle — o bardo das playlists

[![testes](https://github.com/vitormanunciato/beedle/actions/workflows/testes.yml/badge.svg)](https://github.com/vitormanunciato/beedle/actions/workflows/testes.yml)

Agente de IA para o Spotify, feito como perfil do [Hermes Agent](https://github.com/NousResearch/hermes-agent):
monta, edita e decora playlists, conhece seu gosto musical e controla o player,
com personalidade de bardo.

```
SOUL.md                                   personalidade do Beedle
skills/media/spotify-playlists/SKILL.md   como o agente usa o Spotify
skills/media/spotify-playlists/scripts/spotify.py   acesso à API (só Python padrão; Pillow para capas)
tests/test_spotify.py                     testes com um Spotify falso
docs/FUNCIONALIDADES.md                   o que ele faz e de onde veio cada função
instalar.sh                               instala/atualiza o perfil na VPS
.env.example                              variáveis necessárias (sem valores)
```

O que ele faz:
- cria playlists a partir de pedidos ("rock nacional pra viagem, 2 horas"),
  de listas de músicas, por artista ou pelo seu gosto;
- gera e coloca **capa** personalizada nas playlists;
- edita playlists: adiciona (inclusive "a que está tocando"), remove,
  reordena, tira repetidas, renomeia, torna colaborativa, mostra estatísticas;
- curte músicas, segue artistas e faz backup dos seus dados;
- controla o player: tocar, pausar, próxima, fila, volume, trocar aparelho
  (exige Spotify Premium).

Lista completa e origem de cada função: [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md).
Testes: `python3 -m unittest discover -s tests`.

## 1. Criar o app no Spotify (uma vez)

1. Entre em https://developer.spotify.com/dashboard com sua conta Spotify e clique em **Create app**.
2. Preencha nome (ex.: `Beedle`) e descrição.
3. Em **Redirect URIs** coloque exatamente: `http://127.0.0.1:8888/callback`
4. Em **Which API/SDKs are you planning to use?** marque **Web API**. Salve.
5. Copie o **Client ID**. O Client Secret **não** é necessário.
6. Em **User Management**, adicione o e-mail da conta Spotify que o Beedle vai usar
   (apps em modo de desenvolvimento só funcionam para usuários cadastrados ali).

## 2. Instalar na VPS

```bash
git clone https://github.com/vitormanunciato/beedle ~/beedle
```

```bash
bash ~/beedle/instalar.sh
```

Se o repositório for **privado**, a VPS precisa de uma chave de acesso só de leitura:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/beedle_deploy -N "" -C "beedle-vps" && cat ~/.ssh/beedle_deploy.pub
```

Cadastre a chave em **beedle → Settings → Deploy keys → Add deploy key** (sem
marcar escrita) e clone assim:

```bash
GIT_SSH_COMMAND="ssh -i ~/.ssh/beedle_deploy -o IdentitiesOnly=yes" git clone git@github.com:vitormanunciato/beedle.git ~/beedle && git -C ~/beedle config core.sshCommand "ssh -i ~/.ssh/beedle_deploy -o IdentitiesOnly=yes"
```

O script cria o perfil `beedle`, copia a personalidade e a skill e pede o Client ID.

## 3. Conectar a conta do Spotify

Converse com ele (`beedle chat`) e peça uma playlist: ele manda um link. Ou rode direto:

```bash
python3 ~/.hermes/profiles/beedle/skills/media/spotify-playlists/scripts/spotify.py setup-url
```

Abra o link no celular ou computador, aceite, e o navegador vai para uma página
`http://127.0.0.1:8888/callback?code=...` que **não abre** — é normal. Copie esse
endereço inteiro e mande para o Beedle (ou rode `... spotify.py setup-finish "<endereço>"`).

## 4. Falar com ele pelo Telegram (opcional)

Crie um bot novo no @BotFather só para o Beedle e rode:

```bash
beedle gateway setup
```

```bash
beedle gateway install
```

## Atualizar depois de mudanças no GitHub

```bash
cd ~/beedle && git pull && bash instalar.sh
```

## Observação sobre a API do Spotify

Desde o fim de 2024 o Spotify não libera para apps novos os endpoints de
"recomendações" e "características de áudio". Por isso o Beedle escolhe as
músicas pelo próprio conhecimento musical + seu histórico, e o script só
busca e adiciona as faixas.

Se você já tinha conectado a conta antes desta versão, conecte de novo
(`setup-url`/`setup-finish`): as novas funções (capa, curtir, player) pedem
permissões extras. O comando `auth-status` mostra o que falta.

## Créditos

Funcionalidades inspiradas em
[fabioc-aloha/spotify-skill](https://github.com/fabioc-aloha/spotify-skill),
[lukegeel101/Spotify-AI-Agent](https://github.com/lukegeel101/Spotify-AI-Agent),
[zcaceres/spotify-cli](https://github.com/zcaceres/spotify-cli) e
[UffaModey/spotify-ai-agent-playlist-curator](https://github.com/UffaModey/spotify-ai-agent-playlist-curator).
O código daqui foi escrito do zero. Licença: MIT. Não é afiliado ao Spotify.
