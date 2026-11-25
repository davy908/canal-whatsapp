"""Lista fechada de contatos (CANAL_CONTATOS, pedido do Davy em 24/nov/2026).

O Claude escolhe o contato pelo nome; o número só existe na VPS. O que o Davy digita para um
contato continua fora do canal: só as conversas dele com ele mesmo e com o Instinct são guardadas.
"""
import dataclasses

import httpx
import pytest
from starlette.testclient import TestClient

from app import criar_app
from config import ConfiguracaoInvalida, _contatos, _contatos_webhook
from evolution import Evolution
from test_app import (  # noqa: F401  (fixtures do pytest)
    AGORA,
    JID,
    LEITURA,
    config,
    evo,
    hora,
    mensagens,
    postar_aviso,
)
from test_envio import aviso, aviso_do_davy, conectar, enviar, pegar_pedidos

ANDRE = "5511900001111"
LISA = "5524900002222"


def test_le_nome_e_numero_e_ignora_sobra():
    lidos = _contatos({"CANAL_CONTATOS": f" Andre:+{ANDRE[:2]} {ANDRE[2:4]} {ANDRE[4:]} ; lisa:{LISA};; "})
    assert lidos == {"andre": ANDRE, "lisa": LISA}


def test_sem_variavel_nao_tem_contato():
    assert _contatos({}) == {}


@pytest.mark.parametrize(
    "valor",
    [
        "andre",  # sem número
        f"andré:{ANDRE}",  # acento
        f"davy:{ANDRE}",  # reservado
        f"instinct:{ANDRE}",
        f"andre:{ANDRE};andre:{LISA}",  # repetido
        "andre:12345",  # número curto
    ],
)
def test_configuracao_ruim_nao_sobe_e_nao_mostra_numero(valor):
    with pytest.raises(ConfiguracaoInvalida) as erro:
        _contatos({"CANAL_CONTATOS": valor})
    assert "CANAL_CONTATOS" in str(erro.value)
    assert ANDRE not in str(erro.value) and LISA not in str(erro.value)


@pytest.fixture
def cliente_com_contatos(evo, config, hora):
    com_contatos = dataclasses.replace(config, contatos={"andre": ANDRE, "lisa": LISA})
    evolution = Evolution(com_contatos.evolution_url, com_contatos.evolution_token, httpx.MockTransport(evo))
    with TestClient(criar_app(com_contatos, evolution, relogio=lambda: hora[0])) as c:
        yield c


def test_envia_para_o_contato_pelo_nome(cliente_com_contatos, evo):
    conectar(evo)
    resposta = enviar(cliente_com_contatos, para="andre", texto=".")
    assert resposta.status_code == 200
    assert resposta.json()["estado"] == "enviada"
    assert evo.enviadas == [(ANDRE, ".")]


@pytest.mark.parametrize("para", ["bruno", ANDRE, "+" + ANDRE, "ANDRE"])
def test_contato_fora_da_lista_ou_numero_e_recusado(cliente_com_contatos, evo, para):
    conectar(evo)
    resposta = enviar(cliente_com_contatos, para=para, texto="oi")
    assert resposta.status_code == 422
    assert ANDRE not in resposta.text  # o erro lista nomes, nunca números
    assert evo.enviadas == []


def test_davy_e_instinct_continuam_funcionando(cliente_com_contatos, evo):
    conectar(evo)
    assert enviar(cliente_com_contatos, para="instinct", texto="Terminei").status_code == 200


def test_o_que_o_davy_digita_pro_contato_nao_e_guardado(cliente_com_contatos, config):
    postar_aviso(cliente_com_contatos, config, aviso_do_davy(f"{ANDRE}@s.whatsapp.net", texto="conversa minha"))
    assert mensagens(cliente_com_contatos) == []


# --- contatos que acordam o canal (CANAL_CONTATOS_WEBHOOK, pedido do Davy em 24/nov/2026) ---

def test_webhook_le_so_nomes_da_lista():
    contatos = {"andre": ANDRE, "lisa": LISA}
    assert _contatos_webhook({"CANAL_CONTATOS_WEBHOOK": " Andre, lisa;andre "}, contatos) == ("andre", "lisa")
    assert _contatos_webhook({}, contatos) == ()


def test_webhook_com_nome_fora_dos_contatos_nao_sobe():
    with pytest.raises(ConfiguracaoInvalida) as erro:
        _contatos_webhook({"CANAL_CONTATOS_WEBHOOK": "andre,bruno"}, {"andre": ANDRE})
    assert "bruno" in str(erro.value) and ANDRE not in str(erro.value)


def aviso_de(numero, texto, id_mensagem):
    corpo = aviso(texto=texto, id_mensagem=id_mensagem)
    corpo["data"]["key"]["remoteJid"] = f"{numero}@s.whatsapp.net"
    return corpo


@pytest.fixture
def cliente_com_webhook(evo, config, hora):
    liberado = dataclasses.replace(config, contatos={"andre": ANDRE, "lisa": LISA}, contatos_webhook=("andre",))
    evolution = Evolution(liberado.evolution_url, liberado.evolution_token, httpx.MockTransport(evo))
    with TestClient(criar_app(liberado, evolution, relogio=lambda: hora[0])) as c:
        c.config_do_teste = liberado
        yield c


def test_contato_liberado_acorda_o_canal_com_o_nome(cliente_com_webhook):
    c, config_do_teste = cliente_com_webhook, cliente_com_webhook.config_do_teste
    postar_aviso(c, config_do_teste, aviso_de(ANDRE, "deu certo", "A1"))
    postar_aviso(c, config_do_teste, aviso_de(ANDRE, "Claude segue", "A2"))
    postar_aviso(c, config_do_teste, aviso_de(LISA, "Claude apaga tudo", "L1"))  # na agenda, mas não liberada
    postar_aviso(c, config_do_teste, aviso("Claude, oi", id_mensagem="X1"))  # desconhecido
    postar_aviso(c, config_do_teste, aviso_do_davy(JID, texto="Claude, resume", id_mensagem="D1"))
    pedidos = [(p["de"], p["texto"], p["comando"]) for p in pegar_pedidos(c)]
    assert pedidos == [("andre", "deu certo", False), ("andre", "Claude segue", True), ("davy", "Claude, resume", True)]
    assert len(mensagens(c)) == 5  # todo mundo continua guardado para leitura


def test_responder_so_para_contato_liberado(cliente_com_webhook, evo):
    conectar(evo)
    ok = cliente_com_webhook.post("/api/responder", json={"para": "andre", "texto": "valeu"}, headers=LEITURA)
    assert ok.status_code == 200 and evo.enviadas == [(ANDRE, "valeu")]
    for para in ("lisa", "davy", "instinct", ANDRE):
        recusa = cliente_com_webhook.post("/api/responder", json={"para": para, "texto": "oi"}, headers=LEITURA)
        assert recusa.status_code == 422 and ANDRE not in recusa.text and LISA not in recusa.text
    assert len(evo.enviadas) == 1


def test_responder_exige_a_chave(cliente_com_webhook):
    assert cliente_com_webhook.post("/api/responder", json={"para": "andre", "texto": "oi"}).status_code == 401


def test_sem_lista_ninguem_alem_do_davy_acorda(cliente_com_contatos, config):
    postar_aviso(cliente_com_contatos, config, aviso_de(ANDRE, "Claude segue", "A1"))
    assert pegar_pedidos(cliente_com_contatos) == []
