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
    texto TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ajustes (nome TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


class Loja:
    def __init__(self, caminho: str, dias_guarda: int):
        self._caminho = caminho
        self._prazo_segundos = dias_guarda * SEGUNDOS_POR_DIA
        pasta = os.path.dirname(caminho)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        with self._conexao() as banco:
            banco.executescript(_ESQUEMA)
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
                "INSERT OR IGNORE INTO mensagens (id_evolution, recebida_em, remetente, nome_informado, tipo, texto)"
                " VALUES (:id_evolution, :recebida_em, :remetente, :nome_informado, :tipo, :texto)",
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
                "SELECT seq, recebida_em, remetente, nome_informado, tipo, texto FROM mensagens"
                " WHERE recebida_em >= ? AND seq < ? ORDER BY seq DESC LIMIT ?",
                (corte, antes_de if antes_de is not None else 2**62, limite + 1),
            ).fetchall()
        pagina = [dict(linha) for linha in linhas[:limite]]
        return pagina, pagina[-1]["seq"] if len(linhas) > limite else None

    def apagar_vencidas(self, agora: int) -> int:
        with self._conexao() as banco:
            return banco.execute(
                "DELETE FROM mensagens WHERE recebida_em < ?", (agora - self._prazo_segundos,)
            ).rowcount

    def apagar_tudo(self) -> int:
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
