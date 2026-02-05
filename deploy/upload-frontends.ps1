# Script PowerShell para compilar e fazer upload dos frontends
# Execute no Windows PowerShell

Write-Host "=== COMPILAR E FAZER UPLOAD DOS FRONTENDS ===" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Stop"

# Configuracoes
$SERVER_IP = "5.161.115.183"
$SERVER_USER = "root"
$UPLOAD_PATH = "/tmp"

# Verificar se estamos no diretorio correto
if (-not (Test-Path "admin-dashboard") -or -not (Test-Path "stripe")) {
    Write-Host "ERRO: Execute este script na raiz do projeto!" -ForegroundColor Red
    exit 1
}

# PASSO 1: Compilar Admin Dashboard
Write-Host "PASSO 1: Compilando Admin Dashboard..." -ForegroundColor Green
Set-Location admin-dashboard

if (-not (Test-Path "node_modules")) {
    Write-Host "  Instalando dependencias..." -ForegroundColor Yellow
    npm install
}

Write-Host "  Compilando..." -ForegroundColor Yellow
npm run build

if (-not (Test-Path "dist")) {
    Write-Host "ERRO: Compilacao falhou! dist/ nao encontrado." -ForegroundColor Red
    Set-Location ..
    exit 1
}

Set-Location ..

# PASSO 2: Compilar Stripe Plans
Write-Host ""
Write-Host "PASSO 2: Compilando Stripe Plans..." -ForegroundColor Green
Set-Location stripe

if (-not (Test-Path "node_modules")) {
    Write-Host "  Instalando dependencias..." -ForegroundColor Yellow
    npm install
}

Write-Host "  Compilando..." -ForegroundColor Yellow
npm run build

if (-not (Test-Path "dist")) {
    Write-Host "ERRO: Compilacao falhou! dist/ nao encontrado." -ForegroundColor Red
    Set-Location ..
    exit 1
}

Set-Location ..

# PASSO 3: Criar arquivos ZIP
Write-Host ""
Write-Host "PASSO 3: Criando arquivos ZIP..." -ForegroundColor Green

if (Test-Path "admin-dashboard-dist.zip") {
    Remove-Item "admin-dashboard-dist.zip" -Force
}
Compress-Archive -Path "admin-dashboard\dist" -DestinationPath "admin-dashboard-dist.zip" -Force
Write-Host "  admin-dashboard-dist.zip criado!" -ForegroundColor Yellow

if (Test-Path "stripe-dist.zip") {
    Remove-Item "stripe-dist.zip" -Force
}
Compress-Archive -Path "stripe\dist" -DestinationPath "stripe-dist.zip" -Force
Write-Host "  stripe-dist.zip criado!" -ForegroundColor Yellow

# PASSO 4: Fazer upload para o servidor
Write-Host ""
Write-Host "PASSO 4: Fazendo upload para o servidor..." -ForegroundColor Green
Write-Host "  Servidor: ${SERVER_USER}@${SERVER_IP}" -ForegroundColor Yellow

# Verificar se scp esta disponivel
$scpAvailable = $false
try {
    $null = Get-Command scp -ErrorAction Stop
    $scpAvailable = $true
} catch {
    Write-Host "  AVISO: scp nao encontrado. Use WinSCP ou FileZilla para fazer upload manual." -ForegroundColor Yellow
    Write-Host "  Arquivos prontos para upload:" -ForegroundColor Yellow
    Write-Host "    - admin-dashboard-dist.zip" -ForegroundColor Gray
    Write-Host "    - stripe-dist.zip" -ForegroundColor Gray
    Write-Host "  Upload para: ${SERVER_USER}@${SERVER_IP}:${UPLOAD_PATH}/" -ForegroundColor Gray
}

if ($scpAvailable) {
    Write-Host "  Enviando admin-dashboard-dist.zip..." -ForegroundColor Yellow
    scp "admin-dashboard-dist.zip" "${SERVER_USER}@${SERVER_IP}:${UPLOAD_PATH}/"
    
    Write-Host "  Enviando stripe-dist.zip..." -ForegroundColor Yellow
    scp "stripe-dist.zip" "${SERVER_USER}@${SERVER_IP}:${UPLOAD_PATH}/"
    
    Write-Host ""
    Write-Host "=== UPLOAD CONCLUIDO! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "PROXIMO PASSO - Execute no servidor (via SSH):" -ForegroundColor Cyan
    Write-Host "  cd /var/www/quickvet" -ForegroundColor Gray
    Write-Host "  sudo bash deploy/deploy-frontends.sh" -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "=== COMPILACAO CONCLUIDA! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "PROXIMOS PASSOS:" -ForegroundColor Cyan
    Write-Host "1. Faca upload manual dos arquivos .zip para o servidor" -ForegroundColor Yellow
    Write-Host "2. Execute no servidor (via SSH):" -ForegroundColor Yellow
    Write-Host "   cd /var/www/quickvet" -ForegroundColor Gray
    Write-Host "   sudo bash deploy/deploy-frontends.sh" -ForegroundColor Gray
}
