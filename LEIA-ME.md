# Canal de WhatsApp

O Claude consegue ver se o número está conectado, pegar o QR, ler mensagens e enviar texto.
**Ele só envia para dois destinos: para você mesmo e para o Instinct.** O número de cada um fica na VPS.
O Claude escolhe só "davy" ou "instinct", então não tem como mandar mensagem para mais ninguém.

## O que o Claude lê

- Mensagens que outras pessoas mandam para o seu número.
- A sua conversa com você mesmo (a conversa "Você" no WhatsApp).
- A conversa com o Instinct: o que você manda, o que ele responde e o que o Claude enviou.

Ficam de fora: o que você manda para outras pessoas, grupos, status, histórico antigo e arquivos.

## Pedir coisas ao Claude pelo celular

Na conversa **"Você"** do WhatsApp, escreva começando com **Claude**, por exemplo:
"Claude, me manda o resumo dos pedidos de ontem". Cada pedido sai uma vez só.

Quem atende é o **canal**: uma conversa do Claude aberta numa janela de terminal, que recebe o pedido em
poucos segundos e responde na conversa "Você". Para abrir (deixe a janela aberta, pode minimizar):

```bash
powershell -ExecutionPolicy Bypass -File canal_claude\abrir_canal.ps1
```

- Na primeira vez, o Claude pergunta na janela se confia na pasta, se aceita o canal em teste e se liga o
  Remote Control. Responda que sim. Se pedir login, digite `/login`.
- Com o Remote Control, a conversa aparece como **"Canal WhatsApp"** na barra lateral do app do Claude e no
  celular: dá para acompanhar e responder por lá com a janela minimizada. Outro nome: `-NomeNoApp "Debug X"`.
- O programa e a sessão ficam em `D:\Projetos\CanalWhatsapp` (fora do AppData: o que o app do Claude grava em
  `AppData\Local` vai para uma pasta privada dele, que a janela do terminal não enxerga).
- Quando o Claude precisar de aprovação, ela chega no WhatsApp com um código. Responda
  `Claude sim abcde` ou `Claude não abcde`. Também dá para aprovar na própria janela.
- Para o celular tocar quando ele terminar, o Claude manda um aviso curto ao Instinct.
- Janela fechada ou computador desligado: os pedidos esperam na VPS e são atendidos quando você abrir de novo.
- O canal é um recurso em teste do Claude Code e pode mudar. Precisa do Claude Code 2.1.234 ou mais novo
  para as aprovações irem ao WhatsApp (`claude update`).

O resto da conversa "Você" continua sendo anotação sua. Quem estiver com o seu celular desbloqueado
consegue pedir e aprovar: cuide dele.

### Contatos que acordam o canal

Por padrão, mensagem de outra pessoa ou do Instinct só fica guardada para leitura: nunca acorda o canal.
Para liberar alguém (por exemplo, para o Claude esperar o resultado de um teste do André e agir), ponha o
nome em `CANAL_CONTATOS_WEBHOOK`, no Ambiente do serviço. O nome precisa existir em `CANAL_CONTATOS`.

- **Toda** mensagem desse contato chega ao canal, marcada com o nome dele.
- Começando com **Claude** ("Claude segue"), chega como **pedido**: o Claude trata como pedido dessa pessoa,
  com a confiança que você deu, dentro do plano que você deixou na conversa.
- Sem "Claude" ("deu certo", "deu erro tal"), chega como **mensagem**: informação para o Claude seguir o plano.
- O Claude responde a esse contato sozinho, com a ferramenta `responder_contato`. A VPS recusa qualquer
  nome fora de `CANAL_CONTATOS_WEBHOOK`.
- **Aprovação continua só sua.** "Claude sim abcde" vindo do contato vira só mensagem.
- Libere só quem você confia: o que essa pessoa pede, o Claude faz. Para tirar, apague o nome e reimplante.

## O que acontece quando chega uma mensagem

1. O Evolution avisa este serviço, que roda na VPS.
2. O serviço guarda só o remetente, o nome informado, o horário, o tipo e o texto ou a legenda.
3. O Claude lê quando for pedido. Cada mensagem vem marcada pela origem: `externo` (outra pessoa ou o
   Instinct), `davy` (digitada no seu celular) ou `claude` (enviada pelo Claude).

## Envios

O Claude envia por nome, nunca por número: `davy`, `instinct` e os contatos de `CANAL_CONTATOS`
(`andre:5511999990000;lisa:5524999990000`, no Ambiente). Para os contatos, só quando você pede.

O Claude envia na hora ou agenda para um horário (horário de Brasília). Quem envia é a VPS, então
funciona com o computador desligado. No painel aparecem os envios, com um botão para cancelar os
agendados. Se o número estiver desconectado na hora, o envio espera; depois de um dia, desiste e
aparece como "Não foi enviado".

