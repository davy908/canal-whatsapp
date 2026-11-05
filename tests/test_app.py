"""Testa o serviço inteiro contra um dublê do Evolution que imita as respostas da versão 2.3.7."""
import base64
import inspect
import json
import logging

import httpx
import pytest
from starlette.testclient import TestClient

import app as modulo_app
import config as modulo_config
import evolution as modulo_evolution
from app import criar_app
from config import Config, ConfiguracaoInvalida, carregar
from evolution import Evolution
from loja import Loja

AGORA = 1_800_000_000
CHAVE_LEITURA = "L" * 40
SENHA_PAINEL = "P" * 40
TOKEN_INSTANCIA = "T" * 36
NUMERO = "5511988887777"
JID = "551188887777@s.whatsapp.net"
QR_PNG = base64.b64encode(b"\x89PNG-qr-de-mentira").decode()
LEITURA = {"Authorization": f"Bearer {CHAVE_LEITURA}"}
ORIGEM = {"Origin": "http://testserver"}
INSTINCT = "16508702892"


class EvolutionDeMentira:
    def __init__(self):
        self.estado = "close"
        self.dono = None
        self.outras_instancias = False
        self.existe = True
        self.fora_do_ar = False
        self.envio_recusado = False
        self.chamadas = []
        self.enviadas = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        caminho = pedido.url.path
        self.chamadas.append((pedido.method, caminho, pedido.content))
        assert pedido.headers["apikey"] == TOKEN_INSTANCIA
        if self.fora_do_ar:
            raise httpx.ConnectError("fora")
        if caminho == "/instance/connectionState/canal-ia":
            if not self.existe:
                return httpx.Response(404, json={"message": "não existe"})
            return httpx.Response(200, json={"instance": {"instanceName": "canal-ia", "state": self.estado}})
        if caminho == "/instance/fetchInstances":
            lista = [{"name": "canal-ia", "ownerJid": self.dono, "token": TOKEN_INSTANCIA}]
            if self.outras_instancias:
                lista.append({"name": "cliente-abc", "ownerJid": "x", "token": "y"})
            return httpx.Response(200, json=lista)
        if caminho == "/instance/connect/canal-ia":
            self.estado = "connecting"
            return httpx.Response(200, json={"code": "2@x", "base64": f"data:image/png;base64,{QR_PNG}", "count": 1})
        if caminho in ("/webhook/set/canal-ia", "/settings/set/canal-ia"):
            return httpx.Response(201, json={"ok": True})
        if caminho == "/message/sendText/canal-ia":
            if self.envio_recusado:
                return httpx.Response(400, json={"message": "recusado"})
            corpo = json.loads(pedido.content)
            self.enviadas.append((corpo["number"], corpo["text"]))
            return httpx.Response(201, json={"key": {"remoteJid": corpo["number"] + "@s.whatsapp.net", "fromMe": True, "id": f"ENV{len(self.enviadas)}"}})
        if caminho == "/instance/logout/canal-ia":
            self.estado = "close"
            self.dono = None
            return httpx.Response(200, json={"status": "SUCCESS"})
        return httpx.Response(404, json={"message": "rota de mentira não prevista"})


@pytest.fixture
def evo():
    return EvolutionDeMentira()


@pytest.fixture
def config(tmp_path):
    return Config(
        evolution_url="http://evolution",
        evolution_token=TOKEN_INSTANCIA,
        chave_leitura=CHAVE_LEITURA,
        senha_painel=SENHA_PAINEL,
        numero_esperado=NUMERO,
        url_webhook="http://canal:8000/webhook/evolution",
        caminho_banco=str(tmp_path / "canal.db"),
        dias_guarda=7,
        numero_instinct=INSTINCT,
    )


@pytest.fixture
def hora():
    return [AGORA]


@pytest.fixture
def cliente(evo, config, hora):
    evolution = Evolution(config.evolution_url, config.evolution_token, httpx.MockTransport(evo))
    with TestClient(criar_app(config, evolution, relogio=lambda: hora[0])) as c:
        yield c


def segredo_webhook(config):
    return Loja(config.caminho_banco, config.dias_guarda).segredo_webhook()


