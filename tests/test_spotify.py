"""Testes do spotify.py contra um Spotify falso (rede local, sem conta real).

Rodar:  python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/media/spotify-playlists/scripts"
sys.path.insert(0, str(SCRIPTS))
import spotify  # noqa: E402


def T(tid, nome, artista="Art", ano="1986", ms=200_000):
    tid = (tid * 22)[:22]
    return {"id": tid, "name": nome, "uri": f"spotify:track:{tid}", "type": "track",
            "duration_ms": ms, "explicit": False,
            "artists": [{"name": artista, "id": ("a" + artista * 22)[:22]}],
            "album": {"name": "Al", "release_date": f"{ano}-01-01"}}


CATALOGO = {
    "Tempo Perdido": T("A", "Tempo Perdido", "Legião Urbana", "1986"),
    "Epitáfio": T("B", "Epitáfio", "Titãs", "2001"),
    "Lanterna dos Afogados": T("C", "Lanterna dos Afogados", "Os Paralamas do Sucesso", "1989"),
}


class Estado:
    def __init__(self, api_antiga=False):
        self.api_antiga = api_antiga
        self.playlists = {}   # id -> {"name", "items": [track]}
        self.log = []
        self.biblioteca = []
        self.capa = None
        self.tocando = CATALOGO["Epitáfio"]


def servidor(estado):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def resp(self, code, body=None):
            b = json.dumps(body).encode() if body is not None else b""
            self.send_response(code)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def tratar(self, m):
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            n = int(self.headers.get("Content-Length") or 0)
            bruto = self.rfile.read(n)
            corpo = {}
            if self.headers.get("Content-Type") == "application/json" and bruto:
                corpo = json.loads(bruto)
            estado.log.append((m, u.path, q, corpo))
            p = u.path
            if p == "/api/token":
                return self.resp(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
                                       "scope": " ".join(spotify.SCOPES)})
            if self.headers.get("Authorization") != "Bearer AT":
                return self.resp(401, {"error": {"status": 401, "message": "auth"}})
            novo = not estado.api_antiga
            if p == "/v1/me":
                return self.resp(200, {"id": "vitor", "display_name": "Vitor", "product": "premium"})
            if p == "/v1/search":
                termo = q["q"]
                tipo = q["type"]
                if tipo == "track":
                    itens = [t for nome, t in CATALOGO.items() if nome.lower() in termo.lower()
                             or t["artists"][0]["name"].lower() in termo.lower()]
                    return self.resp(200, {"tracks": {"items": itens}})
                if tipo == "artist":
                    return self.resp(200, {"artists": {"items": [
                        {"name": "Titãs", "id": ("aTitãs" * 22)[:22], "uri": "spotify:artist:x", "genres": ["rock"]}]}})
                return self.resp(200, {tipo + "s": {"items": []}})
            if p.startswith("/v1/tracks/"):
                tid = p.rsplit("/", 1)[1]
                for t in CATALOGO.values():
                    if t["id"] == tid:
                        return self.resp(200, t)
                return self.resp(404, {"error": {"message": "no track"}})
            if p == "/v1/me/playlists":
                if m == "GET":
                    return self.resp(200, {"items": [{"id": k, "name": v["name"], "owner": {"id": "vitor"},
                                                      "items": {"total": len(v["items"])}}
                                                     for k, v in estado.playlists.items()], "next": None})
                if not novo:
                    return self.resp(404, {})
            if (p == "/v1/me/playlists" and m == "POST") or p == "/v1/users/vitor/playlists":
                pid = f"PL{len(estado.playlists) + 1}".ljust(22, "x")
                estado.playlists[pid] = {"name": corpo["name"], "items": []}
                return self.resp(201, {"id": pid, "name": corpo["name"],
                                       "external_urls": {"spotify": f"https://open.spotify.com/playlist/{pid}"}})
            partes = p.split("/")
            if len(partes) >= 4 and partes[2] == "playlists":
                pid = partes[3]
                pl = estado.playlists.get(pid)
                if pl is None:
                    return self.resp(404, {"error": {"message": "no playlist"}})
                sub = partes[4] if len(partes) > 4 else ""
                if sub in ("items", "tracks"):
                    if (sub == "items") != novo:
                        return self.resp(404, {"error": {"message": "gone"}})
                    por_uri = {t["uri"]: t for t in CATALOGO.values()}
                    if m == "GET":
                        return self.resp(200, {"items": [{"track" if not novo else "item": t} for t in pl["items"]],
                                               "next": None})
                    if m == "POST":
                        novos = [por_uri[u] for u in corpo["uris"]]
                        pos = corpo.get("position")
                        if pos is None:
                            pl["items"] += novos
                        else:
                            pl["items"][pos:pos] = novos
                        return self.resp(201, {"snapshot_id": "s"})
                    if m == "DELETE":
                        chave = "items" if novo else "tracks"
                        tirar = {x["uri"] for x in corpo[chave]}
                        pl["items"] = [t for t in pl["items"] if t["uri"] not in tirar]
                        return self.resp(200, {"snapshot_id": "s"})
                    if m == "PUT":
                        if "uris" in corpo:
                            pl["items"] = [por_uri[u] for u in corpo["uris"]]
                        else:
                            i, n, ib = corpo["range_start"], corpo["range_length"], corpo["insert_before"]
                            bloco = pl["items"][i:i + n]
                            resto = pl["items"][:i] + pl["items"][i + n:]
                            destino = ib if ib <= i else ib - n
                            pl["items"] = resto[:destino] + bloco + resto[destino:]
                        return self.resp(200, {"snapshot_id": "s"})
                if sub == "images" and m == "PUT":
                    estado.capa = bruto
                    return self.resp(202)
                if sub == "followers" and m == "DELETE":
                    del estado.playlists[pid]
                    return self.resp(200)
                if sub == "" and m == "GET":
                    return self.resp(200, {"name": pl["name"], "public": False})
                if sub == "" and m == "PUT":
                    pl.update({k: v for k, v in corpo.items() if k == "name"})
                    return self.resp(200)
            if p == "/v1/me/library" and novo:
                estado.biblioteca.append((m, q["uris"]))
                return self.resp(200)
            if p == "/v1/me/tracks" and m in ("PUT", "DELETE") and not novo:
                estado.biblioteca.append((m, q["ids"]))
                return self.resp(200)
            if p in ("/v1/me/top/tracks", "/v1/me/tracks") and m == "GET":
                itens = list(CATALOGO.values())
                return self.resp(200, {"items": itens if "top" in p else [{"track": t} for t in itens],
                                       "next": None})
            if p == "/v1/me/top/artists":
                return self.resp(200, {"items": [{"name": "Titãs", "genres": ["rock"], "uri": "spotify:artist:x"}]})
            if p == "/v1/me/player/currently-playing":
                return self.resp(200, {"item": estado.tocando, "currently_playing_type": "track"})
            if p == "/v1/me/player":
                return self.resp(200, {"is_playing": True, "item": estado.tocando, "progress_ms": 61000,
                                       "device": {"name": "Celular", "volume_percent": 50}})
            if p == "/v1/me/player/devices":
                return self.resp(200, {"devices": [{"id": "dev1", "name": "Celular", "is_active": True}]})
            if p.startswith("/v1/me/player/"):
                return self.resp(204)
            return self.resp(404, {"error": {"message": f"inesperado {m} {p}"}})

        do_GET = lambda s: s.tratar("GET")      # noqa: E731
        do_POST = lambda s: s.tratar("POST")    # noqa: E731
        do_PUT = lambda s: s.tratar("PUT")      # noqa: E731
        do_DELETE = lambda s: s.tratar("DELETE")  # noqa: E731

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Base(unittest.TestCase):
    api_antiga = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        (home / ".env").write_text("SPOTIFY_CLIENT_ID=abc\n")
        self.estado = Estado(self.api_antiga)
        self.srv = servidor(self.estado)
        base = f"http://127.0.0.1:{self.srv.server_port}"
        self.orig = (spotify.API, spotify.TOKEN_URL, spotify.HOME, spotify.TOKEN_FILE, spotify.PKCE_FILE)
        spotify.API, spotify.TOKEN_URL = base + "/v1", base + "/api/token"
        spotify.HOME, spotify.TOKEN_FILE, spotify.PKCE_FILE = home, home / "spotify_token.json", home / ".pkce"

    def tearDown(self):
        self.srv.shutdown()
        spotify.API, spotify.TOKEN_URL, spotify.HOME, spotify.TOKEN_FILE, spotify.PKCE_FILE = self.orig
        self.tmp.cleanup()

    def run_cli(self, *args, stdin=None):
        out = io.StringIO()
        antigo = sys.stdin
        sys.stdin = io.StringIO(stdin) if stdin is not None else antigo
        try:
            with contextlib.redirect_stdout(out):
                spotify.main(list(args))
        finally:
            sys.stdin = antigo
        return json.loads(out.getvalue())

    def conectar(self):
        link = self.run_cli("setup-url")["link"]
        state = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)["state"][0]
        return self.run_cli("setup-finish", f"http://127.0.0.1:8888/callback?code=X&state={state}")

    def criar(self, nome="Teste"):
        return self.run_cli("build", "--name", nome, stdin=(
            "1. Legião Urbana - Tempo Perdido\n- Titãs - Epitáfio\nFoo - Inexistente\n"
            "Legião Urbana - Tempo Perdido\n"))


class TestAuth(Base):
    def test_fluxo(self):
        with self.assertRaises(spotify.Erro) as e:
            self.run_cli("me")
        self.assertEqual(e.exception.codigo, spotify.E_AUTH)
        link = self.run_cli("setup-url")["link"]
        self.assertIn("ugc-image-upload", urllib.parse.unquote(link))
        with self.assertRaises(spotify.Erro):
            self.run_cli("setup-finish", "http://127.0.0.1:8888/callback?code=X&state=errado")
        self.assertEqual(self.conectar()["conta"], "Vitor")
        self.assertEqual(oct(os.stat(spotify.TOKEN_FILE).st_mode & 0o777), "0o600")
        self.assertEqual(self.run_cli("auth-status")["escopos_faltando"], [])

    def test_argumento_invalido(self):
        with self.assertRaises(spotify.Erro) as e, contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("comando-que-nao-existe")
        self.assertEqual(e.exception.codigo, spotify.E_ARGS)


class TestPlaylists(Base):
    def setUp(self):
        super().setUp()
        self.conectar()

    def test_build_e_edicao(self):
        r = self.criar()
        self.assertEqual(r["adicionadas"], 2)                 # repetida removida
        self.assertEqual(r["nao_encontradas"], ["Foo - Inexistente"])
        # por nome em vez de id
        r = self.run_cli("add", "teste", "--skip-existing", "--position", "0",
                         stdin="Titãs - Epitáfio\nOs Paralamas do Sucesso - Lanterna dos Afogados\n")
        self.assertEqual(r["adicionadas"], 1)
        self.assertEqual(len(r["ja_estavam"]), 1)
        show = self.run_cli("show", "Teste")
        self.assertEqual([m["titulo"] for m in show["musicas"]],
                         ["Lanterna dos Afogados", "Tempo Perdido", "Epitáfio"])
        self.run_cli("move", "Teste", "--from", "0", "--to", "2")
        show = self.run_cli("show", "Teste")
        self.assertEqual(show["musicas"][2]["titulo"], "Lanterna dos Afogados")
        self.run_cli("remove", "Teste", "Titãs - Epitáfio")
        self.assertEqual(self.run_cli("show", "Teste")["total"], 2)
        st = self.run_cli("stats", "Teste")
        self.assertEqual(st["musicas"], 2)
        self.assertEqual(st["decadas"], {"1980s": 2})

    def test_dedupe_e_replace(self):
        self.criar()
        pid = next(iter(self.estado.playlists))
        self.estado.playlists[pid]["items"].append(CATALOGO["Tempo Perdido"])
        r = self.run_cli("dedupe", "Teste", "--dry-run")
        self.assertEqual(len(r["repetidas"]), 1)
        self.assertFalse(r["aplicado"])
        self.run_cli("dedupe", "Teste")
        self.assertEqual(len(self.estado.playlists[pid]["items"]), 2)
        self.run_cli("replace", "Teste", stdin="Os Paralamas do Sucesso - Lanterna dos Afogados\n")
        self.assertEqual([t["name"] for t in self.estado.playlists[pid]["items"]], ["Lanterna dos Afogados"])

    def test_nome_inexistente(self):
        with self.assertRaises(spotify.Erro) as e:
            self.run_cli("show", "Nao Existe")
        self.assertEqual(e.exception.codigo, spotify.E_ARGS)

    def test_add_current_like_delete(self):
        self.criar()
        self.run_cli("add-current", "Teste")
        self.assertEqual(self.run_cli("show", "Teste")["total"], 3)
        self.run_cli("like")
        self.assertEqual(self.estado.biblioteca[-1][0], "PUT")
        self.run_cli("delete", "Teste")
        self.assertEqual(self.estado.playlists, {})

    def test_capa(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow não instalado")
        self.criar()
        self.run_cli("cover", "Teste", "--title", "Estrada ao Entardecer", "--colors", "#ff7e5f,#2b1055")
        self.assertIsNotNone(self.estado.capa)
        self.assertLessEqual(len(self.estado.capa), 256 * 1024)
        import base64
        self.assertTrue(base64.b64decode(self.estado.capa).startswith(b"\xff\xd8"))  # JPEG

    def test_player(self):
        self.assertTrue(self.run_cli("now")["tocando"])
        self.assertTrue(self.run_cli("play", "Titãs - Epitáfio", "--device", "celular")["ok"])
        self.assertEqual(self.estado.log[-1][2].get("device_id"), "dev1")
        self.run_cli("volume", "150")
        self.assertEqual(self.estado.log[-1][2]["volume_percent"], "100")
        self.assertIn("Epitáfio", self.run_cli("queue", "Titãs - Epitáfio")["na_fila"])

    def test_export(self):
        self.criar()
        r = self.run_cli("export")
        dados = json.loads(Path(r["arquivo"]).read_text())
        self.assertEqual(len(dados["playlists"][0]["musicas_lista"]), 2)


class TestApiAntiga(TestPlaylists):
    """Mesmos testes, mas o servidor só conhece os endpoints antigos (pré-2026)."""
    api_antiga = True


if __name__ == "__main__":
    unittest.main()
