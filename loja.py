"""Guarda das mensagens num SQLite no volume do serviço.

SQLite porque são poucas mensagens, um único processo e nenhum outro sistema lê: não precisa de
migration em banco de produção, e apagar tudo é simples. O teto existe porque qualquer pessoa pode
escrever para o número: sem ele, alguém enche o disco da VPS que os outros serviços usam.
"""
import os
import secrets
import sqlite3
from dataclasses import asdict

from mensagem import MensagemRecebida

TETO_MENSAGENS = 5000
SEGUNDOS_POR_DIA = 86400

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensagens (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id_evolution TEXT NOT NULL UNIQUE,
    recebida_em INTEGER NOT NULL,
    remetente TEXT NOT NULL,
    nome_informado TEXT NOT NULL,
    tipo TEXT NOT NULL,
    texto TEXT NOT NULL,
    origem TEXT NOT NULL DEFAULT 'externo',
    conversa TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ajustes (nome TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agendadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    para TEXT NOT NULL,
    texto TEXT NOT NULL,
    enviar_em INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendente',
    criada_em INTEGER NOT NULL,
    atualizada_em INTEGER NOT NULL
);
"""
# Banco criado pela primeira versão, que só lia: ganha as colunas novas sem perder nada.
_COLUNAS_NOVAS = {"origem": "TEXT NOT NULL DEFAULT 'externo'", "conversa": "TEXT NOT NULL DEFAULT ''"}

PENDENTE, ENVIANDO, ENVIADA, FALHOU, CANCELADA = "pendente", "enviando", "enviada", "falhou", "cancelada"


class Loja:
    def __init__(self, caminho: str, dias_guarda: int):
        self._caminho = caminho
        self._prazo_segundos = dias_guarda * SEGUNDOS_POR_DIA
        pasta = os.path.dirname(caminho)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        with self._conexao() as banco:
            banco.executescript(_ESQUEMA)
            existentes = {linha["name"] for linha in banco.execute("PRAGMA table_info(mensagens)")}
            for nome, definicao in _COLUNAS_NOVAS.items():
                if nome not in existentes:
                    banco.execute(f"ALTER TABLE mensagens ADD COLUMN {nome} {definicao}")
        os.chmod(caminho, 0o600)

    def _conexao(self) -> sqlite3.Connection:
        banco = sqlite3.connect(self._caminho, timeout=10)
        banco.row_factory = sqlite3.Row
        banco.execute("PRAGMA secure_delete = ON")  # apagar sobrescreve o conteúdo no arquivo
        return banco

    def guardar(self, mensagem: MensagemRecebida) -> bool:
        """Idempotente: o Evolution reenvia avisos, e o id da mensagem impede duplicar."""
        with self._conexao() as banco:
            cursor = banco.execute(
                "INSERT OR IGNORE INTO mensagens"
                " (id_evolution, recebida_em, remetente, nome_informado, tipo, texto, origem, conversa)"
                " VALUES (:id_evolution, :recebida_em, :remetente, :nome_informado, :tipo, :texto, :origem, :conversa)",
                asdict(mensagem),
            )
            banco.execute(
                "DELETE FROM mensagens WHERE seq NOT IN (SELECT seq FROM mensagens ORDER BY seq DESC LIMIT ?)",
                (TETO_MENSAGENS,),
            )
            return cursor.rowcount == 1

    def listar(self, agora: int, limite: int, antes_de: int | None = None) -> tuple[list[dict], int | None]:
        """Da mais nova para a mais antiga. Devolve as mensagens e o cursor da próxima página."""
        corte = agora - self._prazo_segundos
        with self._conexao() as banco:
            linhas = banco.execute(
                "SELECT seq, recebida_em, remetente, nome_informado, tipo, texto, origem, conversa FROM mensagens"
                " WHERE recebida_em >= ? AND seq < ? ORDER BY seq DESC LIMIT ?",
                (corte, antes_de if antes_de is not None else 2**62, limite + 1),
            ).fetchall()
        pagina = [dict(linha) for linha in linhas[:limite]]
        return pagina, pagina[-1]["seq"] if len(linhas) > limite else None

    def apagar_vencidas(self, agora: int) -> int:
        corte = agora - self._prazo_segundos
        with self._conexao() as banco:
            banco.execute(
                "DELETE FROM agendadas WHERE estado IN (?, ?, ?) AND atualizada_em < ?",
                (ENVIADA, FALHOU, CANCELADA, corte),
            )
            return banco.execute("DELETE FROM mensagens WHERE recebida_em < ?", (corte,)).rowcount

    # --- envios agendados ---

    def agendar(self, para: str, texto: str, enviar_em: int, agora: int) -> int:
        with self._conexao() as banco:
            return banco.execute(
                "INSERT INTO agendadas (para, texto, enviar_em, estado, criada_em, atualizada_em) VALUES (?, ?, ?, ?, ?, ?)",
                (para, texto, enviar_em, PENDENTE, agora, agora),
            ).lastrowid

    def pegar_para_enviar(self, agora: int) -> list[dict]:
        """Marca como 'enviando' antes de enviar: se o serviço cair no meio, nada é enviado duas vezes."""
        with self._conexao() as banco:
            linhas = banco.execute(
                "SELECT id, para, texto, enviar_em FROM agendadas WHERE estado = ? AND enviar_em <= ? ORDER BY enviar_em, id",
                (PENDENTE, agora),
            ).fetchall()
            banco.executemany(
                "UPDATE agendadas SET estado = ?, atualizada_em = ? WHERE id = ? AND estado = ?",
                [(ENVIANDO, agora, linha["id"], PENDENTE) for linha in linhas],
            )
        return [dict(linha) for linha in linhas]

    def ha_vencida(self, agora: int) -> bool:
        with self._conexao() as banco:
            return banco.execute(
                "SELECT 1 FROM agendadas WHERE estado = ? AND enviar_em <= ? LIMIT 1", (PENDENTE, agora)
            ).fetchone() is not None

    def desistir_das_atrasadas(self, limite: int, agora: int) -> int:
        """Pendentes que passaram do limite sem conexão viram 'falhou': aviso velho não serve mais."""
        with self._conexao() as banco:
            return banco.execute(
                "UPDATE agendadas SET estado = ?, atualizada_em = ? WHERE estado = ? AND enviar_em < ?",
                (FALHOU, agora, PENDENTE, limite),
            ).rowcount

    def guardar_enviada(self, mensagem: MensagemRecebida) -> None:
        """Como guardar, mas se o aviso do Evolution chegou antes, corrige a origem para 'claude'."""
        with self._conexao() as banco:
            banco.execute(
                "INSERT INTO mensagens (id_evolution, recebida_em, remetente, nome_informado, tipo, texto, origem, conversa)"
                " VALUES (:id_evolution, :recebida_em, :remetente, :nome_informado, :tipo, :texto, :origem, :conversa)"
                " ON CONFLICT(id_evolution) DO UPDATE SET origem = excluded.origem, nome_informado = excluded.nome_informado",
                asdict(mensagem),
            )

    def marcar(self, id_agendada: int, estado: str, agora: int) -> None:
        with self._conexao() as banco:
            banco.execute("UPDATE agendadas SET estado = ?, atualizada_em = ? WHERE id = ?", (estado, agora, id_agendada))

    def cancelar(self, id_agendada: int, agora: int) -> bool:
        with self._conexao() as banco:
            return banco.execute(
                "UPDATE agendadas SET estado = ?, atualizada_em = ? WHERE id = ? AND estado = ?",
                (CANCELADA, agora, id_agendada, PENDENTE),
            ).rowcount == 1

    def agendada(self, id_agendada: int) -> dict | None:
        with self._conexao() as banco:
            linha = banco.execute(
                "SELECT id, para, texto, enviar_em, estado FROM agendadas WHERE id = ?", (id_agendada,)
            ).fetchone()
        return dict(linha) if linha else None

    def listar_agendadas(self, limite: int = 50) -> list[dict]:
        """Pendentes primeiro, pela hora de envio; depois as já resolvidas, das mais recentes."""
        with self._conexao() as banco:
            linhas = banco.execute(
                "SELECT id, para, texto, enviar_em, estado FROM agendadas"
                " ORDER BY estado != ?, CASE WHEN estado = ? THEN enviar_em ELSE -atualizada_em END, id LIMIT ?",
                (PENDENTE, PENDENTE, limite),
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def apagar_tudo(self) -> int:
        """Apaga as mensagens guardadas. Os envios agendados ficam: cancele-os um a um no painel."""
        with self._conexao() as banco:
            return banco.execute("DELETE FROM mensagens").rowcount

    def resumo(self, agora: int) -> dict:
        with self._conexao() as banco:
            linha = banco.execute(
                "SELECT COUNT(*) AS total, MAX(recebida_em) AS ultima FROM mensagens WHERE recebida_em >= ?",
                (agora - self._prazo_segundos,),
            ).fetchone()
        return {"mensagens_guardadas": linha["total"], "ultima_mensagem_em": linha["ultima"]}

    def segredo_webhook(self) -> str:
        """Criado uma vez e nunca mostrado: ninguém precisa conhecer, só este serviço e o Evolution."""
        with self._conexao() as banco:
            banco.execute(
                "INSERT OR IGNORE INTO ajustes (nome, valor) VALUES ('segredo_webhook', ?)",
                (secrets.token_urlsafe(32),),
            )
            return banco.execute("SELECT valor FROM ajustes WHERE nome = 'segredo_webhook'").fetchone()["valor"]