As mensagens são apagadas sozinhas depois de **7 dias**. O serviço guarda no máximo 5.000.
Se outro número escanear o QR, o serviço desconecta e não guarda nada.

## Colocar no ar (uma vez)

**1. Criar a instância no Evolution.** Abra
`https://acelera-so-evolution-api.izkl7m.easypanel.host/manager` e entre com a chave de sempre.
Crie a instância com o nome `canal-ia` e o canal Baileys. Copie a chave dessa instância (campo Token).
Use essa, **nunca a chave geral**: se colocar a geral, o serviço recusa e avisa no painel.

**2. Criar o serviço no EasyPanel.** No projeto `acelera_so`, crie um serviço App chamado
`canal-whatsapp`:

- **Fonte:** Upload, com o pacote desta pasta.
- **Domínios:** porta 8000.
- **Armazenamento:** Volume montado em `/data`.
- **Ambiente:** veja a lista abaixo.

**3. Gerar as chaves.** Rode no seu terminal. O programa copia cada chave para você colar no EasyPanel, sem mostrar na tela.

```bash
powershell -ExecutionPolicy Bypass -File canal-whatsapp\preparar_chaves.ps1 -EnderecoDoServico https://acelera-so-canal-whatsapp.izkl7m.easypanel.host
```

O Ambiente fica assim:

```text
EVOLUTION_TOKEN_INSTANCIA=(a chave copiada da instância canal-ia)
CANAL_CHAVE_LEITURA=(copiada pelo programa)
CANAL_SENHA_PAINEL=(copiada pelo programa)
CANAL_NUMERO_ESPERADO=(o número que vai conectar, com 55 e DDD)
CANAL_DIAS_GUARDA=7
```

O número do Instinct já vem no código. Para trocar, coloque `CANAL_NUMERO_INSTINCT` com DDI e DDD.

Depois, clique em **Implantar**.

**4. Dar as ferramentas ao Claude.**

```bash
powershell -ExecutionPolicy Bypass -File canal-whatsapp\instalar_mcp.ps1
```

## Conectar o número

1. Abra `https://acelera-so-canal-whatsapp.izkl7m.easypanel.host/painel`. Em usuário, escreva qualquer coisa. Em senha, use a senha do painel.
2. Clique em **Mostrar QR para conectar**.
3. No celular do número combinado: WhatsApp > Aparelhos conectados > Conectar um aparelho.
4. Aponte a câmera. O painel muda para **Conectado** e mostra o final do número.

Só escaneie com um número seu. Não mande esse QR para ninguém.

## Desconectar

Clique em **Desconectar** no painel. Também funciona pelo celular, em Aparelhos conectados.

## Apagar os dados

Clique em **Apagar mensagens** no painel. Isso apaga o que este serviço guardou e não dá para desfazer.

O Evolution também pode guardar mensagens no banco dele, conforme a configuração da instalação. Isso só some
quando a instância `canal-ia` é apagada no Manager.

## Desligar tudo

Faça nesta ordem:

1. No painel, clique em **Desconectar** e depois em **Apagar mensagens**.
2. No EasyPanel, apague o serviço `canal-whatsapp`. O volume vai junto.
3. No Manager do Evolution, apague a instância `canal-ia`. **Só essa**: as outras são do CRM e dos clientes.
4. Tire as ferramentas e a chave deste computador:

```bash
powershell -ExecutionPolicy Bypass -File canal-whatsapp\instalar_mcp.ps1 -Remover
```

## Se algo der errado

| O painel diz | O que fazer |
|---|---|
| A instância ainda não existe | Faça o passo 1, com o nome `canal-ia` exatamente assim |
| A chave colocada é a geral | Troque `EVOLUTION_TOKEN_INSTANCIA` pela chave da instância e implante de novo |
| O Evolution não respondeu, ou a chave está errada | Veja se o `evolution-api` está no ar e confira a chave |
| Número diferente do combinado | Escaneie com o número certo, ou corrija `CANAL_NUMERO_ESPERADO` |

Se a chave do canal vazar, rode `preparar_chaves.ps1` de novo, cole as novas no EasyPanel e implante.

## Cuidados que continuam valendo

- **Banimento:** o Evolution não é oficial, e o WhatsApp pode banir o número.
- **Mensagem é conteúdo de estranho:** qualquer pessoa pode escrever um texto tentando enganar o Claude. As mensagens vêm marcadas e o serviço não age por elas, mas o Claude pode ter outras ferramentas na mesma conversa. Se ele disser que uma mensagem pede algo, é você quem decide.
- **O que vai para o Instinct sai daqui:** o Instinct é um serviço de fora. Tudo o que o Claude manda para ele passa a estar lá.
- **A chave do canal agora também envia:** quem tiver `CANAL_WHATSAPP_CHAVE` pode mandar mensagem, mas só para você e para o Instinct.

## Várias pessoas no mesmo serviço

