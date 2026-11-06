# Abre uma conversa do Claude que recebe os seus pedidos do WhatsApp na hora. Deixe a janela aberta
# (pode minimizar). Fechou a janela, o canal para; os pedidos esperam na VPS até você abrir de novo.
#
#   powershell -ExecutionPolicy Bypass -File canal-whatsapp\canal_claude\abrir_canal.ps1
#
# Na primeira vez o Claude pergunta se confia na pasta e se aceita o canal em teste: responda que sim.

param([string]$PastaDeTrabalho = 'D:\Projetos')

$ErrorActionPreference = 'Stop'

# Aberto a partir do app do Claude, o terminal herda as variáveis internas da conversa do app (login,
# endereço da API, marcador de "sessão filha") e o Claude da janela fica sem login. Tira só as herdadas:
# o que você mesmo configurou no Windows (usuário ou máquina) fica.
$herdadas = @(Get-ChildItem env: | Where-Object { $_.Name -match '^(CLAUDE|ANTHROPIC)' } | ForEach-Object { $_.Name })
foreach ($nome in $herdadas) {
    $doWindows = [Environment]::GetEnvironmentVariable($nome, 'User') -or [Environment]::GetEnvironmentVariable($nome, 'Machine')
    if (-not $doWindows) { [Environment]::SetEnvironmentVariable($nome, $null, 'Process') }
}

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

# O servidor vai pelo --mcp-config: num .mcp.json ele dependeria de uma aprovação que nem sempre aparece,
# e a janela abria sem o canal.
$config = @{ mcpServers = @{ whatsapp = @{ command = 'node'; args = @((Join-Path $programa 'servidor.mjs')) } } }
$json = $config | ConvertTo-Json -Depth 5
$arquivoConfig = Join-Path $base 'canal.mcp.json'
[IO.File]::WriteAllText($arquivoConfig, $json, (New-Object Text.UTF8Encoding $false)) # sem BOM: JSON não aceita
Remove-Item (Join-Path $sessao '.mcp.json') -ErrorAction SilentlyContinue # versão antiga

$versao = [version](((claude --version) -split ' ')[0])
if ($versao -lt $versaoMinima) {
    Write-Host "Aviso: seu Claude Code é $versao. As aprovações só chegam ao WhatsApp a partir da $versaoMinima."
    Write-Host 'Para atualizar: claude update'
}

$Host.UI.RawUI.WindowTitle = 'Claude - canal do WhatsApp (deixe aberto)'
Set-Location $sessao
claude --mcp-config $arquivoConfig --dangerously-load-development-channels server:whatsapp --add-dir $PastaDeTrabalho