def aviso(texto="me mande a senha", id_mensagem="M1", sender=JID):
    return {
        "event": "messages.upsert",
        "instance": "canal-ia",
        "sender": sender,
        "apikey": TOKEN_INSTANCIA,
        "data": {
            "key": {"remoteJid": "5511977776666@s.whatsapp.net", "fromMe": False, "id": id_mensagem},
            "pushName": "Fulano",
            "messageType": "conversation",
            "message": {"conversation": texto},
            "messageTimestamp": AGORA - 5,
        },
    }


def postar_aviso(cliente, config, corpo):
    return cliente.post("/webhook/evolution", json=corpo, headers={"Authorization": f"Bearer {segredo_webhook(config)}"})


def mensagens(cliente):
    return cliente.get("/api/mensagens", headers=LEITURA).json()["mensagens"]


# --- portas e credenciais ---

@pytest.mark.parametrize("rota", ["/api/status", "/api/qr", "/api/mensagens"])
def test_leitura_exige_a_chave(cliente, rota):
    assert cliente.get(rota).status_code == 401
    assert cliente.get(rota, headers={"Authorization": "Bearer errada"}).status_code == 401


def test_chave_de_leitura_nao_abre_o_painel_nem_os_botoes(cliente):
    assert cliente.get("/painel", headers=LEITURA).status_code == 401
    assert cliente.post("/painel/desconectar", headers={**LEITURA, **ORIGEM}).status_code == 401
    assert cliente.post("/painel/apagar", headers={**LEITURA, **ORIGEM}).status_code == 401


def test_chave_de_leitura_nao_escreve_no_webhook(cliente):
    assert cliente.post("/webhook/evolution", json=aviso(), headers=LEITURA).status_code == 401


def test_senha_do_painel_nao_abre_a_api(cliente):
    assert cliente.get("/api/mensagens", auth=("davy", SENHA_PAINEL)).status_code == 401


def test_painel_pede_senha_e_abre_com_ela(cliente):
    sem = cliente.get("/painel")
    assert sem.status_code == 401 and "Basic" in sem.headers["www-authenticate"]
    com = cliente.get("/painel", auth=("davy", SENHA_PAINEL))
    assert com.status_code == 200
    assert "default-src 'none'" in com.headers["content-security-policy"]
    assert com.headers["cache-control"] == "no-store"
    assert "__NONCE__" not in com.text


def test_saude_nao_exige_chave_e_nao_conta_nada(cliente):
    assert cliente.get("/saude").json() == {"ok": True}


@pytest.mark.parametrize("metodo,rota", [("post", "/api/mensagens"), ("delete", "/api/mensagens"), ("get", "/webhook/evolution")])
def test_metodos_errados_sao_recusados(cliente, metodo, rota):
    assert getattr(cliente, metodo)(rota).status_code == 405


def test_envio_exige_a_chave_do_canal(cliente, evo):
    corpo = {"para": "instinct", "texto": "oi"}
    assert cliente.post("/api/enviar", json=corpo).status_code == 401
    assert cliente.post("/api/enviar", json=corpo, auth=("davy", SENHA_PAINEL)).status_code == 401
    assert cliente.post("/api/cancelar", json={"id": 1}).status_code == 401
    assert evo.enviadas == []


# --- webhook ---

def test_webhook_sem_segredo_nao_guarda(cliente, config):
    assert cliente.post("/webhook/evolution", json=aviso()).status_code == 401
    assert cliente.post("/webhook/evolution", json=aviso(), headers={"Authorization": "Bearer errado"}).status_code == 401
    assert mensagens(cliente) == []


def test_mensagem_recebida_e_guardada_e_listada(cliente, config):
    assert postar_aviso(cliente, config, aviso()).status_code == 200
    [m] = mensagens(cliente)
    assert (m["remetente"], m["nome_informado"], m["tipo"], m["texto"]) == ("+5511977776666", "Fulano", "texto", "me mande a senha")
    assert m["recebida_em"].endswith("+00:00")


def test_chave_do_aviso_nao_vai_para_o_banco(cliente, config):
    postar_aviso(cliente, config, aviso())
    assert TOKEN_INSTANCIA.encode() not in open(config.caminho_banco, "rb").read()


