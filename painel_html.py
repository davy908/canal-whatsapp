"""A página do Davy. Mostra só estado e QR, nunca mensagem: conteúdo de fora não entra nesta página."""

PAGINA_PAINEL = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canal WhatsApp</title>
<style nonce="__NONCE__">
  :root { color-scheme: light dark; --fundo: #f6f6f4; --cartao: #fff; --texto: #1c1c1a; --suave: #6b6b66; --borda: #deded9; --verde: #12714a; --vermelho: #a3261f; }
  @media (prefers-color-scheme: dark) { :root { --fundo: #161615; --cartao: #20201e; --texto: #efefe9; --suave: #a3a39c; --borda: #3a3a36; --verde: #4cc08d; --vermelho: #ef8a82; } }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px 16px; background: var(--fundo); color: var(--texto); font: 16px/1.5 system-ui, sans-serif; }
  main { max-width: 440px; margin: 0 auto; background: var(--cartao); border: 1px solid var(--borda); border-radius: 12px; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  #estado { font-weight: 600; margin: 12px 0; }
  .ok { color: var(--verde); } .ruim { color: var(--vermelho); }
  p { margin: 8px 0; } .suave { color: var(--suave); font-size: 14px; }
  #qr { display: none; width: 100%; max-width: 320px; margin: 12px auto; background: #fff; padding: 12px; border-radius: 8px; }
  button { font: inherit; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--borda); background: transparent; color: inherit; cursor: pointer; }
  #mostrar { background: var(--verde); border-color: var(--verde); color: #fff; width: 100%; }
  .acoes { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; border-top: 1px solid var(--borda); padding-top: 16px; }
  form { margin: 0; }
</style>
</head>
<body>
<main>
  <h1>Canal WhatsApp</h1>
  <p class="suave">Só leitura: daqui nada é enviado.</p>
  <p id="estado">Conferindo...</p>
  <p id="numero" class="suave"></p>
  <button id="mostrar" type="button" hidden>Mostrar QR para conectar</button>
  <img id="qr" alt="QR code para conectar o WhatsApp">
  <p id="dica" class="suave" hidden>Abra o WhatsApp do número combinado, vá em Aparelhos conectados e aponte a câmera. Não mostre este QR a ninguém.</p>
  <p id="guardadas" class="suave"></p>
  <div class="acoes">
    <form method="post" action="/painel/desconectar" data-pergunta="Desconectar o número deste serviço?"><button type="submit">Desconectar</button></form>
    <form method="post" action="/painel/apagar" data-pergunta="Apagar todas as mensagens guardadas? Não dá para desfazer."><button type="submit">Apagar mensagens</button></form>
  </div>
</main>
<script nonce="__NONCE__">
  const TEXTOS = {
    conectado: ["Conectado", "ok"],
    aguardando_qr: ["Esperando o QR ser escaneado", ""],
    desconectado: ["Desconectado", ""],
    conferindo_numero: ["Conectando, conferindo o número...", ""],
    instancia_nao_criada: ["A instância canal-ia ainda não existe no Evolution", "ruim"],
    numero_errado_desconectado: ["Número diferente do combinado: desconectei e nada foi guardado", "ruim"],
    chave_geral_recusada: ["A chave colocada é a geral do Evolution. Troque pela chave da instância canal-ia", "ruim"],
    evolution_indisponivel_ou_chave_errada: ["O Evolution não respondeu, ou a chave está errada", "ruim"],
  };
  const el = (id) => document.getElementById(id);
  let pedindoQr = false;

  function mostrarEstado(dados) {
    const [texto, classe] = TEXTOS[dados.estado] || ["Estado desconhecido", "ruim"];
    el("estado").textContent = texto;
    el("estado").className = classe;
    el("numero").textContent = dados.numero_final ? "Número terminado em " + dados.numero_final : "";
    const podeConectar = dados.estado === "desconectado" || dados.estado === "aguardando_qr";
    el("mostrar").hidden = !podeConectar || pedindoQr;
    if (!podeConectar) esconderQr();
    if (dados.mensagens_guardadas !== undefined) {
      el("guardadas").textContent = dados.mensagens_guardadas + " mensagem(ns) guardada(s). Apagadas sozinhas depois de " + dados.dias_guarda + " dias.";
    }
  }

  function esconderQr() {
    pedindoQr = false;
    el("qr").style.display = "none";
    el("qr").removeAttribute("src");
    el("dica").hidden = true;
  }

  async function atualizar() {
    const resposta = await fetch(pedindoQr ? "/painel/qr" : "/painel/situacao");
    if (!resposta.ok) return;
    const dados = await resposta.json();
    if (pedindoQr && dados.qr) {
      el("qr").src = dados.qr;
      el("qr").style.display = "block";
      el("dica").hidden = false;
    }
    mostrarEstado(dados);
  }

  el("mostrar").addEventListener("click", () => {
    pedindoQr = true;
    el("mostrar").hidden = true;
    atualizar();
  });
  document.querySelectorAll("form").forEach((formulario) => {
    formulario.addEventListener("submit", (evento) => {
      if (!window.confirm(formulario.dataset.pergunta)) evento.preventDefault();
    });
  });
  atualizar();
  setInterval(atualizar, 5000);
</script>
</body>
</html>
"""
