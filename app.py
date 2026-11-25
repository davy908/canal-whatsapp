"""Serviço da VPS: recebe o aviso do Evolution, guarda o mínimo, e envia só para o Davy, o Instinct e a lista fechada de contatos.

Três credenciais, três portas: o Evolution só escreve em /webhook, o Claude lê e pede envios em
/api, e só o Davy desconecta ou apaga, em /painel. O Claude escolhe o destino pelo nome ("davy",
"instinct" ou um nome de CANAL_CONTATOS); o número vem da configuração, então nenhum texto consegue mandar mensagem para outra
pessoa. Conteúdo de mensagem recebida nunca decide nada aqui e nunca aparece em log. Sem limite de
tentativas de senha porque as chaves têm 32+ caracteres aleatórios: adivinhar não é viável.
"""
import base64
import binascii
import hmac
import json
import logging
import re
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
from loja import ENVIADA, FALHOU, Loja
from mensagem import (
    INSTANCIA,
    ORIGEM_CLAUDE,
    TAMANHO_MAXIMO_TEXTO,
    MensagemRecebida,
    _so_digitos,
    extrair_recebida,
    limpar_texto,
    numeros_iguais,
)
from painel_html import PAGINA_PAINEL

log = logging.getLogger("canal-whatsapp")

TAMANHO_MAXIMO_AVISO = 1_000_000
TAMANHO_MAXIMO_PEDIDO = 32_000
LIMITE_PADRAO = 20
LIMITE_MAXIMO = 50
INTERVALO_FILA_SEGUNDOS = 15
INTERVALO_LIMPEZA_SEGUNDOS = 3600
ATRASO_MAXIMO_SEGUNDOS = 86400  # desconectado por mais de um dia: o aviso agendado vira "falhou"
AGENDAMENTO_MAXIMO_SEGUNDOS = 366 * 86400


_PEDIDO = re.compile(r"\s*claude\b", re.IGNORECASE)  # o resto da conversa "Você" é anotação, não pedido


