"""Várias pessoas num serviço só: a credencial escolhe o canal, e nada cruza de uma pessoa para outra.

Duas pessoas, cada uma com a própria instância no Evolution, o próprio banco e as próprias chaves.
Cada teste tenta usar a credencial de uma para alcançar a outra.
"""
import base64
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app import criar_app_de_varias
from config import Config, ConfiguracaoInvalida, carregar_pessoas, resumo_do_segredo
from evolution import Evolution

AGORA = 1_800_000_000
ORIGEM = {"Origin": "http://testserver"}


class Pessoa:
    def __init__(self, nome, instancia, numero, letra):
        self.nome, self.instancia, self.numero = nome, instancia, numero
        self.jid = numero + "@s.whatsapp.net"
        self.chave = letra * 40
        self.senha = letra.lower() * 40
        self.token = "T" + letra * 35
        self.chamadas = []
        self.enviadas = []

    @property
    def leitura(self):
        return {"Authorization": f"Bearer {self.chave}"}

    @property
    def painel(self):
        credencial = base64.b64encode(f"qualquer:{self.senha}".encode()).decode()
        return {"Authorization": f"Basic {credencial}", **ORIGEM}

    def evolution(self, pedido: httpx.Request) -> httpx.Response:
        """Dublê do Evolution 2.3.7 que só conhece a instância desta pessoa, e só pela chave dela."""
        caminho = pedido.url.path
        self.chamadas.append((pedido.method, caminho))
        assert pedido.headers["apikey"] == self.token
        assert caminho.endswith("/" + self.instancia) or caminho == "/instance/fetchInstances"
        if caminho.startswith("/instance/connectionState/"):
            return httpx.Response(200, json={"instance": {"instanceName": self.instancia, "state": "open"}})
        if caminho == "/instance/fetchInstances":
            return httpx.Response(200, json=[{"name": self.instancia, "ownerJid": self.jid, "token": self.token}])
        if caminho.startswith("/message/sendText/"):
            corpo = json.loads(pedido.content)
            self.enviadas.append((corpo["number"], corpo["text"]))
            return httpx.Response(201, json={"key": {"id": f"{self.nome}-{len(self.enviadas)}"}})
        if caminho.startswith(("/webhook/set/", "/settings/set/", "/instance/logout/")):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"message": "rota de mentira não prevista"})

    def config(self, pasta, **extra):
        return Config(
            evolution_url="http://evolution",
            evolution_token=self.token,
            numero_esperado=self.numero,
            url_webhook="http://canal:8000/webhook/evolution",
            caminho_banco=str(pasta / f"{self.nome}.db"),
            dias_guarda=7,
            nome=self.nome,
            instancia=self.instancia,
            hash_chave=resumo_do_segredo(self.chave),
            hash_senha=resumo_do_segredo(self.senha),
            **extra,
        )

    def aviso(self, texto, id_mensagem, conversa_jid="5511977776666@s.whatsapp.net", do_dono=False):
        return {
            "event": "messages.upsert",
            "instance": self.instancia,
            "sender": self.jid,
            "apikey": self.token,
            "data": {
                "key": {"remoteJid": conversa_jid, "fromMe": do_dono, "id": id_mensagem},
                "pushName": "Fulano",
                "messageType": "conversation",
                "message": {"conversation": texto},
                "messageTimestamp": AGORA - 5,
            },
        }


@pytest.fixture
def davy():
    return Pessoa("davy", "canal-ia", "5511988887777", "A")


@pytest.fixture
def danilo():
    return Pessoa("danilo", "canal-danilo", "5521977776666", "B")


@pytest.fixture
def cliente(tmp_path, davy, danilo):
    pessoas = [
        (p.config(tmp_path, numero_instinct="16508702892" if p is davy else ""), Evolution("http://evolution", p.token, httpx.MockTransport(p.evolution), instancia=p.instancia))
        for p in (davy, danilo)
    ]
    with TestClient(criar_app_de_varias(pessoas, relogio=lambda: AGORA)) as c:
        yield c


