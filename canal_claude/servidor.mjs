// Canal do Claude Code para o WhatsApp do Davy. O Claude Code abre este programa e fica escutando.
//
//   Abrir: powershell -ExecutionPolicy Bypass -File canal-whatsapp\canal_claude\abrir_canal.ps1
//
// Não abre porta nenhuma: quem pergunta é este programa, à VPS, a cada poucos segundos, e isso não
// gasta uso do Claude. A chave é lida pelo nome (CANAL_WHATSAPP_CHAVE) e nunca vai para log.
import { execFileSync } from "node:child_process";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import { Canal } from "./canal.mjs";
import { INSTRUCOES } from "./logica.mjs";

const INTERVALO_MS = 4000;
const ESPERA_DEPOIS_DE_ERRO_MS = 30000;
const TIMEOUT_MS = 15000;

function registrar(texto) {
  process.stderr.write(`[canal-whatsapp] ${new Date().toISOString()} ${texto}\n`); // stdout é do MCP
}

function lerVariavel(nome) {
  const doAmbiente = (process.env[nome] ?? "").trim();
  if (doAmbiente || process.platform !== "win32") return doAmbiente;
  try {
    // Terminal aberto antes de a chave existir não a herdou: lê das variáveis do usuário.
    const saida = execFileSync("reg", ["query", "HKCU\\Environment", "/v", nome], { encoding: "utf8", windowsHide: true });
    const linha = saida.split(/\r?\n/).find((l) => l.trim().startsWith(nome));
    return linha ? linha.trim().split(/\s{2,}/).slice(2).join(" ").trim() : "";
  } catch {
    return "";
  }
}

function criarServico() {
  const base = lerVariavel("CANAL_WHATSAPP_URL").replace(/\/+$/, "");
  const chave = lerVariavel("CANAL_WHATSAPP_CHAVE");
  if (!base.startsWith("https://") || !chave) {
    throw new Error("Faltam CANAL_WHATSAPP_URL (https) e CANAL_WHATSAPP_CHAVE. Veja o LEIA-ME do canal.");
  }
  async function postar(caminho, corpo) {
    const resposta = await fetch(base + caminho, {
      method: "POST",
      headers: { Authorization: `Bearer ${chave}`, "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
      redirect: "error",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!resposta.ok) throw new Error(`serviço respondeu HTTP ${resposta.status}`);
    return resposta.json();
  }
  return {
    async pegarPedidos() {
      return (await postar("/api/pedidos/pegar", {})).pedidos ?? [];
    },
    async enviar(para, texto) {
      return postar("/api/enviar", { para, texto });
    },
  };
}

const servico = criarServico();
const mcp = new Server(
  { name: "whatsapp", version: "1.0.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {}, "claude/channel/permission": {} },
      tools: {},
    },
    instructions: INSTRUCOES,
  },
);
const canal = new Canal({
  servico,
  notificar: (method, params) => mcp.notification({ method, params }),
  registrar,
});

const FERRAMENTAS = [
  {
    name: "responder",
    description: "Responde ao Davy no WhatsApp, na conversa dele com ele mesmo. Texto curto e simples.",
    inputSchema: {
      type: "object",
      properties: { texto: { type: "string", minLength: 1, maxLength: 4000 } },
      required: ["texto"],
    },
  },
  {
    name: "avisar_instinct",
    description: "Manda ao Instinct um aviso curto para o celular do Davy tocar. Sem dados privados.",
    inputSchema: {
      type: "object",
      properties: { texto: { type: "string", minLength: 1, maxLength: 300 } },
      required: ["texto"],
    },
  },
];
const DESTINO = { responder: "davy", avisar_instinct: "instinct" };

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: FERRAMENTAS }));
mcp.setRequestHandler(CallToolRequestSchema, async (pedido) => {
  const para = DESTINO[pedido.params.name];
  const texto = String(pedido.params.arguments?.texto ?? "").trim();
  if (!para || !texto) {
    return { content: [{ type: "text", text: "Ferramenta ou texto inválido." }], isError: true };
  }
  try {
    const envio = await servico.enviar(para, texto);
    return { content: [{ type: "text", text: `Enviado (${envio.estado}).` }] };
  } catch (erro) {
    return { content: [{ type: "text", text: `Não consegui enviar: ${erro.message}` }], isError: true };
  }
});

const PedidoDeAprovacao = z.object({
  method: z.literal("notifications/claude/channel/permission_request"),
  params: z.object({
    request_id: z.string(),
    tool_name: z.string(),
    description: z.string().optional(),
    input_preview: z.string().optional(),
  }),
});
mcp.setNotificationHandler(PedidoDeAprovacao, async ({ params }) => {
  try {
    await canal.pedidoDeAprovacao(params);
  } catch (erro) {
    registrar(`aprovacao nao enviada: ${erro.message}`);
  }
});

async function escutar() {
  for (;;) {
    let espera = INTERVALO_MS;
    try {
      await canal.rodada();
    } catch (erro) {
      registrar(`falha ao buscar pedidos: ${erro.message}`);
      espera = ESPERA_DEPOIS_DE_ERRO_MS;
    }
    await new Promise((pronto) => setTimeout(pronto, espera));
  }
}

await mcp.connect(new StdioServerTransport());
registrar("canal ligado");
escutar();
