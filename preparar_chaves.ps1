# Gera as duas chaves do canal e guarda a de leitura neste computador. Rode no SEU terminal:
#
#   powershell -ExecutionPolicy Bypass -File canal-whatsapp\preparar_chaves.ps1
#
# Nada é mostrado na tela nem gravado em arquivo: cada chave vai para a área de transferência e você
# cola no EasyPanel. No fim a área de transferência é limpa.

param([Parameter(Mandatory = $true)][string]$EnderecoDoServico)

$ErrorActionPreference = 'Stop'

function Nova-Chave {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [System.BitConverter]::ToString($bytes).Replace('-', '').ToLower()
}

if (-not $EnderecoDoServico.StartsWith('https://')) {
    throw 'O endereço do serviço precisa começar com https://'
}

$leitura = Nova-Chave
$senha = Nova-Chave

[Environment]::SetEnvironmentVariable('CANAL_WHATSAPP_URL', $EnderecoDoServico.TrimEnd('/'), 'User')
[Environment]::SetEnvironmentVariable('CANAL_WHATSAPP_CHAVE', $leitura, 'User')

Set-Clipboard -Value $leitura
Write-Host '1) A chave de leitura está copiada. No EasyPanel, em Ambiente, cole assim:'
Write-Host '   CANAL_CHAVE_LEITURA=(cole aqui)'
[void](Read-Host 'Colou? Aperte Enter')

Set-Clipboard -Value $senha
Write-Host '2) A senha do painel está copiada. Cole no EasyPanel assim:'
Write-Host '   CANAL_SENHA_PAINEL=(cole aqui)'
Write-Host '   Guarde também no seu gerenciador de senhas: é ela que abre a página do QR.'
[void](Read-Host 'Colou e guardou? Aperte Enter')

Set-Clipboard -Value ' '
Write-Host 'Pronto. A chave de leitura ficou nas variáveis do seu usuário do Windows.'
