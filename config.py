"""Configuração do serviço: tudo vem das variáveis do painel do EasyPanel.

O código só conhece o NOME das variáveis. Sem segredo forte o serviço não sobe, para nunca ficar
aberto por esquecimento.
"""
import os
import re
from dataclasses import dataclass, field

TAMANHO_MINIMO_SEGREDO = 32
NUMERO_INSTINCT_PADRAO = "16508702892"  # o assistente que avisa o Davy; troca por CANAL_NUMERO_INSTINCT
RESERVADOS = ("davy", "instinct")
NOME_DE_CONTATO = re.compile(r"[a-z][a-z0-9_-]{0,29}")  # começa com letra: nunca parece um número


class ConfiguracaoInvalida(Exception):
    """Falta variável ou o valor é fraco. A mensagem cita só o nome da variável."""


@dataclass(frozen=True)
class Config:
    evolution_url: str
    evolution_token: str
    chave_leitura: str
    senha_painel: str
    numero_esperado: str
    url_webhook: str
    caminho_banco: str
    dias_guarda: int
    numero_instinct: str = ""
    contatos: dict[str, str] = field(default_factory=dict)
    contatos_webhook: tuple[str, ...] = ()

    def numeros_webhook(self) -> dict[str, str]:
        """Contatos de CANAL_CONTATOS_WEBHOOK: as mensagens deles acordam o canal como se fossem do Davy,
        e o Claude pode responder a eles sozinho (pedido do Davy, 24/nov/2026). O resto só fica guardado."""
        return {nome: self.contatos[nome] for nome in self.contatos_webhook}

    def destinos(self) -> dict[str, str]:
        """O Davy e o Instinct: as conversas DELE que o canal guarda (inclusive o que ele mesmo digita)."""
        return {"davy": self.numero_esperado, "instinct": self.numero_instinct}

    def destinos_de_envio(self) -> dict[str, str]:
        """Os únicos números para onde este serviço envia: o Davy, o Instinct e a lista fechada de
        CANAL_CONTATOS (pedido do Davy, 24/nov/2026). O Claude escolhe pelo nome, nunca pelo número.
        O que o Davy digita para um contato continua fora do canal: só `destinos()` decide isso."""
        return {**self.contatos, **self.destinos()}


def _segredo(ambiente: dict, nome: str) -> str:
    valor = ambiente.get(nome, "").strip()
    if len(valor) < TAMANHO_MINIMO_SEGREDO:
        raise ConfiguracaoInvalida(f"{nome} ausente ou curta: precisa de {TAMANHO_MINIMO_SEGREDO}+ caracteres")
    return valor


def _numero(ambiente: dict, nome: str, padrao: str = "") -> str:
    numero = "".join(c for c in ambiente.get(nome, padrao) if c.isdigit())
    if len(numero) < 10:
        raise ConfiguracaoInvalida(f"{nome} ausente: use DDI + DDD + número")
    return numero


def _numero_esperado(ambiente: dict) -> str:
    return _numero(ambiente, "CANAL_NUMERO_ESPERADO")


def _contatos(ambiente: dict) -> dict[str, str]:
    """CANAL_CONTATOS=andre:5511999990000;lisa:5524999990000. O erro cita o nome, nunca o número."""
    contatos: dict[str, str] = {}
    for item in ambiente.get("CANAL_CONTATOS", "").split(";"):
        if not item.strip():
            continue
        nome, separador, numero = item.partition(":")
        nome = nome.strip().lower()
        if not separador or not NOME_DE_CONTATO.fullmatch(nome):
            raise ConfiguracaoInvalida("CANAL_CONTATOS: use nome:numero separados por ponto e vírgula (nome começa com letra; só letras sem acento, números, - e _)")
        if nome in RESERVADOS or nome in contatos:
            raise ConfiguracaoInvalida(f"CANAL_CONTATOS: o nome '{nome}' está repetido ou é reservado")
        digitos = "".join(c for c in numero if c.isdigit())
        if len(digitos) < 10:
            raise ConfiguracaoInvalida(f"CANAL_CONTATOS: o número de '{nome}' precisa de DDI + DDD + número")
        contatos[nome] = digitos
    return contatos


def _contatos_webhook(ambiente: dict, contatos: dict[str, str]) -> tuple[str, ...]:
    """CANAL_CONTATOS_WEBHOOK=andre,lisa: só nomes, que precisam estar em CANAL_CONTATOS. Vazio: ninguém."""
    nomes: list[str] = []
    for item in re.split(r"[,;]", ambiente.get("CANAL_CONTATOS_WEBHOOK", "")):
        nome = item.strip().lower()
        if not nome:
            continue
        if nome not in contatos:
            raise ConfiguracaoInvalida(f"CANAL_CONTATOS_WEBHOOK: '{nome}' não está em CANAL_CONTATOS")
        if nome not in nomes:
            nomes.append(nome)
    return tuple(nomes)


def _dias_guarda(ambiente: dict) -> int:
    try:
        dias = int(ambiente.get("CANAL_DIAS_GUARDA", "7"))
    except ValueError:
        raise ConfiguracaoInvalida("CANAL_DIAS_GUARDA precisa ser um número de dias") from None
    if not 1 <= dias <= 30:
        raise ConfiguracaoInvalida("CANAL_DIAS_GUARDA precisa ficar entre 1 e 30")
    return dias


def carregar(ambiente: dict | None = None) -> Config:
    ambiente = os.environ if ambiente is None else ambiente
    contatos = _contatos(ambiente)
    return Config(
        # Endereços internos da rede do EasyPanel: nem o Evolution nem o webhook passam pela internet.
        evolution_url=ambiente.get("EVOLUTION_URL", "http://acelera_so_evolution-api:8080").rstrip("/"),
        evolution_token=ambiente.get("EVOLUTION_TOKEN_INSTANCIA", "").strip() or _faltando("EVOLUTION_TOKEN_INSTANCIA"),
        chave_leitura=_segredo(ambiente, "CANAL_CHAVE_LEITURA"),
        senha_painel=_segredo(ambiente, "CANAL_SENHA_PAINEL"),
        numero_esperado=_numero_esperado(ambiente),
        url_webhook=ambiente.get("CANAL_URL_WEBHOOK", "http://acelera_so_canal-whatsapp:8000/webhook/evolution"),
        caminho_banco=ambiente.get("CANAL_BANCO", "/data/canal.db"),
        dias_guarda=_dias_guarda(ambiente),
        numero_instinct=_numero(ambiente, "CANAL_NUMERO_INSTINCT", NUMERO_INSTINCT_PADRAO),
        contatos=contatos,
        contatos_webhook=_contatos_webhook(ambiente, contatos),
    )


def _faltando(nome: str) -> str:
    raise ConfiguracaoInvalida(f"{nome} ausente")
