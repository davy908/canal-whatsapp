"""Conversa com o Evolution 2.3.7, sempre e só sobre a instância `canal-ia`.

O nome da instância é fixo no código para este serviço nunca alcançar a instância de outro uso. A
chave é a da própria instância: mesmo vazando, ela não abre as outras. Não existe caminho de envio
aqui, de propósito: um teste confere a lista completa de caminhos usados.
"""
import httpx

from mensagem import INSTANCIA

TIMEOUT_SEGUNDOS = 10
EVENTOS = ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
AJUSTES_DA_INSTANCIA = {
    "rejectCall": False,
    "msgCall": "",
    "groupsIgnore": True,  # grupo traz conversa de quem nem sabe que este número é lido
    "alwaysOnline": False,
    "readMessages": False,  # sem o visto azul: ler aqui não avisa ninguém nem muda nada no celular
    "readStatus": False,
    "syncFullHistory": False,  # conectar não puxa as conversas antigas
}


class EvolutionFora(Exception):
    """O Evolution não respondeu ou respondeu erro. Sem detalhes: resposta dele pode ter a chave."""


class ChaveGeralRecusada(Exception):
    """A chave configurada enxerga outras instâncias: é a geral, e este serviço não a aceita."""


class Evolution:
    def __init__(self, url: str, token: str, transporte: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=url,
            headers={"apikey": token},
            timeout=TIMEOUT_SEGUNDOS,
            follow_redirects=False,  # um redirecionamento troca POST por GET e perde o corpo
            transport=transporte,
        )

    def _pedir(self, metodo: str, caminho: str, **opcoes) -> httpx.Response:
        try:
            resposta = self._http.request(metodo, caminho, **opcoes)
        except httpx.HTTPError as erro:
            raise EvolutionFora(type(erro).__name__) from None
        if resposta.status_code >= 500 or 300 <= resposta.status_code < 400 or resposta.status_code in (401, 403):
            raise EvolutionFora(f"HTTP {resposta.status_code}")
        return resposta

    def estado(self) -> str | None:
        """'open', 'connecting' ou 'close'. None se a instância ainda não foi criada no Evolution."""
        resposta = self._pedir("GET", f"/instance/connectionState/{INSTANCIA}")
        if resposta.status_code == 404:
            return None
        if not resposta.is_success:
            raise EvolutionFora(f"HTTP {resposta.status_code}")
        dados = _json(resposta)
        instancia = dados.get("instance") if isinstance(dados, dict) else None
        return instancia.get("state") if isinstance(instancia, dict) else None

    def numero_conectado(self) -> str | None:
        """Número dono da conexão, ou None. Recusa de vez se a chave enxerga outra instância."""
        resposta = self._pedir("GET", "/instance/fetchInstances")
        if not resposta.is_success:
            raise EvolutionFora(f"HTTP {resposta.status_code}")
        instancias = _json(resposta)
        if not isinstance(instancias, list):
            raise EvolutionFora("resposta inesperada")
        if any(isinstance(i, dict) and i.get("name") != INSTANCIA for i in instancias):
            raise ChaveGeralRecusada()
        for instancia in instancias:
            if isinstance(instancia, dict) and instancia.get("name") == INSTANCIA:
                dono = instancia.get("ownerJid")
                return dono if isinstance(dono, str) and dono else None
        return None

    def preparar(self, url_webhook: str, segredo_webhook: str) -> None:
        """Aponta o aviso para este serviço e aplica os ajustes. Pode repetir à vontade."""
        self.numero_conectado()  # antes de gravar qualquer coisa: barra a chave geral
        self._gravar(
            f"/webhook/set/{INSTANCIA}",
            {
                "webhook": {
                    "enabled": True,
                    "url": url_webhook,
                    "headers": {"Authorization": f"Bearer {segredo_webhook}"},
                    "byEvents": False,
                    "base64": False,  # o arquivo em si nunca chega aqui
                    "events": EVENTOS,
                }
            },
        )
        self._gravar(f"/settings/set/{INSTANCIA}", AJUSTES_DA_INSTANCIA)

    def _gravar(self, caminho: str, corpo: dict) -> None:
        resposta = self._pedir("POST", caminho, json=corpo)
        if not resposta.is_success:
            raise EvolutionFora(f"HTTP {resposta.status_code}")

    def pedir_qr(self) -> str | None:
        """Imagem do QR em base64 (data URL), ou None se o Evolution ainda não gerou um."""
        resposta = self._pedir("GET", f"/instance/connect/{INSTANCIA}")
        if not resposta.is_success:
            raise EvolutionFora(f"HTTP {resposta.status_code}")
        dados = _json(resposta)
        if not isinstance(dados, dict):
            return None
        qr = dados.get("qrcode") if isinstance(dados.get("qrcode"), dict) else dados
        imagem = qr.get("base64")
        if not isinstance(imagem, str) or not imagem:
            return None
        return imagem if imagem.startswith("data:image/") else f"data:image/png;base64,{imagem}"

    def desconectar(self) -> None:
        """Desliga o número da instância. Já desligado responde erro 400, e isso não é falha."""
        self._pedir("DELETE", f"/instance/logout/{INSTANCIA}")


def _json(resposta: httpx.Response) -> object:
    try:
        return resposta.json()
    except ValueError:
        raise EvolutionFora("resposta sem JSON") from None
