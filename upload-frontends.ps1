# Script para comprimir e fazer upload dos frontends compilados
# Execute no PowerShell: .\upload-frontends.ps1

Write-Host "=== COMPRIMIR E PREPARAR UPLOAD DOS FRONTENDS ===" -ForegroundColor Cyan
Write-Host ""

# Verificar se as pastas dist existem
if (-not (Test-Path "admin-dashboard\dist")) {
    Write-Host "ERRO: admin-dashboard\dist nao encontrado!" -ForegroundColor Red
    Write-Host "Execute primeiro: cd admin-dashboard; npm run build" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path "stripe\dist")) {
    Write-Host "ERRO: stripe\dist nao encontrado!" -ForegroundColor Red
    Write-Host "Execute primeiro: cd stripe; npm run build" -ForegroundColor Yellow
    exit 1
}

Write-Host "Comprimindo admin-dashboard..." -ForegroundColor Green
Compress-Archive -Path "admin-dashboard\dist" -DestinationPath "admin-dashboard-dist.zip" -Force

Write-Host "Comprimindo stripe..." -ForegroundColor Green
Compress-Archive -Path "stripe\dist" -DestinationPath "stripe-dist.zip" -Force

Write-Host ""
Write-Host "=== ARQUIVOS COMPRIMIDOS COM SUCESSO! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Agora faca upload para o servidor:" -ForegroundColor Yellow
Write-Host ""
Write-Host "Metodo 1 - SCP (no PowerShell ou Git Bash):" -ForegroundColor Cyan
Write-Host "  scp admin-dashboard-dist.zip root@5.161.115.183:/tmp/" -ForegroundColor White
Write-Host "  scp stripe-dist.zip root@5.161.115.183:/tmp/" -ForegroundColor White
Write-Host ""
Write-Host "Metodo 2 - WinSCP ou FileZilla:" -ForegroundColor Cyan
Write-Host "  Conecte via SFTP e arraste os arquivos .zip para /tmp/" -ForegroundColor White
Write-Host ""
Write-Host "Depois, no servidor, execute:" -ForegroundColor Yellow
Write-Host "  cd /tmp" -ForegroundColor White
Write-Host "  sudo unzip -o admin-dashboard-dist.zip -d /var/www/quickvet/admin-dashboard/" -ForegroundColor White
Write-Host "  sudo unzip -o stripe-dist.zip -d /var/www/quickvet/stripe/" -ForegroundColor White
Write-Host "  sudo chown -R quickvet:quickvet /var/www/quickvet/admin-dashboard/dist" -ForegroundColor White
Write-Host "  sudo chown -R quickvet:quickvet /var/www/quickvet/stripe/dist" -ForegroundColor White
Write-Host "  sudo systemctl reload nginx" -ForegroundColor White