Um serviço só atende a equipe inteira. Cada pessoa tem a própria chave, e a chave decide de quem são as
mensagens, os envios e a agenda. O endereço do serviço é o mesmo para todos.

- **Cada pessoa continua com a própria instância no Evolution**, porque cada uma conecta o próprio número pelo QR.
- **Cada pessoa tem o próprio banco** em `/data`. "Apagar mensagens" no painel apaga só a caixa de quem entrou.
- **O Ambiente guarda só o SHA-256 da chave e da senha.** A chave mesmo fica só no PC da pessoa.
- **Sem `CANAL_PESSOAS`, o serviço roda como uma pessoa só**, com as variáveis de sempre. Implantar o código novo
  não muda nada até alguém pôr `CANAL_PESSOAS`.

### Pôr uma pessoa nova (exemplo: danilo)

1. **A pessoa gera as chaves no PC dela:**

   ```bash
   powershell -ExecutionPolicy Bypass -File canal-whatsapp\preparar_chaves.ps1 -EnderecoDoServico https://acelera-so-canal-whatsapp.izkl7m.easypanel.host -Nome danilo
   ```

   O programa pede para ela guardar a senha do painel e mostra duas linhas (`CANAL_DANILO_CHAVE_HASH=...` e
   `CANAL_DANILO_SENHA_PAINEL_HASH=...`), que ela manda para quem administra o EasyPanel.
2. **O administrador cria a instância `canal-danilo` no Manager do Evolution** e copia a chave dela.
3. **O administrador acrescenta no Ambiente do serviço:**

   ```text
   CANAL_PESSOAS=davy,danilo
   CANAL_DANILO_EVOLUTION_TOKEN=(a chave da instância canal-danilo)
   CANAL_DANILO_CHAVE_HASH=(a linha que a pessoa mandou)
   CANAL_DANILO_SENHA_PAINEL_HASH=(a linha que a pessoa mandou)
   CANAL_DANILO_NUMERO=(o número dela, com 55 e DDD)
   ```

   e implanta. A lista completa de variáveis por pessoa está no `.env.example`.
4. **A pessoa conecta o número** no `/painel` com a senha dela e instala as ferramentas no PC (`instalar_mcp.ps1`).

### Passar o serviço de hoje para o modo de várias pessoas

As variáveis de uma pessoa só deixam de valer quando `CANAL_PESSOAS` existe. Para o Davy não perder o QR nem
as mensagens, a parte dele fica assim:

```text
CANAL_DAVY_INSTANCIA=canal-ia
CANAL_DAVY_BANCO=/data/canal.db
CANAL_DAVY_EVOLUTION_TOKEN=(o mesmo valor de EVOLUTION_TOKEN_INSTANCIA)
CANAL_DAVY_NUMERO=(o mesmo valor de CANAL_NUMERO_ESPERADO)
CANAL_DAVY_NUMERO_INSTINCT=(o número do Instinct)
CANAL_DAVY_CONTATOS=(o mesmo valor de CANAL_CONTATOS, se tiver)
CANAL_DAVY_CONTATOS_WEBHOOK=(o mesmo valor de CANAL_CONTATOS_WEBHOOK, se tiver)
CANAL_DAVY_CHAVE_HASH=(SHA-256 da chave de leitura atual)
CANAL_DAVY_SENHA_PAINEL_HASH=(SHA-256 da senha do painel atual)
```

Para tirar o SHA-256 da chave atual sem mostrar a chave, rode no PowerShell do PC do Davy (a senha do painel
é igual, trocando a variável pelo valor guardado no gerenciador de senhas):

```powershell
$s=[Security.Cryptography.SHA256]::Create(); [BitConverter]::ToString($s.ComputeHash([Text.Encoding]::UTF8.GetBytes($env:CANAL_WHATSAPP_CHAVE))).Replace('-','').ToLower()
```

### O que continua valendo

- **Quem administra o EasyPanel consegue ler as mensagens de todo mundo:** os bancos estão no mesmo volume e as
  chaves das instâncias, no mesmo Ambiente. Avise a equipe.
- **Serviço fora do ar é fora do ar para todos.**
- **O webhook é um só** (`/webhook/evolution`). O campo `instance` do aviso escolhe a pessoa, e o aviso só entra se
  vier com o segredo DELA. Pela memória da equipe, o Evolution pode só aceitar webhook na criação da instância:
  se uma pessoa nova conectar e nada chegar, confira o webhook da instância no Manager.

## Para quem for mexer no código

- Testes: `uv run pytest` nesta pasta. Usam um dublê do Evolution 2.3.7.
- Depois de mudar dependência: `uv lock` e `uv export --no-dev --format requirements-txt --no-emit-project -o requirements.txt`.
- Antes de atualizar o Evolution para a 2.4, confira a nota de licença em `CRM-claude/ata/24-mudancas-de-configuracao.md`.
