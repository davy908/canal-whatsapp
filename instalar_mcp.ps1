# Dá ao Claude as ferramentas de leitura do canal, em todas as conversas deste usuário do Windows.
#
#   Instalar:  powershell -ExecutionPolicy Bypass -File canal-whatsapp\instalar_mcp.ps1
#   Tirar:     powershell -ExecutionPolicy Bypass -File canal-whatsapp\instalar_mcp.ps1 -Remover
#
# Copia o programa para %LOCALAPPDATA%\CanalWhatsapp. Vale para conversas abertas depois.

param([switch]$Remover)

$ErrorActionPreference = 'Stop'
$nome = 'canal-whatsapp'
$destino = Join-Path $env:LOCALAPPDATA 'CanalWhatsapp'
$programa = Join-Path $destino 'mcp_whatsapp.py'

cmd /c "claude mcp remove -s user $nome >nul 2>nul"

if ($Remover) {
    if (Test-Path $destino) { Remove-Item -Recurse -Force $destino }
    [Environment]::SetEnvironmentVariable('CANAL_WHATSAPP_URL', $null, 'User')
    [Environment]::SetEnvironmentVariable('CANAL_WHATSAPP_CHAVE', $null, 'User')
    Write-Host 'Ferramentas e chave de leitura removidas deste computador.'
    return
}

$uv = (Get-Command uv).Source
New-Item -ItemType Directory -Force $destino | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'mcp_whatsapp.py') $destino -Force
Copy-Item (Join-Path $PSScriptRoot 'mcp_whatsapp.py.lock') $destino -Force
cmd /c "claude mcp add -s user $nome -- `"$uv`" run --locked --script `"$programa`" >nul 2>nul"
if ($LASTEXITCODE -ne 0) { throw 'Não consegui registrar as ferramentas no Claude Code.' }
Write-Host 'Pronto. Abra uma conversa nova para o Claude ver as ferramentas.'
