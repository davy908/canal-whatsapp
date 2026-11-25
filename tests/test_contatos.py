"""Lista fechada de contatos (CANAL_CONTATOS, pedido do Davy em 24/nov/2026).

O Claude escolhe o contato pelo nome; o número só existe na VPS. O que o Davy digita para um
contato continua fora do canal: só as conversas dele com ele mesmo e com o Instinct são guardadas.
"""
import dataclasses

import httpx
import pytest
from starlette.testclient import TestClient

from app import criar_app
from config import ConfiguracaoInvalida, _contatos
from evolution import Evolution
from test_app import (  # noqa: F401  (fixtures do pytest)
    AGORA,
    LEITURA,
    config,
    evo,
    hora,
    mensagens,
    postar_aviso,
)
from test_envio import aviso_do_davy, conectar, enviar

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
