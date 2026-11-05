// O vaivém do canal: busca pedidos no serviço da VPS, entrega ao Claude e leva as aprovações ao WhatsApp.
// Recebe a rede e o MCP por fora (servico, notificar) para os testes rodarem sem nenhum dos dois.
import { entender, mensagemDeAprovacao } from "./logica.mjs";

const VALIDADE_APROVACAO_MS = 30 * 60 * 1000; // aprovação velha não vale: o Claude já seguiu ou desistiu

export class Canal {
  constructor({ servico, notificar, relogio = () => Date.now(), registrar = () => {} }) {
    this.servico = servico; // { pegarPedidos(), enviar(para, texto) }
    this.notificar = notificar; // (method, params) => Promise
    this.relogio = relogio;
    this.registrar = registrar;
    this.aprovacoesAbertas = new Map(); // código -> quando foi pedida
  }

  async rodada() {
    const pedidos = await this.servico.pegarPedidos();
    for (const pedido of pedidos) {
      await this.#tratar(pedido);
    }
    return pedidos.length;
  }

  async #tratar(pedido) {
    const entendido = entender(pedido.texto);
    if (entendido.tipo === "aprovacao") {
      await this.#responderAprovacao(entendido);
    } else if (entendido.tipo === "pedido") {
      this.registrar(`pedido ${pedido.id} entregue`);
      await this.notificar("notifications/claude/channel", {
        content: entendido.texto,
        meta: { pedido_id: String(pedido.id), hora: String(pedido.recebida_em ?? "") },
      });
    }
  }

  async #responderAprovacao({ codigo, comportamento }) {
    const pedidaEm = this.aprovacoesAbertas.get(codigo);
    if (pedidaEm === undefined || this.relogio() - pedidaEm > VALIDADE_APROVACAO_MS) {
      this.aprovacoesAbertas.delete(codigo);
      await this.servico.enviar("davy", `🤖 Não tem aprovação aberta com o código ${codigo}.`);
      return;
    }
    this.aprovacoesAbertas.delete(codigo);
    this.registrar(`aprovacao ${codigo} ${comportamento}`);
    await this.notificar("notifications/claude/channel/permission", { request_id: codigo, behavior: comportamento });
  }

  async pedidoDeAprovacao(params) {
    const codigo = String(params.request_id ?? "").toLowerCase();
    if (!/^[a-km-z]{5}$/.test(codigo)) return;
    this.aprovacoesAbertas.set(codigo, this.relogio());
    await this.servico.enviar("davy", mensagemDeAprovacao({ ...params, request_id: codigo }));
  }
}