class PedidoInvalido(ValueError):
    """Pedido de envio fora do combinado. A mensagem é curta e segura para devolver."""


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
        self._trava_envio = threading.Lock()  # a fila roda numa thread e no pedido de envio imediato

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
        mensagem = extrair_recebida(
            aviso,
            self.agora(),
            numero_do_davy=self._config.numero_esperado,
            conversas_do_davy=tuple(numero for numero in self._config.destinos().values() if numero),
        )
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
                    "origem": linha["origem"],
                    "conversa": linha["conversa"],
                }
                for linha in pagina
            ],
            "proxima_pagina": proxima,
        }

    # --- pedidos ---

    def pegar_pedidos(self) -> dict:
        """Pedidos novos do Davy: só na conversa dele com ele mesmo e começando com "Claude"."""
        pedidos = [
            {
                "id": linha["seq"],
                "recebida_em": datetime.fromtimestamp(linha["recebida_em"], timezone.utc).isoformat(),
                "tipo": linha["tipo"],
                "texto": linha["texto"],
            }
            for linha in self._loja.pegar_do_davy_depois_do_cursor()
            if numeros_iguais(linha["conversa"], self._config.numero_esperado) and _PEDIDO.match(linha["texto"])
        ]
        if pedidos:
            log.info("pedidos_entregues quantidade=%s", len(pedidos))
        return {"pedidos": pedidos}

    # --- envio ---

    def enviar(self, para: object, texto: object, enviar_em: object) -> dict:
        """Agenda o envio; sem hora (ou hora já passada), envia agora e devolve o resultado."""
        destinos = self._config.destinos_de_envio()
        if not isinstance(para, str) or not destinos.get(para):
            raise PedidoInvalido("para precisa ser um destes: " + ", ".join(sorted(destinos)))
        limpo = limpar_texto(texto, TAMANHO_MAXIMO_TEXTO)
        if not limpo or not isinstance(texto, str) or len(texto.strip()) > TAMANHO_MAXIMO_TEXTO:
            raise PedidoInvalido(f"texto vazio ou com mais de {TAMANHO_MAXIMO_TEXTO} caracteres")
        if para == "davy" and _PEDIDO.match(limpo):
            limpo = "🤖 " + limpo  # resposta do Claude nunca pode parecer um pedido novo do Davy
        agora = self.agora()
        if enviar_em is None:
            quando = agora
        elif isinstance(enviar_em, int) and not isinstance(enviar_em, bool):
            quando = enviar_em
        else:
            raise PedidoInvalido("enviar_em precisa ser a hora UNIX em segundos")
        if quando < agora - 60 or quando > agora + AGENDAMENTO_MAXIMO_SEGUNDOS:
            raise PedidoInvalido("enviar_em no passado ou mais de um ano à frente")
        id_agendada = self._loja.agendar(para, limpo, max(quando, agora), agora)
        if quando <= agora:
            self.processar_fila()
        return _agendada_para_fora(self._loja.agendada(id_agendada))

    def processar_fila(self) -> None:
        with self._trava_envio:
            agora = self.agora()
            if not self._loja.ha_vencida(agora):
                return  # sem nada para enviar, não incomoda o Evolution
            estado, _ = self._estado_e_numero()  # nunca envia de um número que não seja o do Davy
            if estado != "conectado":
                if self._loja.desistir_das_atrasadas(agora - ATRASO_MAXIMO_SEGUNDOS, agora):
                    log.warning("envios_atrasados_desistidos")
                return
            destinos = self._config.destinos_de_envio()
            for item in self._loja.pegar_para_enviar(agora):
                numero = destinos.get(item["para"])
                try:
                    if not numero:
                        raise EvolutionFora("destino sem número")
                    id_mensagem = self._evolution.enviar_texto(numero, item["texto"])
                except EvolutionFora:
                    log.warning("envio_falhou id=%s", item["id"])
                    self._loja.marcar(item["id"], FALHOU, agora)
                    continue
                self._loja.marcar(item["id"], ENVIADA, agora)
                self._loja.guardar_enviada(
                    MensagemRecebida(
                        id_evolution=(id_mensagem or f"canal-{item['id']}")[:128],
                        recebida_em=agora,
                        remetente="+" + self._config.numero_esperado,
                        nome_informado="Claude",
                        tipo="texto",
                        texto=item["texto"],
                        origem=ORIGEM_CLAUDE,
                        conversa="+" + numero,
                    )
                )
                log.info("envio_feito id=%s para=%s", item["id"], item["para"])

    def agendadas(self) -> dict:
        return {"agendadas": [_agendada_para_fora(linha) for linha in self._loja.listar_agendadas()]}

    def cancelar(self, id_agendada: object) -> dict:
        if not isinstance(id_agendada, int) or isinstance(id_agendada, bool):
            raise PedidoInvalido("id precisa ser um número")
        return {"cancelada": self._loja.cancelar(id_agendada, self.agora())}

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


def _agendada_para_fora(linha: dict | None) -> dict:
    if linha is None:
        return {}
    return {
        "id": linha["id"],
        "para": linha["para"],
        "texto": linha["texto"],
        "enviar_em": datetime.fromtimestamp(linha["enviar_em"], timezone.utc).isoformat(),
        "estado": linha["estado"],
    }


