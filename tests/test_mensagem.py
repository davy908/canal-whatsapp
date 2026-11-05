from mensagem import extrair_recebida, limpar_texto, numeros_iguais

AGORA = 1_800_000_000


def aviso(**mudancas):
    dados = {
        "key": {"remoteJid": "5511988887777@s.whatsapp.net", "fromMe": False, "id": "ABC"},
        "pushName": "Maria",
        "messageType": "conversation",
        "message": {"conversation": "oi"},
        "messageTimestamp": AGORA - 10,
    }
    dados.update(mudancas)
    return {"event": "messages.upsert", "instance": "canal-ia", "sender": "551188887777@s.whatsapp.net",
            "apikey": "chave-da-instancia", "data": dados}


def test_extrai_mensagem_de_texto():
    m = extrair_recebida(aviso(), AGORA)
    assert (m.id_evolution, m.remetente, m.nome_informado, m.tipo, m.texto) == ("ABC", "+5511988887777", "Maria", "texto", "oi")
    assert m.recebida_em == AGORA - 10


def test_nao_leva_a_chave_que_vem_no_aviso():
    assert "chave-da-instancia" not in repr(extrair_recebida(aviso(), AGORA))


def test_ignora_o_que_o_proprio_numero_enviou():
    assert extrair_recebida(aviso(key={"remoteJid": "551188887777@s.whatsapp.net", "fromMe": True, "id": "X"}), AGORA) is None


def test_sem_from_me_nao_guarda():
    assert extrair_recebida(aviso(key={"remoteJid": "551188887777@s.whatsapp.net", "id": "X"}), AGORA) is None


def test_ignora_grupos_status_e_listas():
    for conversa in ("123-456@g.us", "status@broadcast", "123@newsletter"):
        assert extrair_recebida(aviso(key={"remoteJid": conversa, "fromMe": False, "id": "X"}), AGORA) is None


def test_ignora_outra_instancia_e_outro_evento():
    assert extrair_recebida({**aviso(), "instance": "acelera-123"}, AGORA) is None
    assert extrair_recebida({**aviso(), "event": "messages.update"}, AGORA) is None


def test_midia_guarda_so_o_tipo_e_a_legenda():
    corpo = {"imageMessage": {"caption": "veja", "url": "https://x/y", "jpegThumbnail": "AAAA"}}
    m = extrair_recebida(aviso(messageType="imageMessage", message=corpo), AGORA)
    assert (m.tipo, m.texto) == ("imagem", "veja")
    assert "AAAA" not in repr(m) and "https://x/y" not in repr(m)


def test_tipos_sem_conteudo_nao_viram_mensagem():
    assert extrair_recebida(aviso(messageType="reactionMessage", message={}), AGORA) is None
    assert extrair_recebida(aviso(messageType="protocolMessage", message={}), AGORA) is None


def test_tipo_desconhecido_guarda_sem_conteudo():
    m = extrair_recebida(aviso(messageType="contactMessage", message={"contactMessage": {"vcard": "segredo"}}), AGORA)
    assert (m.tipo, m.texto) == ("outro", "")


def test_conta_com_identificador_oculto_usa_o_numero_real_se_vier():
    com = {"remoteJid": "999@lid", "fromMe": False, "id": "X", "senderPn": "5511777776666@s.whatsapp.net"}
    sem = {"remoteJid": "999@lid", "fromMe": False, "id": "Y"}
    assert extrair_recebida(aviso(key=com), AGORA).remetente == "+5511777776666"
    assert extrair_recebida(aviso(key=sem), AGORA).remetente == "oculto:999"


def test_tira_caracteres_invisiveis_que_escondem_instrucoes():
    escondido = "oi‮⁦​\U000e0041\x07 tudo\nbem"
    assert limpar_texto(escondido, 100) == "oi tudo\nbem"


def test_mantem_emoji_composto():
    assert limpar_texto("👨‍👩", 100) == "👨‍👩"


def test_corta_texto_grande():
    m = extrair_recebida(aviso(message={"conversation": "a" * 9000}), AGORA)
    assert len(m.texto) == 4000


def test_corpo_malformado_nao_quebra():
    assert extrair_recebida({"event": "messages.upsert", "instance": "canal-ia", "data": "x"}, AGORA) is None
    assert extrair_recebida(aviso(key="x"), AGORA) is None
    assert extrair_recebida(aviso(message="x"), AGORA).texto == ""


def test_hora_absurda_vale_a_hora_da_chegada():
    assert extrair_recebida(aviso(messageTimestamp=1), AGORA).recebida_em == AGORA
    assert extrair_recebida(aviso(messageTimestamp=AGORA + 999999), AGORA).recebida_em == AGORA
    assert extrair_recebida(aviso(messageTimestamp={"low": 1}), AGORA).recebida_em == AGORA


def test_compara_numero_com_e_sem_nono_digito():
    assert numeros_iguais("5511988887777", "551188887777@s.whatsapp.net")
    assert numeros_iguais("5511988887777:12@s.whatsapp.net", "5511988887777")
    assert not numeros_iguais("5511988887777", "5511988887778")
    assert not numeros_iguais("", "")
