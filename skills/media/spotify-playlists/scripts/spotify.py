#!/usr/bin/env python3
"""Ferramenta de linha de comando do Beedle para o Spotify.

Só usa a biblioteca padrão do Python (o comando `cover` usa Pillow, se houver).
Saída sempre em JSON. Códigos de saída: 0 ok, 1 argumentos, 2 autenticação,
3 erro da API do Spotify, 4 rede.

Em qualquer lugar que pede <playlist> pode ir: ID, URI, link ou o NOME da
playlist. Músicas pelo stdin: uma por linha, "Artista - Título" ou URI/link.
Rode `spotify.py -h` ou `spotify.py <comando> -h` para ver as opções.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import secrets
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = [
    "user-read-private",
    "user-top-read",
    "user-library-read",
    "user-library-modify",
    "user-follow-read",
    "user-follow-modify",
    "user-read-recently-played",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "ugc-image-upload",
]

# skills/<categoria>/<skill>/scripts/spotify.py -> raiz do perfil do Hermes
HOME = Path(os.environ.get("BEEDLE_HOME") or Path(__file__).resolve().parents[4])
TOKEN_FILE = HOME / "spotify_token.json"
PKCE_FILE = HOME / ".spotify_pkce.json"

E_ARGS, E_AUTH, E_API, E_REDE = 1, 2, 3, 4


class Erro(Exception):
    def __init__(self, msg, codigo=E_API, status=None):
        super().__init__(msg)
        self.codigo = codigo
        self.status = status


def saida(dados):
    print(json.dumps(dados, ensure_ascii=False, indent=2))


def normal(txt):
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt).strip().lower()


# ================================================================ configuração

def ler_env():
    valores = {}
    env_file = HOME / ".env"
    if env_file.exists():
        for linha in env_file.read_text().splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                valores[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_REDIRECT_URI"):
        if os.environ.get(k):
            valores[k] = os.environ[k]
    return valores


def config():
    env = ler_env()
    client_id = env.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise Erro(f"SPOTIFY_CLIENT_ID não configurado (coloque em {HOME / '.env'})", E_AUTH)
    return client_id, env.get("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8888/callback"


def salvar_privado(caminho, dados):
    caminho.write_text(json.dumps(dados))
    os.chmod(caminho, 0o600)


# ================================================================ HTTP

def http(metodo, url, corpo=None, form=None, token=None, bruto=None, tipo=None):
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif bruto is not None:
        data = bruto
        headers["Content-Type"] = tipo or "application/octet-stream"
    elif corpo is not None:
        data = json.dumps(corpo).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for tentativa in range(4):
        req = urllib.request.Request(url, data=data, headers=headers, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                texto = r.read().decode(errors="replace")
                try:
                    return r.status, (json.loads(texto) if texto.strip() else {})
                except ValueError:
                    return r.status, {"texto": texto[:200]}
        except urllib.error.HTTPError as e:
            texto = e.read().decode(errors="replace")
            if e.code == 429 and tentativa < 3:
                time.sleep(min(int(e.headers.get("Retry-After", "2") or 2), 30))
                continue
            if e.code in (500, 502, 503) and tentativa < 2:
                time.sleep(1 + tentativa)
                continue
            try:
                detalhe = json.loads(texto)
                detalhe = detalhe.get("error", detalhe)
                if isinstance(detalhe, dict):
                    detalhe = detalhe.get("message") or detalhe
            except ValueError:
                detalhe = texto[:300]
            return e.code, {"erro": detalhe}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if tentativa < 2:
                time.sleep(1 + tentativa)
                continue
            raise Erro(f"Falha de rede ao falar com o Spotify: {e}", E_REDE)
    return 429, {"erro": "limite de requisições do Spotify"}


# ================================================================ autenticação

def setup_url():
    client_id, redirect = config()
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    salvar_privado(PKCE_FILE, {"verifier": verifier, "state": state})
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect,
        "code_challenge_method": "S256", "code_challenge": challenge,
        "scope": " ".join(SCOPES), "state": state,
    })
    return {
        "link": url,
        "instrucoes": (
            "Abra o link, faça login e aceite. O navegador vai para um endereço "
            f"que começa com {redirect} e mostra erro de página — isso é normal. "
            "Copie o endereço inteiro da barra do navegador e envie de volta."
        ),
    }


def setup_finish(url_retorno):
    client_id, redirect = config()
    if not PKCE_FILE.exists():
        raise Erro("Rode setup-url primeiro.", E_AUTH)
    pkce = json.loads(PKCE_FILE.read_text())
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url_retorno.strip()).query)
    if "error" in params:
        raise Erro(f"Spotify recusou: {params['error'][0]}", E_AUTH)
    if params.get("state", [None])[0] != pkce["state"]:
        raise Erro("Link não corresponde ao último setup-url. Gere um novo link.", E_AUTH)
    code = params.get("code", [None])[0]
    if not code:
        raise Erro("Não encontrei o 'code' no endereço enviado.", E_AUTH)
    status, dados = http("POST", TOKEN_URL, form={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": client_id, "code_verifier": pkce["verifier"],
    })
    if status != 200:
        raise Erro(f"Falha ao obter token: {dados}", E_AUTH)
    dados["expires_at"] = time.time() + dados.get("expires_in", 3600) - 60
    salvar_privado(TOKEN_FILE, dados)
    PKCE_FILE.unlink(missing_ok=True)
    _, eu = api("GET", "/me")
    return {"ok": True, "conta": eu.get("display_name") or eu.get("id")}


def token_valido():
    if not TOKEN_FILE.exists():
        raise Erro("Spotify não conectado. Rode: setup-url e depois setup-finish.", E_AUTH)
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    client_id, _ = config()
    status, novo = http("POST", TOKEN_URL, form={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        "client_id": client_id,
    })
    if status != 200:
        raise Erro(f"Não consegui renovar o acesso; refaça o setup. Detalhe: {novo}", E_AUTH)
    tok["access_token"] = novo["access_token"]
    tok["refresh_token"] = novo.get("refresh_token", tok["refresh_token"])
    tok["scope"] = novo.get("scope", tok.get("scope"))
    tok["expires_at"] = time.time() + novo.get("expires_in", 3600) - 60
    salvar_privado(TOKEN_FILE, tok)
    return tok["access_token"]


def api(metodo, caminho, corpo=None, bruto=None, tipo=None, params=None):
    url = caminho if caminho.startswith("http") else API + caminho
    if params:
        params = {k: v for k, v in params.items() if v is not None}
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    status, dados = http(metodo, url, corpo=corpo, bruto=bruto, tipo=tipo, token=token_valido())
    if status >= 400:
        msg = dados.get("erro", dados)
        dica = ""
        if status == 401:
            dica = " (acesso expirado/revogado: refaça setup-url/setup-finish)"
        elif status == 403:
            dica = (" (sem permissão: a conta precisa estar em User Management do app, "
                    "o recurso pode exigir Premium, ou falta escopo — rode auth-status)")
        elif status == 404 and "/me/player" in caminho:
            dica = " (nenhum aparelho ativo: abra o Spotify em algum aparelho)"
        raise Erro(f"{metodo} {caminho.split('?')[0]} -> HTTP {status}: {msg}{dica}",
                   E_AUTH if status == 401 else E_API, status)
    return status, dados


def com_reserva(novo, antigo):
    """Tenta o endpoint novo (2026); se não existir, usa o antigo."""
    try:
        return novo()
    except Erro as e:
        if e.status not in (404, 405, 410):
            raise
        return antigo()


def paginar(caminho, chave=None, maximo=10_000, params=None):
    """Junta todas as páginas de uma listagem do Spotify."""
    itens = []
    _, r = api("GET", caminho, params=params)
    while True:
        bloco = r.get(chave, r) if chave else r
        itens += bloco.get("items", [])
        prox = bloco.get("next")
        if not prox or len(itens) >= maximo:
            return itens[:maximo]
        _, r = api("GET", prox)


# ================================================================ formatação

def faixa(t):
    if not t:
        return None
    alb = t.get("album") or {}
    return {
        "titulo": t.get("name"),
        "artistas": ", ".join(a["name"] for a in t.get("artists", [])),
        "album": alb.get("name"),
        "ano": (alb.get("release_date") or "")[:4] or None,
        "duracao": mmss(t.get("duration_ms")),
        "uri": t.get("uri"),
    }


def mmss(ms):
    if not ms:
        return None
    s = int(ms) // 1000
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def item_faixa(item):
    return item.get("track") or item.get("item")


def resumo_playlist(x):
    return {"nome": x.get("name"), "id": x.get("id"),
            "musicas": ((x.get("items") or x.get("tracks")) or {}).get("total"),
            "dono": (x.get("owner") or {}).get("display_name"),
            "publica": x.get("public"), "colaborativa": x.get("collaborative")}


# ================================================================ resolução

ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
URI_RE = re.compile(
    r"(?:spotify:(track|album|artist|playlist):|open\.spotify\.com/(?:intl-[a-z-]+/)?(track|album|artist|playlist)/)"
    r"([A-Za-z0-9]{22})")


def ref(valor, tipo):
    """Extrai o ID se 'valor' for URI/link/ID do tipo pedido; senão None."""
    m = URI_RE.search(valor or "")
    if m and (m.group(1) or m.group(2)) == tipo:
        return m.group(3)
    v = (valor or "").strip()
    return v if ID_RE.match(v) else None


_minhas_playlists = None


def minhas_playlists():
    global _minhas_playlists
    if _minhas_playlists is None:
        _minhas_playlists = paginar("/me/playlists", params={"limit": 50})
    return _minhas_playlists


def playlist_id(valor):
    """Aceita ID, URI, link ou nome (procura nas playlists do usuário)."""
    pid = ref(valor, "playlist")
    if pid:
        return pid
    alvo = normal(valor)
    todas = [p for p in minhas_playlists() if p]
    exatas = [p for p in todas if normal(p.get("name")) == alvo]
    parecidas = exatas or [p for p in todas if alvo in normal(p.get("name"))]
    if len(parecidas) == 1:
        return parecidas[0]["id"]
    if not parecidas:
        raise Erro(f"Não achei playlist chamada '{valor}'. Use `playlists` para ver os nomes.", E_ARGS)
    raise Erro("Mais de uma playlist com esse nome; use o id: " + json.dumps(
        [{"nome": p["name"], "id": p["id"]} for p in parecidas[:10]], ensure_ascii=False), E_ARGS)


def buscar(q, tipo="track", limite=5):
    _, r = api("GET", "/search", params={"q": q, "type": tipo, "limit": limite})
    return (r.get(tipo + "s") or {}).get("items") or []


def achar_faixa(texto):
    """'Artista - Título' / URI / texto livre -> objeto de faixa (ou None)."""
    tid = ref(texto, "track")
    if tid:
        _, t = api("GET", f"/tracks/{tid}")
        return t
    if " - " in texto:
        artista, titulo = (s.strip() for s in texto.split(" - ", 1))
        itens = buscar(f'track:"{titulo}" artist:"{artista}"')
        # prefere a faixa cujo artista bate de verdade
        for t in itens:
            if any(normal(artista) in normal(a["name"]) or normal(a["name"]) in normal(artista)
                   for a in t.get("artists", [])):
                return t
        itens = itens or buscar(f"{artista} {titulo}")
        return itens[0] if itens else None
    itens = buscar(texto)
    return itens[0] if itens else None


def resolver(linhas):
    """Lista de pedidos -> (faixas achadas sem repetição, pedidos não achados)."""
    achadas, faltando, vistas = [], [], set()
    for linha in linhas:
        linha = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", linha).strip()
        if not linha or linha.startswith("#"):
            continue
        m = URI_RE.search(linha)
        if m and (m.group(1) or m.group(2)) == "track":
            uri, info = f"spotify:track:{m.group(3)}", {}
        else:
            t = achar_faixa(linha)
            if not t:
                faltando.append(linha)
                continue
            uri, info = t["uri"], faixa(t)
        if uri not in vistas:
            vistas.add(uri)
            achadas.append({"pedido": linha, "uri": uri, **info})
    return achadas, faltando


def ler_stdin():
    if sys.stdin.isatty():
        raise Erro("Envie as músicas pelo stdin, uma por linha (Artista - Título).", E_ARGS)
    return sys.stdin.read().splitlines()


def nome_faixa(x):
    return f"{x['artistas']} - {x['titulo']}" if x.get("titulo") else x["uri"]


# ================================================================ playlists

def itens_playlist(pid):
    return com_reserva(
        lambda: paginar(f"/playlists/{pid}/items", params={"limit": 100}),
        lambda: paginar(f"/playlists/{pid}/tracks", params={"limit": 100}))


def adicionar(pid, uris, posicao=None):
    for i in range(0, len(uris), 100):
        corpo = {"uris": uris[i:i + 100]}
        if posicao is not None:
            corpo["position"] = posicao + i
        com_reserva(lambda: api("POST", f"/playlists/{pid}/items", corpo),
                    lambda: api("POST", f"/playlists/{pid}/tracks", corpo))


def substituir(pid, uris):
    """Troca todo o conteúdo da playlist por 'uris', nessa ordem."""
    if any(u.startswith("spotify:local:") for u in uris):
        raise Erro("A playlist tem arquivos locais; o Spotify não deixa regravá-los.", E_ARGS)
    primeiro = {"uris": uris[:100]}
    com_reserva(lambda: api("PUT", f"/playlists/{pid}/items", primeiro),
                lambda: api("PUT", f"/playlists/{pid}/tracks", primeiro))
    if len(uris) > 100:
        adicionar(pid, uris[100:])


def remover(pid, uris):
    lista = [{"uri": u} for u in uris]
    for i in range(0, len(lista), 100):
        bloco = lista[i:i + 100]
        com_reserva(lambda: api("DELETE", f"/playlists/{pid}/items", {"items": bloco}),
                    lambda: api("DELETE", f"/playlists/{pid}/tracks", {"tracks": bloco}))


def criar_playlist(nome, descricao="", publica=False, colaborativa=False):
    corpo = {"name": nome, "description": descricao, "public": publica and not colaborativa}
    if colaborativa:
        corpo["collaborative"] = True

    def antigo():
        _, eu = api("GET", "/me")
        return api("POST", f"/users/{eu['id']}/playlists", corpo)
    _, pl = com_reserva(lambda: api("POST", "/me/playlists", corpo), antigo)
    return pl


# ================================================================ capa

def gerar_capa(titulo, subtitulo="", cores=None, emoji=None):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise Erro("Para gerar capas instale o Pillow: pip install pillow "
                   "(ou passe --image com uma imagem pronta).", E_ARGS)
    lado = 640
    cores = cores or ["#1DB954", "#191414"]
    rgb = [tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) for c in cores[:2]]
    if len(rgb) == 1:
        rgb.append(tuple(max(0, v - 120) for v in rgb[0]))
    img = Image.new("RGB", (lado, lado))
    px = img.load()
    for y in range(lado):
        for x in range(lado):
            f = (x + y) / (2 * lado - 2)
            px[x, y] = tuple(int(rgb[0][i] * (1 - f) + rgb[1][i] * f) for i in range(3))
    d = ImageDraw.Draw(img)

    def fonte(tam, negrito=True):
        nomes = ["DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf",
                 "LiberationSans-Bold.ttf" if negrito else "LiberationSans-Regular.ttf"]
        for base in ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
                     "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF", "/Library/Fonts"]:
            for n in nomes:
                p = Path(base) / n
                if p.exists():
                    return ImageFont.truetype(str(p), tam)
        try:
            return ImageFont.load_default(size=tam)
        except TypeError:
            return ImageFont.load_default()

    def quebrar(texto, f, largura):
        linhas, atual = [], ""
        for palavra in texto.split():
            teste = (atual + " " + palavra).strip()
            if d.textlength(teste, font=f) <= largura or not atual:
                atual = teste
            else:
                linhas.append(atual)
                atual = palavra
        return linhas + ([atual] if atual else [])

    # contraste: texto claro em fundo escuro e vice-versa
    lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in rgb) / (255 * len(rgb))
    cor_txt = (20, 20, 20) if lum > 0.6 else (255, 255, 255)
    margem = 56
    for tam in range(110, 39, -6):
        f = fonte(tam)
        linhas = quebrar(titulo.upper(), f, lado - 2 * margem)
        if len(linhas) <= 4 and all(d.textlength(l, font=f) <= lado - 2 * margem for l in linhas):
            break
    y = lado - margem - len(linhas) * int(tam * 1.08) - (50 if subtitulo else 0)
    for l in linhas:
        d.text((margem, y), l, font=f, fill=cor_txt)
        y += int(tam * 1.08)
    if subtitulo:
        d.text((margem, y + 12), subtitulo, font=fonte(30, False), fill=cor_txt)
    d.text((margem, margem - 10), "♪ BEEDLE", font=fonte(26), fill=cor_txt)
    return img


def jpeg_ate_256k(img):
    img = img.convert("RGB")
    for q in (92, 85, 75, 65, 55, 45):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        b64 = base64.b64encode(buf.getvalue())
        if len(b64) <= 256 * 1024:
            return b64
    img = img.resize((480, 480))
    return jpeg_ate_256k(img)


# ================================================================ comandos

def c_setup_url(a): return setup_url()
def c_setup_finish(a): return setup_finish(a.url)


def c_auth_status(a):
    if not TOKEN_FILE.exists():
        return {"conectado": False}
    tok = json.loads(TOKEN_FILE.read_text())
    _, eu = api("GET", "/me")
    concedidos = set((tok.get("scope") or "").split())
    faltando = [s for s in SCOPES if s not in concedidos] if concedidos else []
    return {"conectado": True, "conta": eu.get("display_name") or eu.get("id"),
            "plano": eu.get("product"), "escopos_faltando": faltando,
            "dica": "refaça setup-url/setup-finish para liberar os escopos faltando" if faltando else None}


def c_logout(a):
    TOKEN_FILE.unlink(missing_ok=True)
    return {"ok": True}


def c_me(a):
    _, r = api("GET", "/me")
    return {"nome": r.get("display_name"), "id": r.get("id"), "pais": r.get("country"),
            "plano": r.get("product")}


def c_top_tracks(a):
    _, r = api("GET", "/me/top/tracks", params={"time_range": a.range, "limit": lim(a.limit)})
    return [faixa(t) for t in r.get("items", [])]


def c_top_artists(a):
    _, r = api("GET", "/me/top/artists", params={"time_range": a.range, "limit": lim(a.limit)})
    return [{"artista": x.get("name"), "generos": x.get("genres", []), "uri": x.get("uri")}
            for x in r.get("items", [])]


def c_saved(a):
    return [faixa(i.get("track")) for i in paginar("/me/tracks", params={"limit": 50}, maximo=a.limit)]


def c_recent(a):
    _, r = api("GET", "/me/player/recently-played", params={"limit": lim(a.limit)})
    return [{**faixa(i.get("track")), "tocada_em": i.get("played_at")} for i in r.get("items", [])]


def c_following(a):
    _, r = api("GET", "/me/following", params={"type": "artist", "limit": lim(a.limit)})
    return [{"artista": x.get("name"), "generos": x.get("genres", []), "uri": x.get("uri")}
            for x in (r.get("artists") or {}).get("items", [])]


def c_search(a):
    itens = buscar(a.q, a.type, lim(a.limit, 10))
    if a.type == "track":
        return [faixa(t) for t in itens]
    if a.type == "artist":
        return [{"artista": x.get("name"), "generos": x.get("genres", []), "uri": x.get("uri")} for x in itens]
    if a.type == "album":
        return [{"album": x.get("name"), "artistas": ", ".join(y["name"] for y in x.get("artists", [])),
                 "ano": (x.get("release_date") or "")[:4], "uri": x.get("uri")} for x in itens]
    return [resumo_playlist(x) for x in itens if x]


def achar_artista(valor):
    aid = ref(valor, "artist")
    if aid:
        _, x = api("GET", f"/artists/{aid}")
        return x
    itens = buscar(valor, "artist", 5)
    if not itens:
        raise Erro(f"Artista não encontrado: {valor}", E_ARGS)
    exato = [x for x in itens if normal(x["name"]) == normal(valor)]
    return (exato or itens)[0]


def c_artist_top(a):
    art = achar_artista(a.artista)
    try:
        _, r = api("GET", f"/artists/{art['id']}/top-tracks", params={"market": "from_token"})
        faixas = r.get("tracks", [])
    except Erro as e:
        if e.status not in (403, 404, 410):
            raise
        faixas = []
    if not faixas:  # endpoint indisponível: usa busca filtrando pelo artista
        faixas = [t for t in buscar(f'artist:"{art["name"]}"', "track", 10)
                  if any(x["id"] == art["id"] for x in t.get("artists", []))]
    return {"artista": art["name"], "uri": art["uri"], "musicas": [faixa(t) for t in faixas[:a.limit]]}


def c_album_tracks(a):
    alid = ref(a.album, "album")
    if not alid:
        itens = buscar(a.album, "album", 5)
        if not itens:
            raise Erro(f"Álbum não encontrado: {a.album}", E_ARGS)
        alid = itens[0]["id"]
    _, alb = api("GET", f"/albums/{alid}")
    faixas = alb.get("tracks", {}).get("items", [])
    for t in faixas:
        t.setdefault("album", {"name": alb.get("name"), "release_date": alb.get("release_date")})
    return {"album": alb.get("name"), "artistas": ", ".join(x["name"] for x in alb.get("artists", [])),
            "ano": (alb.get("release_date") or "")[:4], "musicas": [faixa(t) for t in faixas]}


def c_playlists(a):
    return [resumo_playlist(x) for x in minhas_playlists()[:a.limit] if x]


def c_show(a):
    pid = playlist_id(a.playlist)
    _, info = api("GET", f"/playlists/{pid}", params={"fields": "name,description,public,collaborative,owner(display_name)"})
    musicas = []
    for n, i in enumerate(itens_playlist(pid)):
        f = faixa(item_faixa(i))
        if f:
            f["posicao"] = n
            musicas.append(f)
    return {"nome": info.get("name"), "id": pid, "descricao": info.get("description"),
            "publica": info.get("public"), "colaborativa": info.get("collaborative"),
            "total": len(musicas), "musicas": musicas}


def c_stats(a):
    pid = playlist_id(a.playlist)
    faixas = [item_faixa(i) for i in itens_playlist(pid)]
    faixas = [t for t in faixas if t]
    artistas, decadas, uris = {}, {}, {}
    for t in faixas:
        for x in t.get("artists", []):
            artistas[x["name"]] = artistas.get(x["name"], 0) + 1
        ano = ((t.get("album") or {}).get("release_date") or "")[:4]
        if ano.isdigit():
            dec = f"{ano[:3]}0s"
            decadas[dec] = decadas.get(dec, 0) + 1
        uris[t["uri"]] = uris.get(t["uri"], 0) + 1
    total_ms = sum(t.get("duration_ms") or 0 for t in faixas)
    return {
        "musicas": len(faixas), "duracao_total": mmss(total_ms),
        "artistas_diferentes": len(artistas),
        "artistas_mais_presentes": sorted(artistas.items(), key=lambda kv: -kv[1])[:10],
        "decadas": dict(sorted(decadas.items())),
        "explicitas": sum(1 for t in faixas if t.get("explicit")),
        "repetidas": {u: n for u, n in uris.items() if n > 1},
    }


def c_build(a):
    achadas, faltando = resolver(ler_stdin())
    if not achadas:
        raise Erro(f"Nenhuma música encontrada. Não achei: {faltando}", E_ARGS)
    pl = criar_playlist(a.name, a.description, a.public, a.collaborative)
    adicionar(pl["id"], [x["uri"] for x in achadas])
    return {"ok": True, "playlist": pl.get("name"), "id": pl["id"],
            "link": (pl.get("external_urls") or {}).get("spotify"),
            "adicionadas": len(achadas), "nao_encontradas": faltando,
            "musicas": [nome_faixa(x) for x in achadas]}


def c_add(a):
    pid = playlist_id(a.playlist)
    achadas, faltando = resolver(ler_stdin())
    if a.skip_existing and achadas:
        existentes = {(item_faixa(i) or {}).get("uri") for i in itens_playlist(pid)}
        puladas = [nome_faixa(x) for x in achadas if x["uri"] in existentes]
        achadas = [x for x in achadas if x["uri"] not in existentes]
    else:
        puladas = []
    if achadas:
        adicionar(pid, [x["uri"] for x in achadas], a.position)
    return {"ok": True, "adicionadas": len(achadas), "musicas": [nome_faixa(x) for x in achadas],
            "ja_estavam": puladas, "nao_encontradas": faltando}


def c_add_current(a):
    st, r = api("GET", "/me/player/currently-playing")
    t = r.get("item") if r else None
    if not t or r.get("currently_playing_type") not in (None, "track"):
        raise Erro("Nada tocando agora (ou é um podcast).", E_ARGS)
    pid = playlist_id(a.playlist)
    adicionar(pid, [t["uri"]])
    return {"ok": True, "adicionada": nome_faixa({**faixa(t)})}


def c_remove(a):
    pid = playlist_id(a.playlist)
    uris = []
    for u in a.musicas:
        tid = ref(u, "track")
        if tid:
            uris.append(f"spotify:track:{tid}")
        else:
            t = achar_faixa(u)
            if not t:
                raise Erro(f"Não achei a música: {u}", E_ARGS)
            uris.append(t["uri"])
    remover(pid, uris)
    return {"ok": True, "removidas": len(uris), "obs": "todas as ocorrências dessas músicas saíram"}


def c_move(a):
    pid = playlist_id(a.playlist)
    para = a.para + a.count if a.para > a.de else a.para
    corpo = {"range_start": a.de, "insert_before": para, "range_length": a.count}
    com_reserva(lambda: api("PUT", f"/playlists/{pid}/items", corpo),
                lambda: api("PUT", f"/playlists/{pid}/tracks", corpo))
    return {"ok": True}


def c_replace(a):
    pid = playlist_id(a.playlist)
    achadas, faltando = resolver(ler_stdin())
    if not achadas:
        raise Erro("Lista vazia; nada foi alterado.", E_ARGS)
    substituir(pid, [x["uri"] for x in achadas])
    return {"ok": True, "total": len(achadas), "nao_encontradas": faltando}


def c_dedupe(a):
    pid = playlist_id(a.playlist)
    faixas = [item_faixa(i) for i in itens_playlist(pid)]
    vistas, unicas, removidas = set(), [], []
    for t in faixas:
        if not t:
            continue
        chave = t["uri"] if a.exact else (normal(t.get("name")), normal((t.get("artists") or [{}])[0].get("name")))
        if chave in vistas:
            removidas.append(nome_faixa(faixa(t)))
        else:
            vistas.add(chave)
            unicas.append(t["uri"])
    if removidas and not a.dry_run:
        substituir(pid, unicas)
    return {"ok": True, "repetidas": removidas, "aplicado": bool(removidas) and not a.dry_run}


def c_edit(a):
    pid = playlist_id(a.playlist)
    corpo = {k: v for k, v in {"name": a.name, "description": a.description,
                                "public": a.publica, "collaborative": a.colab}.items() if v is not None}
    if corpo.get("collaborative"):
        corpo["public"] = False
    if not corpo:
        raise Erro("Nada para alterar.", E_ARGS)
    api("PUT", f"/playlists/{pid}", corpo)
    return {"ok": True, "alterado": corpo}


def c_delete(a):
    pid = playlist_id(a.playlist)
    api("DELETE", f"/playlists/{pid}/followers")
    return {"ok": True, "obs": "playlist removida da sua biblioteca (o Spotify não apaga de vez)"}


def c_cover(a):
    pid = playlist_id(a.playlist)
    if a.image:
        from_path = Path(a.image)
        if not from_path.exists():
            raise Erro(f"Imagem não encontrada: {a.image}", E_ARGS)
        try:
            from PIL import Image
            b64 = jpeg_ate_256k(Image.open(from_path))
        except ImportError:
            dados = from_path.read_bytes()
            if not from_path.suffix.lower() in (".jpg", ".jpeg"):
                raise Erro("Sem Pillow, só aceito imagem .jpg", E_ARGS)
            b64 = base64.b64encode(dados)
            if len(b64) > 256 * 1024:
                raise Erro("Imagem grande demais (máx. ~190 KB em JPEG). Instale o Pillow.", E_ARGS)
    else:
        if not a.title:
            _, info = api("GET", f"/playlists/{pid}", params={"fields": "name"})
            a.title = info.get("name", "Playlist")
        cores = [c.strip() for c in a.colors.split(",")] if a.colors else None
        img = gerar_capa(a.title, a.subtitle or "", cores)
        b64 = jpeg_ate_256k(img)
        if a.save:
            img.save(a.save)
    api("PUT", f"/playlists/{pid}/images", bruto=b64, tipo="image/jpeg")
    return {"ok": True, "obs": "a capa pode levar alguns segundos para aparecer"}


def c_export(a):
    eu = c_me(a)
    dados = {"exportado_em": datetime.now().isoformat(timespec="seconds"), "conta": eu,
             "top_musicas": c_top_tracks(argparse.Namespace(range="medium_term", limit=50)),
             "top_artistas": c_top_artists(argparse.Namespace(range="medium_term", limit=50)),
             "curtidas": c_saved(argparse.Namespace(limit=a.saved)),
             "playlists": []}
    for p in minhas_playlists():
        if not p:
            continue
        reg = resumo_playlist(p)
        if (p.get("owner") or {}).get("id") == eu["id"]:
            reg["musicas_lista"] = [faixa(item_faixa(i)) for i in itens_playlist(p["id"]) if item_faixa(i)]
        dados["playlists"].append(reg)
    destino = Path(a.out) if a.out else HOME / "exports" / f"spotify-{datetime.now():%Y%m%d-%H%M}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
    return {"ok": True, "arquivo": str(destino), "playlists": len(dados["playlists"])}


# ---- biblioteca

def uris_de(valores, tipo):
    uris = []
    for v in valores:
        rid = ref(v, tipo)
        if not rid:
            if tipo == "track":
                t = achar_faixa(v)
                rid = t["id"] if t else None
            else:
                rid = achar_artista(v)["id"]
        if not rid:
            raise Erro(f"Não achei: {v}", E_ARGS)
        uris.append(f"spotify:{tipo}:{rid}")
    return uris


def biblioteca(metodo, uris, tipo):
    ids = ",".join(u.split(":")[-1] for u in uris)
    antigo = (lambda: api(metodo, "/me/tracks", params={"ids": ids})) if tipo == "track" else \
             (lambda: api(metodo, "/me/following", params={"type": "artist", "ids": ids}))
    com_reserva(lambda: api(metodo, "/me/library", params={"uris": ",".join(uris)}), antigo)


def c_like(a):
    uris = uris_de(a.musicas, "track") if a.musicas else [_tocando()["uri"]]
    biblioteca("PUT", uris, "track")
    return {"ok": True, "curtidas": uris}


def c_unlike(a):
    uris = uris_de(a.musicas, "track")
    biblioteca("DELETE", uris, "track")
    return {"ok": True, "descurtidas": uris}


def c_follow(a):
    uris = uris_de(a.artistas, "artist")
    biblioteca("PUT", uris, "artist")
    return {"ok": True, "seguindo": uris}


def c_unfollow(a):
    uris = uris_de(a.artistas, "artist")
    biblioteca("DELETE", uris, "artist")
    return {"ok": True, "deixou_de_seguir": uris}


# ---- player (a maioria exige Spotify Premium)

def _tocando():
    st, r = api("GET", "/me/player/currently-playing")
    if not r or not r.get("item"):
        raise Erro("Nada tocando agora.", E_ARGS)
    return r["item"]


def c_now(a):
    st, r = api("GET", "/me/player")
    if not r:
        return {"tocando": False}
    t = r.get("item")
    return {"tocando": r.get("is_playing"), "musica": faixa(t) if t and t.get("type") == "track" else (t or {}).get("name"),
            "progresso": mmss(r.get("progress_ms")), "aparelho": (r.get("device") or {}).get("name"),
            "volume": (r.get("device") or {}).get("volume_percent"),
            "aleatorio": r.get("shuffle_state"), "repetir": r.get("repeat_state"),
            "contexto": (r.get("context") or {}).get("uri")}


def c_devices(a):
    _, r = api("GET", "/me/player/devices")
    return [{"nome": d.get("name"), "id": d.get("id"), "tipo": d.get("type"),
             "ativo": d.get("is_active"), "volume": d.get("volume_percent")} for d in r.get("devices", [])]


def aparelho(valor):
    if not valor:
        return None
    for d in c_devices(None):
        if valor in (d["id"],) or normal(valor) in normal(d["nome"]):
            return d["id"]
    raise Erro(f"Aparelho não encontrado: {valor}. Veja `devices`.", E_ARGS)


def c_play(a):
    corpo = None
    if a.oque:
        alvo = a.oque
        m = URI_RE.search(alvo)
        tipo = (m.group(1) or m.group(2)) if m else a.type
        if tipo == "track":
            t = achar_faixa(alvo)
            if not t:
                raise Erro(f"Não achei: {alvo}", E_ARGS)
            corpo, nome = {"uris": [t["uri"]]}, nome_faixa(faixa(t))
        elif tipo == "playlist":
            pid = playlist_id(alvo) if not m else m.group(3)
            corpo, nome = {"context_uri": f"spotify:playlist:{pid}"}, alvo
        elif tipo == "album":
            alid = m.group(3) if m else (buscar(alvo, "album", 1) or [{}])[0].get("id")
            corpo, nome = {"context_uri": f"spotify:album:{alid}"}, alvo
        else:
            art = achar_artista(alvo)
            corpo, nome = {"context_uri": art["uri"]}, art["name"]
    api("PUT", "/me/player/play", corpo, params={"device_id": aparelho(a.device)})
    return {"ok": True, "tocando": nome if a.oque else "retomado"}


def simples(metodo, caminho, **params):
    def f(a):
        api(metodo, caminho, params={k: (v(a) if callable(v) else v) for k, v in params.items()})
        return {"ok": True}
    return f


def c_queue(a):
    t = achar_faixa(a.musica)
    if not t:
        raise Erro(f"Não achei: {a.musica}", E_ARGS)
    api("POST", "/me/player/queue", params={"uri": t["uri"]})
    return {"ok": True, "na_fila": nome_faixa(faixa(t))}


def c_queue_show(a):
    _, r = api("GET", "/me/player/queue")
    return {"agora": faixa(r.get("currently_playing")) if r.get("currently_playing") else None,
            "proximas": [faixa(t) for t in (r.get("queue") or [])[:a.limit] if t]}


def c_transfer(a):
    api("PUT", "/me/player", {"device_ids": [aparelho(a.aparelho)], "play": True})
    return {"ok": True}


def lim(n, m=50):
    return max(1, min(int(n), m))


# ================================================================ CLI

def montar_parser():
    p = argparse.ArgumentParser(prog="spotify.py", description="Spotify do Beedle")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(nome, func, ajuda):
        s = sub.add_parser(nome, help=ajuda, description=ajuda)
        s.set_defaults(func=func)
        return s

    # conta
    cmd("setup-url", c_setup_url, "gera link para conectar a conta")
    cmd("setup-finish", c_setup_finish, "conclui a conexão com o endereço de retorno").add_argument("url")
    cmd("auth-status", c_auth_status, "mostra conta conectada e permissões faltando")
    cmd("logout", c_logout, "desconecta a conta")
    cmd("me", c_me, "dados da conta")
    # gosto
    for nome, func in (("top-tracks", c_top_tracks), ("top-artists", c_top_artists)):
        s = cmd(nome, func, "mais ouvidas" if "tracks" in nome else "artistas mais ouvidos")
        s.add_argument("--range", default="medium_term", choices=["short_term", "medium_term", "long_term"])
        s.add_argument("--limit", type=int, default=20)
    cmd("saved", c_saved, "músicas curtidas").add_argument("--limit", type=int, default=50)
    cmd("recent", c_recent, "tocadas recentemente").add_argument("--limit", type=int, default=30)
    cmd("following", c_following, "artistas que você segue").add_argument("--limit", type=int, default=50)
    # descoberta
    s = cmd("search", c_search, "busca (aceita filtros: artist:, album:, year:1990-1999, genre:)")
    s.add_argument("q"); s.add_argument("--type", default="track", choices=["track", "artist", "album", "playlist"])
    s.add_argument("--limit", type=int, default=10)
    s = cmd("artist-top", c_artist_top, "músicas mais populares de um artista")
    s.add_argument("artista"); s.add_argument("--limit", type=int, default=10)
    cmd("album-tracks", c_album_tracks, "faixas de um álbum").add_argument("album")
    # playlists
    cmd("playlists", c_playlists, "suas playlists").add_argument("--limit", type=int, default=200)
    cmd("show", c_show, "músicas de uma playlist").add_argument("playlist")
    cmd("stats", c_stats, "estatísticas de uma playlist").add_argument("playlist")
    s = cmd("build", c_build, "cria playlist com as músicas do stdin")
    s.add_argument("--name", required=True); s.add_argument("--description", default="")
    s.add_argument("--public", action="store_true"); s.add_argument("--collaborative", action="store_true")
    s = cmd("add", c_add, "adiciona músicas do stdin")
    s.add_argument("playlist"); s.add_argument("--position", type=int)
    s.add_argument("--skip-existing", action="store_true", help="não adiciona o que já está lá")
    cmd("add-current", c_add_current, "adiciona a música que está tocando").add_argument("playlist")
    s = cmd("remove", c_remove, "remove músicas (URI, link ou 'Artista - Título')")
    s.add_argument("playlist"); s.add_argument("musicas", nargs="+")
    s = cmd("move", c_move, "move músicas de posição (começa em 0)")
    s.add_argument("playlist")
    s.add_argument("--from", dest="de", type=int, required=True)
    s.add_argument("--to", dest="para", type=int, required=True)
    s.add_argument("--count", type=int, default=1)
    cmd("replace", c_replace, "regrava a playlist inteira na ordem do stdin").add_argument("playlist")
    s = cmd("dedupe", c_dedupe, "remove músicas repetidas")
    s.add_argument("playlist"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--exact", action="store_true", help="só repetição do mesmo URI")
    s = cmd("edit", c_edit, "muda nome, descrição, pública/privada, colaborativa")
    s.add_argument("playlist"); s.add_argument("--name"); s.add_argument("--description")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--public", dest="publica", action="store_const", const=True)
    g.add_argument("--private", dest="publica", action="store_const", const=False)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--collaborative", dest="colab", action="store_const", const=True)
    g.add_argument("--not-collaborative", dest="colab", action="store_const", const=False)
    cmd("delete", c_delete, "tira a playlist da sua biblioteca").add_argument("playlist")
    s = cmd("cover", c_cover, "gera e envia capa (ou envia --image)")
    s.add_argument("playlist"); s.add_argument("--title"); s.add_argument("--subtitle")
    s.add_argument("--colors", help="duas cores, ex: '#ff7e5f,#2b1055'")
    s.add_argument("--image", help="usar esta imagem em vez de gerar")
    s.add_argument("--save", help="salvar também a capa gerada neste arquivo")
    s = cmd("export", c_export, "exporta seus dados (backup) para JSON")
    s.add_argument("--out"); s.add_argument("--saved", type=int, default=500)
    # biblioteca
    cmd("like", c_like, "curte músicas (sem argumentos: a que está tocando)").add_argument("musicas", nargs="*")
    cmd("unlike", c_unlike, "descurte músicas").add_argument("musicas", nargs="+")
    cmd("follow", c_follow, "segue artistas").add_argument("artistas", nargs="+")
    cmd("unfollow", c_unfollow, "deixa de seguir artistas").add_argument("artistas", nargs="+")
    # player
    cmd("now", c_now, "o que está tocando")
    cmd("devices", c_devices, "aparelhos disponíveis")
    s = cmd("play", c_play, "toca/retoma (música, playlist, álbum ou artista)")
    s.add_argument("oque", nargs="?"); s.add_argument("--type", default="track",
                                                      choices=["track", "playlist", "album", "artist"])
    s.add_argument("--device")
    cmd("pause", simples("PUT", "/me/player/pause"), "pausa")
    cmd("next", simples("POST", "/me/player/next"), "próxima")
    cmd("prev", simples("POST", "/me/player/previous"), "anterior")
    cmd("queue", c_queue, "põe música na fila").add_argument("musica")
    cmd("queue-show", c_queue_show, "mostra a fila").add_argument("--limit", type=int, default=10)
    cmd("transfer", c_transfer, "passa a tocar em outro aparelho").add_argument("aparelho")
    cmd("volume", simples("PUT", "/me/player/volume", volume_percent=lambda a: max(0, min(100, a.v))),
        "volume 0-100").add_argument("v", type=int)
    cmd("shuffle", simples("PUT", "/me/player/shuffle", state=lambda a: a.estado),
        "aleatório").add_argument("estado", choices=["true", "false"])
    cmd("repeat", simples("PUT", "/me/player/repeat", state=lambda a: a.estado),
        "repetir").add_argument("estado", choices=["track", "context", "off"])
    cmd("seek", simples("PUT", "/me/player/seek", position_ms=lambda a: a.segundos * 1000),
        "pula para o segundo X da música").add_argument("segundos", type=int)
    return p


def main(argv=None):
    global _minhas_playlists
    _minhas_playlists = None
    p = montar_parser()
    try:
        a = p.parse_args(argv)
    except SystemExit as e:
        raise Erro("Argumentos inválidos (veja -h).", E_ARGS) if e.code else e
    resultado = a.func(a)
    saida(resultado)


if __name__ == "__main__":
    try:
        main()
    except Erro as e:
        saida({"ok": False, "erro": str(e)})
        sys.exit(e.codigo)
    except SystemExit:
        raise
