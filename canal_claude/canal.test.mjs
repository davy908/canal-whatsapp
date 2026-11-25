import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Canal } from "./canal.mjs";
import { entender, entenderContato, mensagemDeAprovacao } from "./logica.mjs";

function montar({ pedidos = [], agora = 1_000_000 } = {}) {
  const enviados = [];
  const notificacoes = [];
  const relogio = { agora };
  const fila = [...pedidos];
  const canal = new Canal({
    servico: {
      async pegarPedidos() {
        return fila.splice(0);
      },
      async enviar(para, texto) {
        enviados.push([para, texto]);
        return { estado: "enviada" };
      },
    },
    notificar: async (method, params) => notificacoes.push([method, params]),
    relogio: () => relogio.agora,
  });
  return { canal, enviados, notificacoes, relogio, fila };
}

test("tira o 'Claude' do começo e entrega o pedido", () => {
  assert.deepEqual(entender("Claude, resume meu dia"), { tipo: "pedido", texto: "resume meu dia" });
  assert.deepEqual(entender("  claude: oi"), { tipo: "pedido", texto: "oi" });
  assert.deepEqual(entender("Claude"), { tipo: "vazio" });
});

test("entende aprovação com o código de 5 letras", () => {
  assert.deepEqual(entender("Claude sim abcde"), { tipo: "aprovacao", codigo: "abcde", comportamento: "allow" });
  assert.deepEqual(entender("claude, não ABCDE"), { tipo: "aprovacao", codigo: "abcde", comportamento: "deny" });
  assert.deepEqual(entender("Claude nao abcde."), { tipo: "aprovacao", codigo: "abcde", comportamento: "deny" });
  // "l" não existe nos códigos, e frase maior não é aprovação: vira pedido comum.
  assert.equal(entender("Claude sim abcdl").tipo, "pedido");
  assert.equal(entender("Claude sim abcde e apaga tudo").tipo, "pedido");
});

test("pedido vira aviso do canal com o id", async () => {
  const { canal, notificacoes } = montar({ pedidos: [{ id: 7, recebida_em: "2030-01-01T00:00:00+00:00", texto: "Claude, oi" }] });
  assert.equal(await canal.rodada(), 1);
  assert.deepEqual(notificacoes, [
    ["notifications/claude/channel", { content: "oi", meta: { pedido_id: "7", hora: "2030-01-01T00:00:00+00:00", de: "davy", tipo: "pedido" } }],
  ]);
});

test("pedido de aprovação vai ao WhatsApp e a resposta volta ao Claude uma vez só", async () => {
  const { canal, enviados, notificacoes, fila } = montar();
  await canal.pedidoDeAprovacao({ request_id: "abcde", tool_name: "Bash", description: "rodar comando", input_preview: "git status" });
  assert.equal(enviados.length, 1);
  assert.match(enviados[0][1], /Claude sim abcde/);
  assert.match(enviados[0][1], /^🤖/); // não pode parecer um pedido do Davy
  fila.push({ id: 1, texto: "Claude sim abcde" }, { id: 2, texto: "Claude sim abcde" });
  await canal.rodada();
  assert.deepEqual(notificacoes, [["notifications/claude/channel/permission", { request_id: "abcde", behavior: "allow" }]]);
  assert.match(enviados.at(-1)[1], /Não tem aprovação aberta/);
});

test("aprovação com código desconhecido ou vencido não passa", async () => {
  const { canal, notificacoes, fila, relogio } = montar();
  fila.push({ id: 1, texto: "Claude sim zzzzz" });
  await canal.rodada();
  await canal.pedidoDeAprovacao({ request_id: "qwert", tool_name: "Bash" });
  relogio.agora += 31 * 60 * 1000;
  fila.push({ id: 2, texto: "Claude sim qwert" });
  await canal.rodada();
  assert.deepEqual(notificacoes, []);
});

test("código de aprovação fora do formato é ignorado", async () => {
  const { canal, enviados } = montar();
  await canal.pedidoDeAprovacao({ request_id: "../x", tool_name: "Bash" });
  assert.deepEqual(enviados, []);
});

test("mensagem de aprovação corta a prévia grande", () => {
  const texto = mensagemDeAprovacao({ request_id: "abcde", tool_name: "Write", input_preview: "x".repeat(5000) });
  assert.ok(texto.length < 1000);
});

test("o servidor declara o canal e a aprovação, e não imprime a chave", () => {
  const fonte = readFileSync(new URL("./servidor.mjs", import.meta.url), "utf8");
  assert.match(fonte, /"claude\/channel": \{\}/);
  assert.match(fonte, /"claude\/channel\/permission": \{\}/);
  assert.doesNotMatch(fonte, /registrar\([^)]*chave/);
  assert.doesNotMatch(fonte, /console\.log/); // stdout é do protocolo MCP
});


test("contato liberado: 'Claude ...' vira pedido, o resto vira mensagem", () => {
  assert.deepEqual(entenderContato("Claude segue"), { tipo: "pedido", texto: "segue" });
  assert.deepEqual(entenderContato("deu certo"), { tipo: "mensagem", texto: "deu certo" });
  assert.deepEqual(entenderContato("Claude"), { tipo: "mensagem", texto: "Claude" });
  assert.deepEqual(entenderContato("Claudete ligou"), { tipo: "mensagem", texto: "Claudete ligou" });
});

test("mensagem de contato chega com o nome e o tipo", async () => {
  const { canal, notificacoes } = montar({
    pedidos: [
      { id: 3, recebida_em: "h", tipo: "texto", texto: "deu certo", de: "andre", comando: false },
      { id: 4, recebida_em: "h", tipo: "texto", texto: "Claude segue", de: "andre", comando: true },
      { id: 5, recebida_em: "h", tipo: "imagem", texto: "", de: "andre", comando: false },
    ],
  });
  await canal.rodada();
  assert.deepEqual(
    notificacoes.map(([, p]) => [p.content, p.meta.de, p.meta.tipo, p.meta.formato]),
    [["deu certo", "andre", "mensagem", "texto"], ["segue", "andre", "pedido", "texto"], ["[imagem sem texto]", "andre", "mensagem", "imagem"]],
  );
});

test("contato não aprova: o código dele vira só mensagem", async () => {
  const { canal, notificacoes, fila } = montar();
  await canal.pedidoDeAprovacao({ request_id: "abcde", tool_name: "Bash" });
  fila.push({ id: 1, texto: "Claude sim abcde", de: "andre" });
  await canal.rodada();
  assert.equal(notificacoes.length, 1);
  assert.equal(notificacoes[0][0], "notifications/claude/channel"); // não é a de permissão
  assert.equal(notificacoes[0][1].meta.de, "andre");
  // A aprovação continua aberta para o Davy.
  fila.push({ id: 2, texto: "Claude sim abcde" });
  await canal.rodada();
  assert.deepEqual(notificacoes.at(-1), ["notifications/claude/channel/permission", { request_id: "abcde", behavior: "allow" }]);
});

test("metadados só com letras, números e _ (o Claude Code descarta o resto)", async () => {
  const { canal, notificacoes } = montar({ pedidos: [{ id: 9, texto: "oi", de: "andre" }] });
  await canal.rodada();
  for (const chave of Object.keys(notificacoes[0][1].meta)) assert.match(chave, /^[A-Za-z0-9_]+$/);
});
