// Liga o servidor de verdade por stdio, como o Claude Code faz, apontando para um endereço que não existe.
import assert from "node:assert/strict";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

test("servidor sobe, declara o canal e oferece só as ferramentas de resposta", async () => {
  const transporte = new StdioClientTransport({
    command: process.execPath,
    args: [new URL("./servidor.mjs", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")],
    env: { ...process.env, CANAL_WHATSAPP_URL: "https://canal.invalid", CANAL_WHATSAPP_CHAVE: "chave-de-teste" },
    stderr: "pipe",
  });
  const cliente = new Client({ name: "teste", version: "1.0.0" });
  await cliente.connect(transporte);
  try {
    const capacidades = cliente.getServerCapabilities();
    assert.ok(capacidades.experimental["claude/channel"]);
    assert.ok(capacidades.experimental["claude/channel/permission"]);
    assert.match(cliente.getInstructions(), /responder/);
    const { tools } = await cliente.listTools();
    assert.deepEqual(tools.map((t) => t.name).sort(), ["avisar_instinct", "responder", "responder_contato"]);
    const semNome = await cliente.callTool({ name: "responder_contato", arguments: { texto: "x" } });
    assert.equal(semNome.isError, true);
    const ruim = await cliente.callTool({ name: "apagar", arguments: { texto: "x" } });
    assert.equal(ruim.isError, true);
  } finally {
    await cliente.close();
  }
});