def canal_de(cliente, pessoa):
    [canal] = [c for c in cliente.app.state.canais if c.config.nome == pessoa.nome]
    return canal


def postar_aviso(cliente, assinado_por, corpo):
    segredo = canal_de(cliente, assinado_por).segredo_webhook()
    return cliente.post("/webhook/evolution", json=corpo, headers={"Authorization": f"Bearer {segredo}"})


def textos(cliente, pessoa):
    resposta = cliente.get("/api/mensagens", headers=pessoa.leitura)
    assert resposta.status_code == 200
    return [m["texto"] for m in resposta.json()["mensagens"]]


# --- leitura ---

def test_cada_chave_le_so_a_propria_caixa(cliente, davy, danilo):
    postar_aviso(cliente, davy, davy.aviso("para o davy", "A1"))
    postar_aviso(cliente, danilo, danilo.aviso("para o danilo", "B1"))
    assert textos(cliente, davy) == ["para o davy"]
    assert textos(cliente, danilo) == ["para o danilo"]


def test_status_diz_de_quem_e_o_canal(cliente, davy, danilo):
    assert cliente.get("/api/status", headers=davy.leitura).json()["pessoa"] == "davy"
    situacao = cliente.get("/api/status", headers=danilo.leitura).json()
    assert (situacao["pessoa"], situacao["instancia"], situacao["estado"]) == ("danilo", "canal-danilo", "conectado")


def test_chave_desconhecida_nao_le_nada(cliente):
    for rota in ("/api/status", "/api/mensagens", "/api/agendadas"):
        assert cliente.get(rota, headers={"Authorization": "Bearer " + "Z" * 40}).status_code == 401


def test_senha_do_painel_nao_serve_de_chave(cliente, danilo):
    assert cliente.get("/api/mensagens", headers={"Authorization": f"Bearer {danilo.senha}"}).status_code == 401


# --- webhook ---

def test_aviso_da_instancia_de_uma_pessoa_com_o_segredo_de_outra_e_ignorado(cliente, davy, danilo):
    # Alguém com a instância do Danilo tenta escrever na caixa do Davy fingindo ser a canal-ia.
    falso = davy.aviso("injetado", "X1")
    assert postar_aviso(cliente, danilo, falso).status_code == 200
    assert textos(cliente, davy) == []
    assert textos(cliente, danilo) == []
    assert davy.chamadas == []  # nem chegou a falar com o Evolution do Davy


def test_aviso_sem_segredo_valido_e_recusado(cliente, davy):
    resposta = cliente.post("/webhook/evolution", json=davy.aviso("x", "X2"), headers={"Authorization": "Bearer errado"})
    assert resposta.status_code == 401


# --- pedidos e envio ---

def test_pedido_do_danilo_vem_com_o_nome_dele_e_so_para_ele(cliente, davy, danilo):
    postar_aviso(cliente, danilo, danilo.aviso("Claude, resume o dia", "B2", conversa_jid=danilo.jid, do_dono=True))
    assert cliente.post("/api/pedidos/pegar", headers=davy.leitura).json()["pedidos"] == []
    [pedido] = cliente.post("/api/pedidos/pegar", headers=danilo.leitura).json()["pedidos"]
    assert (pedido["de"], pedido["texto"]) == ("danilo", "Claude, resume o dia")
    [mensagem] = cliente.get("/api/mensagens", headers=danilo.leitura).json()["mensagens"]
    assert (mensagem["origem"], mensagem["nome_informado"]) == ("danilo", "Danilo")


def test_cada_um_envia_para_si_mesmo_pela_propria_instancia(cliente, davy, danilo):
    assert cliente.post("/api/enviar", json={"para": "danilo", "texto": "pronto"}, headers=danilo.leitura).json()["estado"] == "enviada"
    assert danilo.enviadas == [(danilo.numero, "pronto")]
    assert davy.enviadas == [] and all(caminho != "/message/sendText/canal-ia" for _, caminho in davy.chamadas)


