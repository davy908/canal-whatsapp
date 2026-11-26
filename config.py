"""Configuração do serviço: tudo vem das variáveis do painel do EasyPanel.

O código só conhece o NOME das variáveis. Sem segredo forte o serviço não sobe, para nunca ficar
aberto por esquecimento.

Dois modos:
- Uma pessoa (sem CANAL_PESSOAS): as variáveis de sempre, instância `canal-ia`, banco /data/canal.db.
- Várias pessoas (CANAL_PESSOAS=davy,danilo): cada uma com as variáveis CANAL_<NOME>_*, a própria
  instância no Evolution, o próprio banco e a própria chave. A chave decide de quem são as mensagens.
  O Ambiente guarda só o SHA-256 da chave e da senha do painel: quem abre o EasyPanel não consegue usá-las.
"""
import hashlib
import os
import re
from dataclasses import dataclass, field

TAMANHO_MINIMO_SEGREDO = 32
NUMERO_INSTINCT_PADRAO = "16508702892"  # o assistente que avisa o Davy; só no modo de uma pessoa
INSTANCIA_PADRAO = "canal-ia"
DONO_PADRAO = "davy"
INSTINCT = "instinct"
RESERVADOS = (DONO_PADRAO, INSTINCT)
NOME_DE_CONTATO = re.compile(r"[a-z][a-z0-9_-]{0,29}")  # começa com letra: nunca parece um número
NOME_DE_INSTANCIA = re.compile(r"[A-Za-z0-9_-]{1,64}")  # vai no caminho da URL do Evolution
HASH_SHA256 = re.compile(r"[0-9a-f]{64}")
PASTA_DADOS = "/data"


class ConfiguracaoInvalida(Exception):
    """Falta variável ou o valor é fraco. A mensagem cita só o nome da variável."""


def resumo_do_segredo(segredo: str) -> str:
    """SHA-256 em hexadecimal minúsculo: é o que vai no Ambiente no modo de várias pessoas."""
    return hashlib.sha256(segredo.encode()).hexdigest()


@dataclass(frozen=True)
class Config:
    """O canal de UMA pessoa. No modo de várias pessoas, o serviço tem um Config por pessoa."""

    evolution_url: str
    evolution_token: str
    numero_esperado: str
    url_webhook: str
    caminho_banco: str
    dias_guarda: int
    chave_leitura: str = ""  # modo de uma pessoa: a chave em si
    senha_painel: str = ""
    numero_instinct: str = ""
    contatos: dict[str, str] = field(default_factory=dict)
    contatos_webhook: tuple[str, ...] = ()
    nome: str = DONO_PADRAO  # como o dono aparece no fio: destino "ele mesmo" e origem do que ele digita
    instancia: str = INSTANCIA_PADRAO
    hash_chave: str = ""  # modo de várias pessoas: só o resumo
    hash_senha: str = ""

    def resumo_da_chave(self) -> str:
        return self.hash_chave or resumo_do_segredo(self.chave_leitura)

    def resumo_da_senha(self) -> str:
        return self.hash_senha or resumo_do_segredo(self.senha_painel)

    def numeros_webhook(self) -> dict[str, str]:
        """Contatos de CANAL_CONTATOS_WEBHOOK: as mensagens deles acordam o canal como se fossem do dono,
        e o Claude pode responder a eles sozinho (pedido do Davy, 24/nov/2026). O resto só fica guardado."""
        return {nome: self.contatos[nome] for nome in self.contatos_webhook}

    def destinos(self) -> dict[str, str]:
        """O dono e o Instinct: as conversas DELE que o canal guarda (inclusive o que ele mesmo digita)."""
        return {self.nome: self.numero_esperado, INSTINCT: self.numero_instinct}

    def destinos_de_envio(self) -> dict[str, str]:
        """Os únicos números para onde este canal envia: o dono, o Instinct e a lista fechada de
        CANAL_CONTATOS (pedido do Davy, 24/nov/2026). O Claude escolhe pelo nome, nunca pelo número.
        O que o dono digita para um contato continua fora do canal: só `destinos()` decide isso."""
        return {**self.contatos, **self.destinos()}