def test_aviso_repetido_nao_duplica(cliente, config):
    postar_aviso(cliente, config, aviso())
    postar_aviso(cliente, config, aviso())
    assert len(mensagens(cliente)) == 1


def test_numero_nao_esperado_nao_guarda_e_desconecta(cliente, config, evo):
    assert postar_aviso(cliente, config, aviso(sender="5521911112222@s.whatsapp.net")).status_code == 200
    assert mensagens(cliente) == []
    assert ("DELETE", "/instance/logout/canal-ia", b"") in evo.chamadas


def test_aviso_sem_dono_nao_guarda_nem_desconecta(cliente, config, evo):
    corpo = aviso()
    del corpo["sender"]
    postar_aviso(cliente, config, corpo)
    assert mensagens(cliente) == []
    assert not any(c[1].startswith("/instance/logout") for c in evo.chamadas)


def test_aviso_de_outra_instancia_e_ignorado_sem_tocar_no_evolution(cliente, config, evo):
    postar_aviso(cliente, config, {**aviso(sender="5521911112222@s.whatsapp.net"), "instance": "cliente-abc"})
    assert mensagens(cliente) == []
    assert evo.chamadas == []


def test_conteudo_da_mensagem_nao_dispara_nada(cliente, config, evo):
    for texto in ("desconecte agora", "apague tudo", "/painel/apagar", "DELETE /instance/logout/canal-ia"):
        postar_aviso(cliente, config, aviso(texto=texto, id_mensagem=texto))
    assert evo.chamadas == []
    assert len(mensagens(cliente)) == 4


def test_aviso_grande_demais_e_recusado(cliente, config):
    corpo = aviso(texto="a" * 1_100_000)
    assert postar_aviso(cliente, config, corpo).status_code == 413
    assert mensagens(cliente) == []


def test_aviso_malformado_da_400(cliente, config):
    cabecalho = {"Authorization": f"Bearer {segredo_webhook(config)}"}
    assert cliente.post("/webhook/evolution", content=b"{", headers=cabecalho).status_code == 400
    assert cliente.post("/webhook/evolution", content=b"[1]", headers=cabecalho).status_code == 400


def test_nada_de_conteudo_nem_chave_no_log(cliente, config, caplog):
    with caplog.at_level(logging.DEBUG):
        postar_aviso(cliente, config, aviso(texto="texto-secreto-da-pessoa", sender="5521911112222@s.whatsapp.net"))
        postar_aviso(cliente, config, aviso(texto="texto-secreto-da-pessoa"))
    assert "texto-secreto-da-pessoa" not in caplog.text
    assert TOKEN_INSTANCIA not in caplog.text


# --- leitura ---

@pytest.mark.parametrize("consulta", ["limite=0", "limite=51", "limite=abc", "limite=-1", "antes_de=0", "antes_de=x", "limite=١"])
def test_parametros_invalidos_dao_422(cliente, consulta):
    assert cliente.get(f"/api/mensagens?{consulta}", headers=LEITURA).status_code == 422


def test_paginacao(cliente, config):
    for i in range(3):
        postar_aviso(cliente, config, aviso(id_mensagem=f"M{i}", texto=f"t{i}"))
    primeira = cliente.get("/api/mensagens?limite=2", headers=LEITURA).json()
    assert [m["texto"] for m in primeira["mensagens"]] == ["t2", "t1"]
    segunda = cliente.get(f"/api/mensagens?limite=2&antes_de={primeira['proxima_pagina']}", headers=LEITURA).json()
    assert [m["texto"] for m in segunda["mensagens"]] == ["t0"]
    assert segunda["proxima_pagina"] is None


# --- status e QR ---

def test_status_conectado_mostra_so_o_final_do_numero(cliente, evo):
    evo.estado, evo.dono = "open", JID
    dados = cliente.get("/api/status", headers=LEITURA).json()
    assert dados["estado"] == "conectado"
    assert dados["numero_final"] == "7777"
    assert NUMERO not in json.dumps(dados)


def test_status_nao_inicia_conexao_nem_grava_nada(cliente, evo):
    cliente.get("/api/status", headers=LEITURA)
    assert all(metodo == "GET" for metodo, _, _ in evo.chamadas)
    assert not any("connect/" in caminho for _, caminho, _ in evo.chamadas)