def test_um_nao_envia_para_o_outro_pelo_nome(cliente, davy, danilo):
    resposta = cliente.post("/api/enviar", json={"para": "davy", "texto": "oi"}, headers=danilo.leitura)
    assert resposta.status_code == 422
    assert "davy" not in resposta.json()["title"]
    assert davy.enviadas == [] and danilo.enviadas == []


def test_sem_numero_do_instinct_nao_existe_instinct(cliente, danilo):
    resposta = cliente.post("/api/enviar", json={"para": "instinct", "texto": "oi"}, headers=danilo.leitura)
    assert resposta.status_code == 422
    assert danilo.enviadas == []


def test_um_nao_cancela_nem_ve_o_agendamento_do_outro(cliente, davy, danilo):
    agendado = cliente.post(
        "/api/enviar", json={"para": "davy", "texto": "depois", "enviar_em": AGORA + 3600}, headers=davy.leitura
    ).json()
    assert cliente.get("/api/agendadas", headers=danilo.leitura).json()["agendadas"] == []
    assert cliente.post("/api/cancelar", json={"id": agendado["id"]}, headers=danilo.leitura).json() == {"cancelada": False}
    [ainda] = cliente.get("/api/agendadas", headers=davy.leitura).json()["agendadas"]
    assert ainda["estado"] == "pendente"


# --- painel ---

def test_senha_do_painel_abre_so_o_canal_da_pessoa(cliente, davy, danilo):
    assert cliente.get("/painel/situacao", headers=danilo.painel).json()["pessoa"] == "danilo"
    assert cliente.get("/painel/situacao", headers=davy.painel).json()["pessoa"] == "davy"
    assert cliente.get("/painel/situacao", headers={"Authorization": "Basic " + base64.b64encode(b"davy:errada").decode()}).status_code == 401


def test_apagar_pelo_painel_apaga_so_a_caixa_de_quem_pediu(cliente, davy, danilo):
    postar_aviso(cliente, davy, davy.aviso("fica", "A3"))
    postar_aviso(cliente, danilo, danilo.aviso("some", "B3"))
    assert cliente.post("/painel/apagar", headers=danilo.painel, follow_redirects=False).status_code == 303
    assert textos(cliente, danilo) == []
    assert textos(cliente, davy) == ["fica"]


def test_desconectar_pelo_painel_so_toca_a_instancia_de_quem_pediu(cliente, davy, danilo):
    cliente.post("/painel/desconectar", headers=danilo.painel, follow_redirects=False)
    assert ("DELETE", "/instance/logout/canal-danilo") in danilo.chamadas
    assert all(metodo != "DELETE" for metodo, _ in davy.chamadas)


def test_a_fila_de_cada_pessoa_sai_pela_instancia_dela(cliente, davy, danilo):
    for pessoa in (davy, danilo):
        cliente.post("/api/enviar", json={"para": pessoa.nome, "texto": "agendado", "enviar_em": AGORA + 1}, headers=pessoa.leitura)
    for canal in cliente.app.state.canais:
        canal._relogio = lambda: AGORA + 10
        canal.processar_fila()
    assert davy.enviadas == [(davy.numero, "agendado")]
    assert danilo.enviadas == [(danilo.numero, "agendado")]


# --- configuração ---