def _segredo(ambiente: dict, nome: str) -> str:
    valor = ambiente.get(nome, "").strip()
    if len(valor) < TAMANHO_MINIMO_SEGREDO:
        raise ConfiguracaoInvalida(f"{nome} ausente ou curta: precisa de {TAMANHO_MINIMO_SEGREDO}+ caracteres")
    return valor


def _resumo(ambiente: dict, nome: str) -> str:
    valor = ambiente.get(nome, "").strip().lower()
    if not HASH_SHA256.fullmatch(valor):
        raise ConfiguracaoInvalida(f"{nome} ausente: use o SHA-256 (64 letras e números) gerado pelo preparar_chaves.ps1")
    return valor


def _numero(ambiente: dict, nome: str, padrao: str = "") -> str:
    numero = "".join(c for c in ambiente.get(nome, padrao) if c.isdigit())
    if len(numero) < 10:
        raise ConfiguracaoInvalida(f"{nome} ausente: use DDI + DDD + número")
    return numero


def _numero_opcional(ambiente: dict, nome: str) -> str:
    return _numero(ambiente, nome) if ambiente.get(nome, "").strip() else ""


def _contatos(ambiente: dict, variavel: str = "CANAL_CONTATOS", reservados: tuple[str, ...] = RESERVADOS) -> dict[str, str]:
    """CANAL_CONTATOS=andre:5511999990000;lisa:5524999990000. O erro cita o nome, nunca o número."""
    contatos: dict[str, str] = {}
    for item in ambiente.get(variavel, "").split(";"):
        if not item.strip():
            continue
        nome, separador, numero = item.partition(":")
        nome = nome.strip().lower()
        if not separador or not NOME_DE_CONTATO.fullmatch(nome):
            raise ConfiguracaoInvalida(f"{variavel}: use nome:numero separados por ponto e vírgula (nome começa com letra; só letras sem acento, números, - e _)")
        if nome in reservados or nome in contatos:
            raise ConfiguracaoInvalida(f"{variavel}: o nome '{nome}' está repetido ou é reservado")
        digitos = "".join(c for c in numero if c.isdigit())
        if len(digitos) < 10:
            raise ConfiguracaoInvalida(f"{variavel}: o número de '{nome}' precisa de DDI + DDD + número")
        contatos[nome] = digitos
    return contatos


def _contatos_webhook(ambiente: dict, contatos: dict[str, str], variavel: str = "CANAL_CONTATOS_WEBHOOK", agenda: str = "CANAL_CONTATOS") -> tuple[str, ...]:
    """CANAL_CONTATOS_WEBHOOK=andre,lisa: só nomes, que precisam estar em CANAL_CONTATOS. Vazio: ninguém."""
    nomes: list[str] = []
    for item in re.split(r"[,;]", ambiente.get(variavel, "")):
        nome = item.strip().lower()
        if not nome:
            continue
        if nome not in contatos:
            raise ConfiguracaoInvalida(f"{variavel}: '{nome}' não está em {agenda}")
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


def _comuns(ambiente: dict) -> dict:
    # Endereços internos da rede do EasyPanel: nem o Evolution nem o webhook passam pela internet.
    return {
        "evolution_url": ambiente.get("EVOLUTION_URL", "http://acelera_so_evolution-api:8080").rstrip("/"),
        "url_webhook": ambiente.get("CANAL_URL_WEBHOOK", "http://acelera_so_canal-whatsapp:8000/webhook/evolution"),
        "dias_guarda": _dias_guarda(ambiente),
    }


def carregar(ambiente: dict | None = None) -> Config:
    """Modo de uma pessoa: as variáveis de sempre."""
    ambiente = os.environ if ambiente is None else ambiente
    contatos = _contatos(ambiente)
    return Config(
        **_comuns(ambiente),
        evolution_token=ambiente.get("EVOLUTION_TOKEN_INSTANCIA", "").strip() or _faltando("EVOLUTION_TOKEN_INSTANCIA"),
        chave_leitura=_segredo(ambiente, "CANAL_CHAVE_LEITURA"),
        senha_painel=_segredo(ambiente, "CANAL_SENHA_PAINEL"),
        numero_esperado=_numero(ambiente, "CANAL_NUMERO_ESPERADO"),
        caminho_banco=ambiente.get("CANAL_BANCO", f"{PASTA_DADOS}/canal.db"),
        numero_instinct=_numero(ambiente, "CANAL_NUMERO_INSTINCT", NUMERO_INSTINCT_PADRAO),
        contatos=contatos,
        contatos_webhook=_contatos_webhook(ambiente, contatos),
    )


