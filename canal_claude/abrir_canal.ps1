# Abre uma conversa do Claude que recebe os seus pedidos do WhatsApp na hora. Deixe a janela aberta
# (pode minimizar). Fechou a janela, o canal para; os pedidos esperam na VPS até você abrir de novo.
#
#   powershell -ExecutionPolicy Bypass -File canal-whatsapp\canal_claude\abrir_canal.ps1
#
# Na primeira vez o Claude pergunta se confia na pasta, se aceita o canal em teste e se liga o Remote
# Control: responda que sim. Com o Remote Control, a conversa aparece com o nome abaixo na barra lateral
# do app do Claude e no celular, e dá para acompanhar e responder por lá com a janela minimizada.

param([string]$PastaDeTrabalho = 'D:\Projetos', [string]$NomeNoApp = 'Canal WhatsApp')

$ErrorActionPreference = 'Stop'

# Aberto a partir do app do Claude, o terminal herda as variáveis internas da conversa do app (login,
# endereço da API, marcador de "sessão filha") e o Claude da janela fica sem login. Tira só as herdadas:
# o que você mesmo configurou no Windows (usuário ou máquina) fica.
$herdadas = @(Get-ChildItem env: | Where-Object { $_.Name -match '^(CLAUDE|ANTHROPIC)' } | ForEach-Object { $_.Name })
foreach ($nome in $herdadas) {
    $doWindows = [Environment]::GetEnvironmentVariable($nome, 'User') -or [Environment]::GetEnvironmentVariable($nome, 'Machine')
    if (-not $doWindows) { [Environment]::SetEnvironmentVariable($nome, $null, 'Process') }
}

# Fora do AppData: o que o app do Claude grava em AppData\Local vai para a pasta privada dele, e a
# janela do terminal não enxerga (o canal-whatsapp falhava nela por isso).
$base = 'D:\Projetos\CanalWhatsapp'
$programa = Join-Path $base 'canal_claude'
$sessao = Join-Path $base 'sessao'
$versaoMinima = [version]'2.1.234' # antes disso, as aprovações não chegam ao WhatsApp

# Copia o programa para fora do projeto: atualizar ou apagar o projeto não derruba o canal.
New-Item -ItemType Directory -Force $programa, $sessao | Out-Null
foreach ($arquivo in 'servidor.mjs', 'canal.mjs', 'logica.mjs', 'package.json', 'package-lock.json') {
    Copy-Item (Join-Path $PSScriptRoot $arquivo) $programa -Force
}
Push-Location $programa
try {
    npm ci --ignore-scripts --omit=dev --no-audit --no-fund --loglevel=error | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Não consegui instalar as dependências do canal (npm ci).' }
} finally {
    Pop-Location
}

# O canal só é reconhecido num .mcp.json (servidor vindo do --mcp-config dá "no MCP server configured with
# that name" no Claude Code 2.1.319). O settings.local.json da pasta da sessão já aprova esse servidor, para
# não depender da pergunta de aprovação, que nem sempre aparecia.
$utf8SemBom = New-Object Text.UTF8Encoding $false # JSON não aceita BOM
$config = @{ mcpServers = @{ whatsapp = @{ command = 'node'; args = @((Join-Path $programa 'servidor.mjs')) } } }
[IO.File]::WriteAllText((Join-Path $sessao '.mcp.json'), ($config | ConvertTo-Json -Depth 5), $utf8SemBom)
$pastaAjustes = Join-Path $sessao '.claude'
New-Item -ItemType Directory -Force $pastaAjustes | Out-Null
$ajustes = @{ enabledMcpjsonServers = @('whatsapp') }
[IO.File]::WriteAllText((Join-Path $pastaAjustes 'settings.local.json'), ($ajustes | ConvertTo-Json -Depth 5), $utf8SemBom)
Remove-Item (Join-Path $base 'canal.mcp.json') -ErrorAction SilentlyContinue # versão anterior

$versao = [version](((claude --version) -split ' ')[0])
if ($versao -lt $versaoMinima) {
    Write-Host "Aviso: seu Claude Code é $versao. As aprovações só chegam ao WhatsApp a partir da $versaoMinima."
    Write-Host 'Para atualizar: claude update'
}

$Host.UI.RawUI.WindowTitle = 'Claude - canal do WhatsApp (deixe aberto)'
Set-Location $sessao
claude --dangerously-load-development-channels server:whatsapp --add-dir $PastaDeTrabalho --remote-control $NomeNoApp