async def _ler_json(pedido: Request) -> dict:
    corpo = bytearray()
    async for pedaco in pedido.stream():
        corpo.extend(pedaco)
        if len(corpo) > TAMANHO_MAXIMO_PEDIDO:
            raise PedidoInvalido("pedido grande demais")
    try:
        dados = json.loads(corpo)
    except ValueError:
        raise PedidoInvalido("pedido não é JSON") from None
    if not isinstance(dados, dict):
        raise PedidoInvalido("pedido não é um objeto JSON")
    return dados


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

    def _pedido_json(funcao, autorizado, recusa):
        """Rota POST com corpo JSON: confere quem pede antes de ler o corpo, e responde 422 se fora do combinado."""
        async def rota(pedido: Request) -> Response:
            if not autorizado(pedido):
                return recusa()
            try:
                dados = await _ler_json(pedido)
                return JSONResponse(await run_in_threadpool(funcao, dados))
            except PedidoInvalido as erro:
                return _erro(422, str(erro))
        return rota

    def _do_claude(funcao):
        return _pedido_json(funcao, lambda p: _bearer_confere(p, config.chave_leitura), lambda: _erro(401, "Não autorizado"))

    def _do_davy(funcao):
        def autorizado(pedido: Request) -> bool:
            return _basic_confere(pedido, config.senha_painel) and _mesma_origem(pedido)
        return _pedido_json(funcao, autorizado, lambda: _erro(401, "Não autorizado"))

    def enviar(dados: dict) -> dict:
        return canal.enviar(dados.get("para"), dados.get("texto"), dados.get("enviar_em"))

    def cancelar(dados: dict) -> dict:
        return canal.cancelar(dados.get("id"))

    def agendadas(_: Request) -> Response:
        return JSONResponse(canal.agendadas())

    def pegar_pedidos(_: Request) -> Response:
        return JSONResponse(canal.pegar_pedidos())

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

        def trabalhar_de_tempos_em_tempos() -> None:
            ultima_limpeza = 0.0
            while True:
                try:
                    canal.processar_fila()
                except Exception as erro:  # a fila tenta de novo na próxima volta
                    log.error("fila_falhou %s", type(erro).__name__)
                if time.monotonic() - ultima_limpeza >= INTERVALO_LIMPEZA_SEGUNDOS:
                    ultima_limpeza = time.monotonic()
                    try:
                        canal.apagar_vencidas()
                    except Exception as erro:  # a limpeza tenta de novo; a listagem já esconde o vencido
                        log.error("limpeza_falhou %s", type(erro).__name__)
                if parar.wait(INTERVALO_FILA_SEGUNDOS):
                    return

        threading.Thread(target=trabalhar_de_tempos_em_tempos, daemon=True).start()
        yield
        parar.set()

    aplicacao = Starlette(
        middleware=[Middleware(_CabecalhosDeSeguranca)],
        routes=[
            Route("/saude", saude),
            Route("/webhook/evolution", webhook, methods=["POST"]),
            Route("/api/status", _so_leitura(api_status)),
            Route("/api/qr", _so_leitura(api_qr)),
            Route("/api/mensagens", _so_leitura(api_mensagens)),
            Route("/api/agendadas", _so_leitura(agendadas)),
            Route("/api/pedidos/pegar", _so_leitura(pegar_pedidos), methods=["POST"]),
            Route("/api/enviar", _do_claude(enviar), methods=["POST"]),
            Route("/api/cancelar", _do_claude(cancelar), methods=["POST"]),
            Route("/painel", _so_davy(painel)),
            Route("/painel/situacao", _so_davy(painel_situacao)),
            Route("/painel/qr", _so_davy(painel_qr)),
            Route("/painel/agendadas", _so_davy(agendadas)),
            Route("/painel/cancelar", _do_davy(cancelar), methods=["POST"]),
            Route("/painel/desconectar", _botao_do_davy(canal.desconectar), methods=["POST"]),
            Route("/painel/apagar", _botao_do_davy(canal.apagar_mensagens), methods=["POST"]),
        ],
        lifespan=ciclo_de_vida,
    )
    aplicacao.state.canal = canal  # para os testes rodarem a fila sem esperar a thread
    return aplicacao


def fabrica() -> Starlette:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # cada chamada ao Evolution não precisa de registro
    config = carregar()
    return criar_app(config, Evolution(config.evolution_url, config.evolution_token))