def carregar_pessoas(ambiente: dict | None = None) -> list[Config]:
    """Sem CANAL_PESSOAS, o serviço roda como sempre rodou, para uma pessoa só."""
    ambiente = os.environ if ambiente is None else ambiente
    if not ambiente.get("CANAL_PESSOAS", "").strip():
        return [carregar(ambiente)]
    comuns = _comuns(ambiente)
    pessoas = [_carregar_pessoa(ambiente, nome, comuns) for nome in _nomes_das_pessoas(ambiente)]
    _sem_repeticao(pessoas)
    return pessoas


def _nomes_das_pessoas(ambiente: dict) -> list[str]:
    nomes: list[str] = []
    for item in re.split(r"[,;]", ambiente["CANAL_PESSOAS"]):
        nome = item.strip().lower()
        if not nome:
            continue
        if not NOME_DE_CONTATO.fullmatch(nome) or nome == INSTINCT:
            raise ConfiguracaoInvalida("CANAL_PESSOAS: nomes separados por vírgula (começam com letra; só letras sem acento, números, - e _; 'instinct' é reservado)")
        if nome in nomes:
            raise ConfiguracaoInvalida(f"CANAL_PESSOAS: '{nome}' está repetido")
        nomes.append(nome)
    return nomes


def prefixo_da_pessoa(nome: str) -> str:
    return "CANAL_" + nome.upper().replace("-", "_") + "_"


def _carregar_pessoa(ambiente: dict, nome: str, comuns: dict) -> Config:
    p = prefixo_da_pessoa(nome)
    instancia = ambiente.get(p + "INSTANCIA", "").strip() or f"canal-{nome}"
    if not NOME_DE_INSTANCIA.fullmatch(instancia):
        raise ConfiguracaoInvalida(f"{p}INSTANCIA: só letras sem acento, números, - e _")
    contatos = _contatos(ambiente, p + "CONTATOS", reservados=(nome, INSTINCT))
    return Config(
        **comuns,
        nome=nome,
        instancia=instancia,
        evolution_token=ambiente.get(p + "EVOLUTION_TOKEN", "").strip() or _faltando(p + "EVOLUTION_TOKEN"),
        hash_chave=_resumo(ambiente, p + "CHAVE_HASH"),
        hash_senha=_resumo(ambiente, p + "SENHA_PAINEL_HASH"),
        numero_esperado=_numero(ambiente, p + "NUMERO"),
        caminho_banco=ambiente.get(p + "BANCO", "").strip() or f"{PASTA_DADOS}/{nome}.db",
        numero_instinct=_numero_opcional(ambiente, p + "NUMERO_INSTINCT"),
        contatos=contatos,
        contatos_webhook=_contatos_webhook(ambiente, contatos, p + "CONTATOS_WEBHOOK", p + "CONTATOS"),
    )


def _sem_repeticao(pessoas: list[Config]) -> None:
    """Duas pessoas com a mesma instância, banco ou chave leriam a caixa uma da outra."""
    campos = {
        "INSTANCIA": lambda c: c.instancia,
        "EVOLUTION_TOKEN": lambda c: c.evolution_token,
        "BANCO": lambda c: os.path.normpath(c.caminho_banco),
        "CHAVE_HASH": lambda c: c.hash_chave,
        "SENHA_PAINEL_HASH": lambda c: c.hash_senha,
        "NUMERO": lambda c: c.numero_esperado,
    }
    for sufixo, valor in campos.items():
        vistos: dict[str, str] = {}
        for pessoa in pessoas:
            chave = valor(pessoa)
            if chave in vistos:
                raise ConfiguracaoInvalida(
                    f"{prefixo_da_pessoa(vistos[chave])}{sufixo} e {prefixo_da_pessoa(pessoa.nome)}{sufixo} são iguais: cada pessoa precisa do seu"
                )
            vistos[chave] = pessoa.nome


def _faltando(nome: str) -> str:
    raise ConfiguracaoInvalida(f"{nome} ausente")