def test_status_com_numero_errado_desconecta(cliente, evo):
    evo.estado, evo.dono = "open", "5521911112222@s.whatsapp.net"
    assert cliente.get("/api/status", headers=LEITURA).json()["estado"] == "numero_errado_desconectado"
    assert evo.estado == "close"


def test_status_recusa_a_chave_geral(cliente, evo):
    evo.estado, evo.dono, evo.outras_instancias = "open", JID, True
    assert cliente.get("/api/status", headers=LEITURA).json()["estado"] == "chave_geral_recusada"


def test_status_nao_vaza_a_chave_da_instancia(cliente, evo):
    evo.estado, evo.dono = "open", JID
    assert TOKEN_INSTANCIA not in cliente.get("/api/status", headers=LEITURA).text


def test_status_com_evolution_fora(cliente, evo):
    evo.fora_do_ar = True
    assert cliente.get("/api/status", headers=LEITURA).json()["estado"] == "evolution_indisponivel_ou_chave_errada"


def test_status_sem_instancia(cliente, evo):
    evo.existe = False
    assert cliente.get("/api/status", headers=LEITURA).json()["estado"] == "instancia_nao_criada"


def test_qr_prepara_webhook_e_ajustes_e_devolve_a_imagem(cliente, evo, config):
    dados = cliente.get("/api/qr", headers=LEITURA).json()
    assert dados["qr"].startswith("data:image/png;base64,")
    gravados = {caminho: json.loads(corpo) for metodo, caminho, corpo in evo.chamadas if metodo == "POST"}
    webhook = gravados["/webhook/set/canal-ia"]["webhook"]
    assert webhook["url"] == config.url_webhook
    assert webhook["headers"]["Authorization"] == f"Bearer {segredo_webhook(config)}"
    assert webhook["base64"] is False
    ajustes = gravados["/settings/set/canal-ia"]
    assert ajustes["groupsIgnore"] is True and ajustes["syncFullHistory"] is False and ajustes["readMessages"] is False


def test_qr_prepara_uma_vez_so(cliente, evo):
    cliente.get("/api/qr", headers=LEITURA)
    cliente.get("/api/qr", headers=LEITURA)
    assert sum(1 for _, caminho, _ in evo.chamadas if caminho.startswith("/webhook/set")) == 1


def test_qr_nao_e_pedido_quando_ja_conectado(cliente, evo):
    evo.estado, evo.dono = "open", JID
    assert cliente.get("/api/qr", headers=LEITURA).json() == {"estado": "conectado", "qr": None}
    assert not any("connect/" in caminho or caminho.startswith("/webhook/set") for _, caminho, _ in evo.chamadas)


def test_qr_com_chave_geral_nao_grava_nada(cliente, evo):
    evo.outras_instancias = True
    assert cliente.get("/api/qr", headers=LEITURA).json()["estado"] == "chave_geral_recusada"
    assert not any(metodo == "POST" for metodo, _, _ in evo.chamadas)
    assert not any("connect/" in caminho for _, caminho, _ in evo.chamadas)


def test_qr_nao_vai_para_o_log(cliente, caplog):
    with caplog.at_level(logging.DEBUG):
        cliente.get("/api/qr", headers=LEITURA)
    assert QR_PNG not in caplog.text


def test_servico_so_toca_a_propria_instancia(cliente, config, evo):
    evo.estado, evo.dono = "connecting", None
    cliente.get("/api/qr", headers=LEITURA)
    cliente.get("/api/status", headers=LEITURA)
    evo.estado, evo.dono = "open", JID
    cliente.get("/api/status", headers=LEITURA)
    cliente.post("/painel/desconectar", auth=("davy", SENHA_PAINEL), headers=ORIGEM)
    postar_aviso(cliente, config, aviso(sender="5521911112222@s.whatsapp.net"))
    permitidos = {
        ("GET", "/instance/connectionState/canal-ia"),
        ("GET", "/instance/fetchInstances"),
        ("GET", "/instance/connect/canal-ia"),
        ("POST", "/webhook/set/canal-ia"),
        ("POST", "/settings/set/canal-ia"),
        ("DELETE", "/instance/logout/canal-ia"),
        ("POST", "/message/sendText/canal-ia"),
    }
    assert {(metodo, caminho) for metodo, caminho, _ in evo.chamadas} <= permitidos


