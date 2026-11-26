# Gera as duas chaves do canal e guarda a de leitura neste computador. Rode no SEU terminal:
#
#   Uma pessoa só (o serviço de sempre):
#   powershell -ExecutionPolicy Bypass -File canal-whatsapp\preparar_chaves.ps1 -EnderecoDoServico https://...
#
#   Várias pessoas no mesmo serviço (CANAL_PESSOAS): cada pessoa roda no PC dela, com o próprio nome:
#   powershell -ExecutionPolicy Bypass -File canal-whatsapp\preparar_chaves.ps1 -EnderecoDoServico https://... -Nome danilo
#
# A chave e a senha nunca aparecem na tela nem vão para arquivo: vão para a área de transferência, que é
# limpa no fim. Com -Nome, o que vai para o EasyPanel é só o SHA-256 delas (pode mostrar ao administrador:
# o resumo não abre nada). A chave de leitura fica nas variáveis do seu usuário do Windows.

param(
    [Parameter(Mandatory = $true)][string]$EnderecoDoServico,
    [string]$Nome = ''
)

$ErrorActionPreference = 'Stop'

function Nova-Chave {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [System.BitConverter]::ToString($bytes).Replace('-', '').ToLower()
}

function Resumo([string]$segredo) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($segredo))
    return [System.BitConverter]::ToString($bytes).Replace('-', '').ToLower()
}

if (-not $EnderecoDoServico.StartsWith('https://')) {
    throw 'O endereço do serviço precisa começar com https://'
}
$Nome = $Nome.Trim().ToLower()
if ($Nome -and $Nome -notmatch '^[a-z][a-z0-9_-]{0,29}$') {
    throw 'O nome começa com letra e só tem letras sem acento, números, - e _ (ex.: danilo)'
}

$leitura = Nova-Chave
$senha = Nova-Chave

[Environment]::SetEnvironmentVariable('CANAL_WHATSAPP_URL', $EnderecoDoServico.TrimEnd('/'), 'User')
[Environment]::SetEnvironmentVariable('CANAL_WHATSAPP_CHAVE', $leitura, 'User')

if ($Nome) {
    $prefixo = 'CANAL_' + $Nome.ToUpper().Replace('-', '_') + '_'
    Set-Clipboard -Value $senha
    Write-Host '1) A senha do seu painel está copiada. Guarde no seu gerenciador de senhas: é ela que abre a página do QR.'
    [void](Read-Host 'Guardou? Aperte Enter')
    Set-Clipboard -Value ' '
    Write-Host ''
    Write-Host '2) Mande estas duas linhas para quem administra o EasyPanel (são só resumos, não abrem nada):'
    Write-Host ''
    Write-Host ($prefixo + 'CHAVE_HASH=' + (Resumo $leitura))
    Write-Host ($prefixo + 'SENHA_PAINEL_HASH=' + (Resumo $senha))
    Write-Host ''
    Write-Host 'Pronto. A sua chave de leitura ficou nas variáveis do seu usuário do Windows.'
    return
}

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
