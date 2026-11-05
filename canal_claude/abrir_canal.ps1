# Abre uma conversa do Claude que recebe os seus pedidos do WhatsApp na hora. Deixe a janela aberta
# (pode minimizar). Fechou a janela, o canal para; os pedidos esperam na VPS até você abrir de novo.
#
#   powershell -ExecutionPolicy Bypass -File canal-whatsapp\canal_claude\abrir_canal.ps1
#
# Na primeira vez o Claude pergunta se confia na pasta, se pode usar o servidor "whatsapp" e se aceita
# o canal em teste: responda que sim nas três.

param([string]$PastaDeTrabalho = 'D:\Projetos')

$ErrorActionPreference = 'Stop'
$base = Join-Path $env:LOCALAPPDATA 'CanalWhatsapp'
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

$config = @{ mcpServers = @{ whatsapp = @{ command = 'node'; args = @((Join-Path $programa 'servidor.mjs')) } } }
$json = $config | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $sessao '.mcp.json'), $json, (New-Object Text.UTF8Encoding $false)) # sem BOM: JSON não aceita

$versao = [version](((claude --version) -split ' ')[0])
if ($versao -lt $versaoMinima) {
    Write-Host "Aviso: seu Claude Code é $versao. As aprovações só chegam ao WhatsApp a partir da $versaoMinima."
    Write-Host 'Para atualizar: claude update'
}

$Host.UI.RawUI.WindowTitle = 'Claude - canal do WhatsApp (deixe aberto)'
Set-Location $sessao
claude --dangerously-load-development-channels server:whatsapp --add-dir $PastaDeTrabalho
