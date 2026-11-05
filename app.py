"""Serviço da VPS: recebe o aviso do Evolution, guarda o mínimo e expõe só leitura.

Três credenciais, três portas: o Evolution só escreve em /webhook, o Claude só lê em /api, e só o
Davy desconecta ou apaga, em /painel. Conteúdo de mensagem nunca decide nada aqui e nunca aparece
no painel nem em log. Sem limite de tentativas de senha porque as chaves têm 32+ caracteres
aleatórios: adivinhar não é viável.
"""
import base64
import binascii
import hmac
import json
import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from config import Config, carregar
from evolution import ChaveGeralRecusada, Evolution, EvolutionFora
from loja import Loja
from mensagem import INSTANCIA, _so_digitos, extrair_recebida, numeros_iguais
from painel_html import PAGINA_PAINEL

log = logging.getLogger("canal-whatsapp")

TAMANHO_MAXIMO_AVISO = 1_000_000
LIMITE_PADRAO = 20
LIMITE_MAXIMO = 50
INTERVALO_LIMPEZA_SEGUNDOS = 3600


class _CabecalhosDeSeguranca(BaseHTTPMiddleware):
    async def dispatch(self, pedido: Request, seguinte) -> Response:
        resposta = await seguinte(pedido)
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        return resposta


def _segredo_confere(apresentado: str, esperado: str) -> bool:
    return hmac.compare_digest(apresentado.encode(), esperado.encode())


def _bearer_confere(pedido: Request, esperado: str) -> bool:
    cabecalho = pedido.headers.get("authorization", "")
    return cabecalho.startswith("Bearer ") and _segredo_confere(cabecalho[len("Bearer "):], esperado)


