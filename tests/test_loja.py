import sqlite3

import loja as modulo_loja
from loja import Loja
from mensagem import MensagemRecebida

AGORA = 1_800_000_000
DIA = 86400


def msg(id_evolution="A", recebida_em=AGORA, texto="oi"):
    return MensagemRecebida(id_evolution, recebida_em, "+5511", "Nome", "texto", texto)


def nova_loja(tmp_path, dias=7):
    return Loja(str(tmp_path / "canal.db"), dias)


def test_mesmo_aviso_duas_vezes_guarda_uma_so(tmp_path):
    loja = nova_loja(tmp_path)
    assert loja.guardar(msg()) is True
    assert loja.guardar(msg()) is False
    assert loja.resumo(AGORA)["mensagens_guardadas"] == 1


def test_lista_da_mais_nova_para_a_mais_antiga_com_pagina(tmp_path):
    loja = nova_loja(tmp_path)
    for i in range(5):
        loja.guardar(msg(f"M{i}", AGORA + i, f"t{i}"))
    pagina, proxima = loja.listar(AGORA + 10, 2)
    assert [m["texto"] for m in pagina] == ["t4", "t3"]
    pagina, proxima = loja.listar(AGORA + 10, 2, proxima)
    assert [m["texto"] for m in pagina] == ["t2", "t1"]
    pagina, proxima = loja.listar(AGORA + 10, 2, proxima)
    assert [m["texto"] for m in pagina] == ["t0"]
    assert proxima is None


def test_vencida_nao_aparece_mesmo_antes_da_limpeza(tmp_path):
    loja = nova_loja(tmp_path, dias=7)
    loja.guardar(msg("velha", AGORA - 8 * DIA))
    loja.guardar(msg("nova", AGORA - 6 * DIA))
    pagina, _ = loja.listar(AGORA, 10)
    assert len(pagina) == 1
    assert loja.resumo(AGORA)["mensagens_guardadas"] == 1


def test_limpeza_apaga_do_arquivo_so_a_vencida(tmp_path):
    loja = nova_loja(tmp_path, dias=7)
    loja.guardar(msg("velha", AGORA - 8 * DIA, "conteudo-velho"))
    loja.guardar(msg("nova", AGORA))
    assert loja.apagar_vencidas(AGORA) == 1
    assert sqlite3.connect(tmp_path / "canal.db").execute("SELECT COUNT(*) FROM mensagens").fetchone()[0] == 1
    assert b"conteudo-velho" not in (tmp_path / "canal.db").read_bytes()


def test_apagar_tudo(tmp_path):
    loja = nova_loja(tmp_path)
    loja.guardar(msg("A"))
    loja.guardar(msg("B"))
    assert loja.apagar_tudo() == 2
    assert loja.listar(AGORA, 10)[0] == []


def test_teto_impede_encher_o_disco(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_loja, "TETO_MENSAGENS", 3)
    loja = nova_loja(tmp_path)
    for i in range(5):
        loja.guardar(msg(f"M{i}", AGORA, f"t{i}"))
    assert [m["texto"] for m in loja.listar(AGORA, 10)[0]] == ["t4", "t3", "t2"]


def test_segredo_do_webhook_e_criado_uma_vez(tmp_path):
    loja = nova_loja(tmp_path)
    segredo = loja.segredo_webhook()
    assert len(segredo) >= 32
    assert Loja(str(tmp_path / "canal.db"), 7).segredo_webhook() == segredo


def test_apagar_mensagens_nao_troca_o_segredo(tmp_path):
    loja = nova_loja(tmp_path)
    segredo = loja.segredo_webhook()
    loja.apagar_tudo()
    assert loja.segredo_webhook() == segredo


def test_banco_da_versao_antiga_ganha_as_colunas_novas(tmp_path):
    caminho = tmp_path / "canal.db"
    with sqlite3.connect(caminho) as banco:
        banco.execute(
            "CREATE TABLE mensagens (seq INTEGER PRIMARY KEY AUTOINCREMENT, id_evolution TEXT NOT NULL UNIQUE,"
            " recebida_em INTEGER NOT NULL, remetente TEXT NOT NULL, nome_informado TEXT NOT NULL,"
            " tipo TEXT NOT NULL, texto TEXT NOT NULL)"
        )
        banco.execute("INSERT INTO mensagens VALUES (1, 'V', ?, '+55', 'N', 'texto', 'antiga')", (AGORA,))
    banco.close()
    loja = Loja(str(caminho), 7)
    [linha], _ = loja.listar(AGORA, 10)
    assert (linha["texto"], linha["origem"], linha["conversa"]) == ("antiga", "externo", "")
    Loja(str(caminho), 7)  # abrir de novo não tenta criar a coluna outra vez


def test_envio_pego_uma_vez_so(tmp_path):
    loja = nova_loja(tmp_path)
    loja.agendar("instinct", "oi", AGORA, AGORA)
    assert len(loja.pegar_para_enviar(AGORA)) == 1
    assert loja.pegar_para_enviar(AGORA) == []  # ficou "enviando": queda no meio não repete o envio
    assert not loja.ha_vencida(AGORA)


def test_limpeza_tira_envios_antigos_e_deixa_os_pendentes(tmp_path):
    loja = nova_loja(tmp_path)
    feito = loja.agendar("davy", "feito", AGORA, AGORA)
    loja.marcar(feito, modulo_loja.ENVIADA, AGORA)
    pendente = loja.agendar("davy", "longe", AGORA + 30 * DIA, AGORA)
    loja.apagar_vencidas(AGORA + 8 * DIA)
    assert [e["id"] for e in loja.listar_agendadas()] == [pendente]