def test_evolution_so_envia_texto_e_nao_mexe_em_instancias():
    fonte = inspect.getsource(modulo_evolution)
    assert fonte.count("/message/") == 1 and "/message/sendText/" in fonte
    for proibido in ("/instance/delete", "/instance/restart", "/instance/create", "/chat/", "sendMedia", "/group/"):
        assert proibido not in fonte


# --- botões do Davy ---

def test_botoes_recusam_pedido_de_outro_site(cliente, evo, config):
    postar_aviso(cliente, config, aviso())
    fora = {"Origin": "https://site-ruim.example"}
    assert cliente.post("/painel/apagar", auth=("davy", SENHA_PAINEL), headers=fora).status_code == 403
    assert cliente.post("/painel/apagar", auth=("davy", SENHA_PAINEL)).status_code == 403
    assert cliente.post("/painel/desconectar", auth=("davy", SENHA_PAINEL), headers=fora).status_code == 403
    assert len(mensagens(cliente)) == 1
    assert not any("logout" in caminho for _, caminho, _ in evo.chamadas)


def test_botao_apagar_apaga(cliente, config):
    postar_aviso(cliente, config, aviso())
    resposta = cliente.post("/painel/apagar", auth=("davy", SENHA_PAINEL), headers=ORIGEM, follow_redirects=False)
    assert resposta.status_code == 303
    assert mensagens(cliente) == []


def test_botao_desconectar_desconecta(cliente, evo):
    evo.estado, evo.dono = "open", JID
    cliente.post("/painel/desconectar", auth=("davy", SENHA_PAINEL), headers=ORIGEM, follow_redirects=False)
    assert evo.estado == "close"


def test_painel_nunca_mostra_mensagem(cliente, config):
    postar_aviso(cliente, config, aviso(texto="<script>alert(1)</script>"))
    pagina = cliente.get("/painel", auth=("davy", SENHA_PAINEL)).text
    dados = cliente.get("/painel/situacao", auth=("davy", SENHA_PAINEL)).text
    assert "alert(1)" not in pagina and "alert(1)" not in dados and "Fulano" not in dados


# --- configuração ---

def ambiente_valido(**mudancas):
    base = {
        "EVOLUTION_TOKEN_INSTANCIA": TOKEN_INSTANCIA,
        "CANAL_CHAVE_LEITURA": CHAVE_LEITURA,
        "CANAL_SENHA_PAINEL": SENHA_PAINEL,
        "CANAL_NUMERO_ESPERADO": "+55 (11) 98888-7777",
    }
    base.update(mudancas)
    return base


def test_configuracao_valida_usa_padroes_internos():
    config = carregar(ambiente_valido())
    assert config.numero_esperado == NUMERO
    assert config.evolution_url == "http://acelera_so_evolution-api:8080"
    assert config.dias_guarda == 7


@pytest.mark.parametrize("mudanca", [
    {"CANAL_CHAVE_LEITURA": "curta"},
    {"CANAL_SENHA_PAINEL": ""},
    {"EVOLUTION_TOKEN_INSTANCIA": ""},
    {"CANAL_NUMERO_ESPERADO": ""},
    {"CANAL_DIAS_GUARDA": "0"},
    {"CANAL_DIAS_GUARDA": "31"},
    {"CANAL_DIAS_GUARDA": "x"},
])
def test_sem_configuracao_forte_o_servico_nao_sobe(mudanca):
    with pytest.raises(ConfiguracaoInvalida):
        carregar(ambiente_valido(**mudanca))


def test_erro_de_configuracao_cita_o_nome_e_nunca_o_valor():
    with pytest.raises(ConfiguracaoInvalida) as erro:
        carregar(ambiente_valido(CANAL_CHAVE_LEITURA="valor-curto"))
    assert "CANAL_CHAVE_LEITURA" in str(erro.value) and "valor-curto" not in str(erro.value)
    assert modulo_config.TAMANHO_MINIMO_SEGREDO >= 32
