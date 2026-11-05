"""Configuração do serviço: tudo vem das variáveis do painel do EasyPanel.

O código só conhece o NOME das variáveis. Sem segredo forte o serviço não sobe, para nunca ficar
aberto por esquecimento.
"""
import os
from dataclasses import dataclass

TAMANHO_MINIMO_SEGREDO = 32
NUMERO_INSTINCT_PADRAO = "16508702892"  # o assistente que avisa o Davy; troca por CANAL_NUMERO_INSTINCT


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

    def destinos(self) -> dict[str, str]:
        """Os únicos números para onde este serviço envia. O Claude escolhe pelo nome, nunca pelo número."""
        return {"davy": self.numero_esperado, "instinct": self.numero_instinct}


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
    )


def _faltando(nome: str) -> str:
    raise ConfiguracaoInvalida(f"{nome} ausente")