def _basic_confere(pedido: Request, senha: str) -> bool:
    cabecalho = pedido.headers.get("authorization", "")
    if not cabecalho.startswith("Basic "):
        return False
    try:
        decodificado = base64.b64decode(cabecalho[len("Basic "):], validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    return _segredo_confere(decodificado.partition(":")[2], senha)


def _erro(status: int, titulo: str) -> JSONResponse:
    return JSONResponse({"title": titulo, "status": status}, status_code=status, media_type="application/problem+json")


class Canal:
    """As regras do serviço, sem HTTP: quem pode ser guardado e o que cada estado significa."""

    def __init__(self, config: Config, evolution: Evolution, loja: Loja, relogio=time.time):
        self._config = config
        self._evolution = evolution
        self._loja = loja
        self._relogio = relogio
        self._ja_preparou = False

    def agora(self) -> int:
        return int(self._relogio())

    def _estado_e_numero(self) -> tuple[str, str | None]:
        """A checagem do número desconecta quem não é o esperado: é a trava, por isso mora na leitura."""
        try:
            estado = self._evolution.estado()
            if estado is None:
                return "instancia_nao_criada", None
            if estado == "connecting":
                return "aguardando_qr", None
            if estado != "open":
                return "desconectado", None
            dono = self._evolution.numero_conectado()
            if dono is None:
                return "conferindo_numero", None
            if not numeros_iguais(dono, self._config.numero_esperado):
                self._desconectar_numero_errado()
                return "numero_errado_desconectado", None
            return "conectado", _so_digitos(dono)[-4:]
        except ChaveGeralRecusada:
            log.error("chave_geral_recusada")
            return "chave_geral_recusada", None
        except EvolutionFora:
            log.warning("evolution_indisponivel")
            return "evolution_indisponivel_ou_chave_errada", None

    def situacao(self) -> dict:
        estado, numero_final = self._estado_e_numero()
        return {
            "estado": estado,
            "numero_final": numero_final,
            "dias_guarda": self._config.dias_guarda,
            **self._loja.resumo(self.agora()),
        }

    def qr(self) -> dict:
        estado, _ = self._estado_e_numero()
        if estado not in ("desconectado", "aguardando_qr"):
            return {"estado": estado, "qr": None}
        try:
            if not self._ja_preparou:
                self._evolution.preparar(self._config.url_webhook, self._loja.segredo_webhook())
                self._ja_preparou = True
            return {"estado": "aguardando_qr", "qr": self._evolution.pedir_qr()}
        except ChaveGeralRecusada:
            log.error("chave_geral_recusada")
            return {"estado": "chave_geral_recusada", "qr": None}
        except EvolutionFora:
            log.warning("evolution_indisponivel")
            return {"estado": "evolution_indisponivel_ou_chave_errada", "qr": None}

    def receber_aviso(self, aviso: dict) -> None:
        if aviso.get("instance") != INSTANCIA:
            return
        dono = aviso.get("sender")
        if not isinstance(dono, str) or not _so_digitos(dono):
            return  # sem saber de quem é a conexão, não guarda
        if not numeros_iguais(dono, self._config.numero_esperado):
            self._desconectar_numero_errado()
            return
        mensagem = extrair_recebida(aviso, self.agora())
        if mensagem is not None:
            self._loja.guardar(mensagem)

    def _desconectar_numero_errado(self) -> None:
        log.error("numero_nao_esperado_desconectando")
        try:
            self._evolution.desconectar()
        except EvolutionFora:
            log.warning("evolution_indisponivel")

    def mensagens(self, limite: int, antes_de: int | None) -> dict:
        pagina, proxima = self._loja.listar(self.agora(), limite, antes_de)
        return {
            "mensagens": [
                {
                    "id": linha["seq"],
                    "recebida_em": datetime.fromtimestamp(linha["recebida_em"], timezone.utc).isoformat(),
                    "remetente": linha["remetente"],
                    "tipo": linha["tipo"],
                    "nome_informado": linha["nome_informado"],
                    "texto": linha["texto"],
                }
                for linha in pagina
            ],
            "proxima_pagina": proxima,
        }

    def desconectar(self) -> bool:
        try:
            self._evolution.desconectar()
            return True
        except EvolutionFora:
            log.warning("evolution_indisponivel")
            return False

    def apagar_mensagens(self) -> int:
        return self._loja.apagar_tudo()

    def apagar_vencidas(self) -> int:
        return self._loja.apagar_vencidas(self.agora())


def _inteiro(pedido: Request, nome: str, minimo: int, maximo: int, padrao: int | None) -> int | None:
    bruto = pedido.query_params.get(nome)
    if bruto is None:
        return padrao
    if not bruto.isascii() or not bruto.isdigit():
        raise ValueError(nome)
    valor = int(bruto)
    if not minimo <= valor <= maximo:
        raise ValueError(nome)
    return valor


def _mesma_origem(pedido: Request) -> bool:
    """A senha do painel vai sozinha em todo pedido do navegador: outro site não pode apertar os botões."""
    origem = pedido.headers.get("origin")
    return bool(origem) and urlsplit(origem).netloc == pedido.headers.get("host")


def criar_app(config: Config, evolution: Evolution, relogio=time.time) -> Starlette:
    loja = Loja(config.caminho_banco, config.dias_guarda)
    canal = Canal(config, evolution, loja, relogio)

    def saude(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def webhook(pedido: Request) -> Response:
        if not _bearer_confere(pedido, loja.segredo_webhook()):
            return _erro(401, "Não autorizado")
        corpo = bytearray()
        async for pedaco in pedido.stream():  # autentica antes de ler; lê com teto
            corpo.extend(pedaco)
            if len(corpo) > TAMANHO_MAXIMO_AVISO:
                return _erro(413, "Aviso grande demais")
        try:
            aviso = json.loads(corpo)
        except ValueError:
            return _erro(400, "Aviso inválido")
        if not isinstance(aviso, dict):
            return _erro(400, "Aviso inválido")
        await run_in_threadpool(canal.receber_aviso, aviso)
        return JSONResponse({"ok": True})

    def _so_leitura(funcao):
        def rota(pedido: Request) -> Response:
            if not _bearer_confere(pedido, config.chave_leitura):
                return _erro(401, "Não autorizado")
            return funcao(pedido)
        return rota

    def api_status(_: Request) -> Response:
        return JSONResponse(canal.situacao())

    def api_qr(_: Request) -> Response:
        return JSONResponse(canal.qr())

    def api_mensagens(pedido: Request) -> Response:
        try:
            limite = _inteiro(pedido, "limite", 1, LIMITE_MAXIMO, LIMITE_PADRAO)
            antes_de = _inteiro(pedido, "antes_de", 1, 2**62, None)
        except ValueError:
            return _erro(422, "Parâmetro inválido")
        return JSONResponse(canal.mensagens(limite, antes_de))

    def _so_davy(funcao):
        def rota(pedido: Request) -> Response:
            if not _basic_confere(pedido, config.senha_painel):
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Canal WhatsApp", charset="UTF-8"'})
            return funcao(pedido)
        return rota

    def _botao_do_davy(funcao):
        def rota(pedido: Request) -> Response:
            if not _mesma_origem(pedido):
                return _erro(403, "Origem recusada")
            funcao()
            return RedirectResponse("/painel", status_code=303)
        return _so_davy(rota)

    def painel(_: Request) -> Response:
        nonce = secrets.token_urlsafe(16)
        politica = (
            f"default-src 'none'; img-src data:; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return HTMLResponse(PAGINA_PAINEL.replace("__NONCE__", nonce), headers={"Content-Security-Policy": politica})

    def painel_situacao(_: Request) -> Response:
        return JSONResponse(canal.situacao())

    def painel_qr(_: Request) -> Response:
        return JSONResponse(canal.qr())

    @asynccontextmanager
    async def ciclo_de_vida(_: Starlette):
        parar = threading.Event()

        def limpar_de_tempos_em_tempos() -> None:
            while True:
                try:
                    canal.apagar_vencidas()
                except Exception as erro:  # a limpeza tenta de novo; a listagem já esconde o vencido
                    log.error("limpeza_falhou %s", type(erro).__name__)
                if parar.wait(INTERVALO_LIMPEZA_SEGUNDOS):
                    return

        threading.Thread(target=limpar_de_tempos_em_tempos, daemon=True).start()
        yield
        parar.set()

    return Starlette(
        middleware=[Middleware(_CabecalhosDeSeguranca)],
        routes=[
            Route("/saude", saude),
            Route("/webhook/evolution", webhook, methods=["POST"]),
            Route("/api/status", _so_leitura(api_status)),
            Route("/api/qr", _so_leitura(api_qr)),
            Route("/api/mensagens", _so_leitura(api_mensagens)),
            Route("/painel", _so_davy(painel)),
            Route("/painel/situacao", _so_davy(painel_situacao)),
            Route("/painel/qr", _so_davy(painel_qr)),
            Route("/painel/desconectar", _botao_do_davy(canal.desconectar), methods=["POST"]),
            Route("/painel/apagar", _botao_do_davy(canal.apagar_mensagens), methods=["POST"]),
        ],
        lifespan=ciclo_de_vida,
    )


def fabrica() -> Starlette:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # cada chamada ao Evolution não precisa de registro
    config = carregar()
    return criar_app(config, Evolution(config.evolution_url, config.evolution_token))
