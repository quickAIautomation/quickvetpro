#!/bin/bash
# Script para extrair e configurar os frontends no servidor
# Execute no servidor após fazer upload dos arquivos .zip

set -e

echo "=== EXTRAIR E CONFIGURAR FRONTENDS ==="
echo ""

# Verificar se os arquivos existem
if [ ! -f "/tmp/admin-dashboard-dist.zip" ]; then
    echo "ERRO: admin-dashboard-dist.zip nao encontrado em /tmp/"
    echo "Faca upload do arquivo primeiro!"
    exit 1
fi

if [ ! -f "/tmp/stripe-dist.zip" ]; then
    echo "ERRO: stripe-dist.zip nao encontrado em /tmp/"
    echo "Faca upload do arquivo primeiro!"
    exit 1
fi

echo "Extraindo admin-dashboard..."
cd /tmp
sudo unzip -o admin-dashboard-dist.zip -d /var/www/quickvet/admin-dashboard/

echo "Extraindo stripe..."
sudo unzip -o stripe-dist.zip -d /var/www/quickvet/stripe/

echo "Ajustando permissoes..."
sudo chown -R quickvet:quickvet /var/www/quickvet/admin-dashboard/dist
sudo chown -R quickvet:quickvet /var/www/quickvet/stripe/dist

echo "Recarregando Nginx..."
sudo systemctl reload nginx

echo ""
echo "=== CONCLUIDO! ==="
echo ""
echo "Teste os frontends:"
echo "  curl http://localhost/admin"
echo "  curl http://localhost/plans"
echo ""
