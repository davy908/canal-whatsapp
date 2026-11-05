"""Traduz o aviso do Evolution em uma mensagem recebida, guardando só o mínimo.

O aviso traz a chave da instância no campo `apikey` e a mensagem inteira em `data`. Por isso nada
do aviso bruto é guardado ou registrado: só os campos abaixo saem daqui. O conteúdo nunca decide
nada no sistema; ele só é limpo, cortado e guardado.
"""
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

INSTANCIA = "canal-ia"
TAMANHO_MAXIMO_TEXTO = 4000
TAMANHO_MAXIMO_NOME = 80

_MIDIAS = {
    "imageMessage": "imagem",
    "videoMessage": "video",
    "audioMessage": "audio",
    "documentMessage": "documento",
    "stickerMessage": "figurinha",
}
_SEM_CONTEUDO = {"protocolMessage", "reactionMessage", "senderKeyDistributionMessage", "messageContextInfo"}
_CONVERSA_DE_GRUPO_OU_LISTA = ("@g.us", "@broadcast", "@newsletter")
_JUNTA_EMOJI = {"‌", "‍"}  # sem eles, emoji composto quebra; são os únicos invisíveis mantidos


@dataclass(frozen=True)
class MensagemRecebida:
    id_evolution: str
    recebida_em: int  # segundos desde 1970, em UTC
    remetente: str
    nome_informado: str
    tipo: str
    texto: str


def limpar_texto(bruto: object, limite: int) -> str:
    """Tira caracteres invisíveis, que servem para esconder instruções de quem lê, e corta o tamanho."""
    if not isinstance(bruto, str):
        return ""
    limpo = []
    for caractere in bruto:
        if caractere in "\n\t" or caractere in _JUNTA_EMOJI:
            limpo.append(caractere)
        elif unicodedata.category(caractere) not in ("Cc", "Cf", "Co", "Cn", "Cs"):
            limpo.append(caractere)
    return "".join(limpo).strip()[:limite]


def _so_digitos(jid: str) -> str:
    return "".join(c for c in jid.split("@")[0].split(":")[0] if c.isdigit())


def numeros_iguais(a: str, b: str) -> bool:
    """Compara dois números, aceitando o nono dígito brasileiro que o WhatsApp às vezes omite."""
    a, b = _so_digitos(a), _so_digitos(b)
    return bool(a) and _sem_nono_digito(a) == _sem_nono_digito(b)


def _sem_nono_digito(numero: str) -> str:
    if numero.startswith("55") and len(numero) == 13 and numero[4] == "9":
        return numero[:4] + numero[5:]
    return numero


def _remetente(chave: dict, conversa: str) -> str:
    # Conta com identificador oculto (@lid): o número real, se veio, está em outro campo.
    if conversa.endswith("@lid"):
        for campo in ("senderPn", "remoteJidAlt"):
            alternativo = chave.get(campo)
            if isinstance(alternativo, str) and _so_digitos(alternativo):
                return "+" + _so_digitos(alternativo)
        return "oculto:" + _so_digitos(conversa)
    return "+" + _so_digitos(conversa)


def _tipo_e_texto(dados: dict) -> tuple[str, str] | None:
    tipo = dados.get("messageType")
    corpo = dados.get("message")
    corpo = corpo if isinstance(corpo, dict) else {}
    if tipo in _SEM_CONTEUDO:
        return None
    if tipo == "conversation":
        return "texto", limpar_texto(corpo.get("conversation"), TAMANHO_MAXIMO_TEXTO)
    if tipo == "extendedTextMessage":
        estendida = corpo.get("extendedTextMessage")
        texto = estendida.get("text") if isinstance(estendida, dict) else None
        return "texto", limpar_texto(texto, TAMANHO_MAXIMO_TEXTO)
    if tipo in _MIDIAS:
        # Arquivo não é baixado: guarda só o tipo e a legenda, e imagem não vira injeção por imagem.
        midia = corpo.get(tipo)
        legenda = midia.get("caption") if isinstance(midia, dict) else None
        return _MIDIAS[tipo], limpar_texto(legenda, TAMANHO_MAXIMO_TEXTO)
    return "outro", ""


def _instante(dados: dict, agora: int) -> int:
    marcado = dados.get("messageTimestamp")
    # Vem do aviso; fora de um intervalo razoável vale a hora em que chegou (senão escaparia do prazo).
    if isinstance(marcado, int) and not isinstance(marcado, bool) and agora - 86400 * 2 <= marcado <= agora + 300:
        return marcado
    return agora


def extrair_recebida(aviso: dict, agora: int | None = None) -> MensagemRecebida | None:
    """Devolve a mensagem que merece ser guardada, ou None para o resto (enviadas, grupos, status)."""
    agora = int(datetime.now(timezone.utc).timestamp()) if agora is None else agora
    if aviso.get("event") != "messages.upsert" or aviso.get("instance") != INSTANCIA:
        return None
    dados = aviso.get("data")
    if not isinstance(dados, dict):
        return None
    chave = dados.get("key")
    if not isinstance(chave, dict) or chave.get("fromMe") is not False:
        return None
    conversa, id_evolution = chave.get("remoteJid"), chave.get("id")
    if not isinstance(conversa, str) or not isinstance(id_evolution, str) or not id_evolution:
        return None
    if conversa.endswith(_CONVERSA_DE_GRUPO_OU_LISTA) or not _so_digitos(conversa):
        return None
    conteudo = _tipo_e_texto(dados)
    if conteudo is None:
        return None
    tipo, texto = conteudo
    return MensagemRecebida(
        id_evolution=id_evolution[:128],
        recebida_em=_instante(dados, agora),
        remetente=_remetente(chave, conversa),
        nome_informado=limpar_texto(dados.get("pushName"), TAMANHO_MAXIMO_NOME),
        tipo=tipo,
        texto=texto,
    )
