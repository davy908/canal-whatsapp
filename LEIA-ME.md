# Canal de WhatsApp (só leitura)

O Claude consegue ver se um número está conectado, pegar o QR e ler as mensagens que esse número recebe.
Ele **não consegue enviar nada**: essa ferramenta não existe aqui.

## O que acontece quando chega uma mensagem

1. O Evolution avisa este serviço, que roda na VPS.
2. O serviço guarda só o remetente, o nome informado, o horário, o tipo e o texto ou a legenda.
3. O Claude lê quando for pedido, com um aviso de que aquilo foi escrito por outra pessoa.

Ficam de fora: grupos, status, mensagens enviadas pelo próprio número, histórico antigo e arquivos.

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

Se a chave de leitura vazar, rode `preparar_chaves.ps1` de novo, cole as novas no EasyPanel e implante.

## Cuidados que continuam valendo

- **Banimento:** o Evolution não é oficial, e o WhatsApp pode banir o número.
- **Mensagem é conteúdo de estranho:** qualquer pessoa pode escrever um texto tentando enganar o Claude. As mensagens vêm marcadas e o serviço não age por elas, mas o Claude pode ter outras ferramentas na mesma conversa. Se ele disser que uma mensagem pede algo, é você quem decide.

## Para quem for mexer no código

- Testes: `uv run pytest` nesta pasta. Usam um dublê do Evolution 2.3.7.
- Depois de mudar dependência: `uv lock` e `uv export --no-dev --format requirements-txt --no-emit-project -o requirements.txt`.
- Antes de atualizar o Evolution para a 2.4, confira a nota de licença em `CRM-claude/ata/24-mudancas-de-configuracao.md`.