def ambiente_de_duas_pessoas(**mudancas):
    base = {
        "CANAL_PESSOAS": "davy, Danilo",
        "CANAL_DAVY_INSTANCIA": "canal-ia",
        "CANAL_DAVY_BANCO": "/data/canal.db",
        "CANAL_DAVY_EVOLUTION_TOKEN": "token-do-davy",
        "CANAL_DAVY_CHAVE_HASH": resumo_do_segredo("A" * 40),
        "CANAL_DAVY_SENHA_PAINEL_HASH": resumo_do_segredo("a" * 40),
        "CANAL_DAVY_NUMERO": "+55 11 98888-7777",
        "CANAL_DAVY_NUMERO_INSTINCT": "16508702892",
        "CANAL_DANILO_EVOLUTION_TOKEN": "token-do-danilo",
        "CANAL_DANILO_CHAVE_HASH": resumo_do_segredo("B" * 40).upper(),
        "CANAL_DANILO_SENHA_PAINEL_HASH": resumo_do_segredo("b" * 40),
        "CANAL_DANILO_NUMERO": "5521977776666",
        "CANAL_DANILO_CONTATOS": "davy:5511988887777",
        "CANAL_DANILO_CONTATOS_WEBHOOK": "davy",
    }
    base.update(mudancas)
    return {chave: valor for chave, valor in base.items() if valor is not None}


def test_sem_canal_pessoas_roda_como_uma_pessoa_so():
    [config] = carregar_pessoas(
        {
            "EVOLUTION_TOKEN_INSTANCIA": "T" * 36,
            "CANAL_CHAVE_LEITURA": "L" * 40,
            "CANAL_SENHA_PAINEL": "P" * 40,
            "CANAL_NUMERO_ESPERADO": "5511988887777",
        }
    )
    assert (config.nome, config.instancia, config.caminho_banco, config.numero_instinct) == ("davy", "canal-ia", "/data/canal.db", "16508702892")
    assert config.resumo_da_chave() == resumo_do_segredo("L" * 40)


def test_duas_pessoas_com_padroes():
    davy, danilo = carregar_pessoas(ambiente_de_duas_pessoas())
    assert (davy.nome, davy.instancia, davy.caminho_banco, davy.numero_esperado) == ("davy", "canal-ia", "/data/canal.db", "5511988887777")
    assert (danilo.nome, danilo.instancia, danilo.caminho_banco, danilo.numero_instinct) == ("danilo", "canal-danilo", "/data/danilo.db", "")
    assert danilo.hash_chave == resumo_do_segredo("B" * 40)
    assert danilo.contatos == {"davy": "5511988887777"} and danilo.contatos_webhook == ("davy",)
    assert danilo.chave_leitura == "" and danilo.senha_painel == ""  # no Ambiente só existe o resumo


@pytest.mark.parametrize(
    "mudanca",
    [
        {"CANAL_PESSOAS": "davy,davy"},
        {"CANAL_PESSOAS": "davy,instinct"},
        {"CANAL_PESSOAS": "davy,josé"},
        {"CANAL_DANILO_CHAVE_HASH": "curta"},
        {"CANAL_DANILO_CHAVE_HASH": None},
        {"CANAL_DANILO_SENHA_PAINEL_HASH": None},
        {"CANAL_DANILO_EVOLUTION_TOKEN": None},
        {"CANAL_DANILO_NUMERO": None},
        {"CANAL_DANILO_INSTANCIA": "canal-ia"},  # mesma instância do Davy
        {"CANAL_DANILO_INSTANCIA": "../instance"},
        {"CANAL_DANILO_BANCO": "/data/../data/canal.db"},  # mesmo banco do Davy
        {"CANAL_DANILO_CHAVE_HASH": resumo_do_segredo("A" * 40)},  # mesma chave do Davy
        {"CANAL_DANILO_EVOLUTION_TOKEN": "token-do-davy"},
        {"CANAL_DANILO_NUMERO": "5511988887777"},
        {"CANAL_DANILO_CONTATOS": "danilo:5511988887777"},  # o próprio nome é reservado
        {"CANAL_DANILO_CONTATOS_WEBHOOK": "lisa"},
    ],
)
def test_configuracao_que_misturaria_pessoas_nao_sobe(mudanca):
    with pytest.raises(ConfiguracaoInvalida) as erro:
        carregar_pessoas(ambiente_de_duas_pessoas(**mudanca))
    assert "token-do-davy" not in str(erro.value) and "5511988887777" not in str(erro.value)
