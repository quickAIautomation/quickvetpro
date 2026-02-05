#!/bin/bash

# Script de instalação completa - QuickVET PRO
# Execute no servidor Ubuntu via Termius

set -e

echo "=========================================="
echo "Instalacao QuickVET PRO - Ubuntu 24.04"
echo "=========================================="
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Função para imprimir mensagens
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verificar se está rodando como root
if [ "$EUID" -ne 0 ]; then 
    print_error "Por favor, execute como root ou com sudo"
    exit 1
fi

print_info "Atualizando sistema..."
apt update && apt upgrade -y

print_info "Instalando dependências básicas..."
apt install -y \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    git \
    curl \
    wget \
    build-essential \
    libpq-dev \
    php-fpm \
    php-pgsql \
    certbot \
    python3-certbot-nginx

print_info "Adicionando repositório do PostgreSQL..."
# Adicionar repositório oficial do PostgreSQL
sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
apt update

print_info "Instalando PostgreSQL 17 com pgvector..."
apt install -y \
    postgresql-17 \
    postgresql-contrib-17 \
    postgresql-17-pgvector

print_info "Adicionando PPA para Python 3.11..."
# Adicionar PPA deadsnakes para Python 3.11
add-apt-repository -y ppa:deadsnakes/ppa
apt update

print_info "Instalando Python 3.11..."
# Tentar instalar Python 3.11, se não disponível usar Python 3 padrão
if apt-cache search python3.11 | grep -q python3.11; then
    apt install -y python3.11 python3.11-venv python3.11-dev
else
    print_warn "Python 3.11 não disponível, usando Python 3 padrão"
    apt install -y python3 python3-venv python3-dev python3-pip
    # Criar symlink para python3.11 se necessário
    if [ ! -f /usr/bin/python3.11 ]; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
        print_info "Usando Python ${PYTHON_VERSION}"
    fi
fi

# Nginx já está instalado no servidor, pulando instalação
print_warn "Nginx já está instalado, pulando instalação..."

# Redis será usado do Easypanel, pulando instalação
print_warn "Redis será usado do Easypanel, pulando instalação..."

print_info "Criando usuário quickvet..."
if ! id "quickvet" &>/dev/null; then
    useradd -m -s /bin/bash quickvet
    print_info "Usuário quickvet criado"
else
    print_warn "Usuário quickvet já existe"
fi

print_info "Criando diretórios..."
mkdir -p /var/www/quickvet
mkdir -p /var/www/adminer
chown -R quickvet:quickvet /var/www/quickvet

print_info "Configurando PostgreSQL..."
# Criar banco e usuário
sudo -u postgres psql <<EOF
-- Criar banco de dados
CREATE DATABASE quickvetpro;

-- Criar usuário
CREATE USER quickvet WITH PASSWORD 'QuickVET2024!Secure';

-- Dar permissões
GRANT ALL PRIVILEGES ON DATABASE quickvetpro TO quickvet;
ALTER USER quickvet CREATEDB;

-- Conectar ao banco e habilitar extensões
\c quickvetpro
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF

print_info "Baixando Adminer..."
cd /var/www/adminer
wget -q https://www.adminer.org/latest.php -O index.php
chown -R www-data:www-data /var/www/adminer

print_info "Configurando Nginx para Adminer..."
cat > /etc/nginx/sites-available/adminer <<'EOF'
server {
    listen 8080;
    server_name _;

    root /var/www/adminer;
    index index.php;

    location / {
        try_files $uri $uri/ =404;
    }

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php8.3-fpm.sock;
    }
}
EOF

ln -sf /etc/nginx/sites-available/adminer /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

print_info "Criando systemd service para QuickVET..."
cat > /etc/systemd/system/quickvet.service <<'EOF'
[Unit]
Description=QuickVET PRO API
After=network.target postgresql.service

[Service]
User=quickvet
Group=quickvet
WorkingDirectory=/var/www/quickvet
Environment="PATH=/var/www/quickvet/venv/bin"
EnvironmentFile=/var/www/quickvet/.env
ExecStart=/var/www/quickvet/venv/bin/gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

print_info "Criando configuração Nginx para QuickVET..."
cat > /etc/nginx/sites-available/quickvetpro <<'EOF'
server {
    listen 80;
    server_name quickvetpro.com.br www.quickvetpro.com.br;

    access_log /var/log/nginx/quickvetpro_access.log;
    error_log /var/log/nginx/quickvetpro_error.log;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/quickvetpro /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

print_info "Configurando firewall..."
if command -v ufw &> /dev/null; then
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 8080/tcp
    ufw --force enable
fi

echo ""
echo "=========================================="
echo "Instalacao concluida!"
echo "=========================================="
echo ""
echo "PROXIMOS PASSOS:"
echo ""
echo "1. Clonar o repositorio Git:"
echo "   cd /var/www/quickvet"
echo "   sudo -u quickvet git clone https://github.com/quickAIautomation/quickvetpro.git ."
echo ""
echo "2. Criar ambiente virtual e instalar dependencias:"
echo "   cd /var/www/quickvet"
PYTHON_CMD=$(which python3.11 2>/dev/null || which python3)
echo "   sudo -u quickvet $PYTHON_CMD -m venv venv"
echo "   sudo -u quickvet venv/bin/pip install --upgrade pip"
echo "   sudo -u quickvet venv/bin/pip install -r requirements.txt"
echo "   sudo -u quickvet venv/bin/pip install gunicorn"
echo ""
echo "3. Criar arquivo .env:"
echo "   sudo -u quickvet nano /var/www/quickvet/.env"
echo ""
echo "   Adicione as seguintes variaveis:"
echo "   DATABASE_URL=postgresql://quickvet:QuickVET2024!Secure@localhost:5432/quickvetpro"
echo "   REDIS_URL=redis://default:#QuickAI2504.@easypanel.quickautomation.space:6386/0"
echo "   (e todas as outras credenciais do Easypanel)"
echo ""
echo "4. Iniciar servico:"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable quickvet"
echo "   sudo systemctl start quickvet"
echo ""
echo "5. Configurar SSL:"
echo "   sudo certbot --nginx -d quickvetpro.com.br -d www.quickvetpro.com.br"
echo ""
echo "6. Acessar Adminer (painel PostgreSQL):"
echo "   http://SEU_IP:8080"
echo "   Sistema: PostgreSQL"
echo "   Servidor: localhost"
echo "   Usuario: quickvet"
echo "   Senha: QuickVET2024!Secure"
echo "   Banco: quickvetpro"
echo ""
echo "CREDENCIAIS CRIADAS:"
echo "PostgreSQL (local):"
echo "  Usuario: quickvet"
echo "  Senha: QuickVET2024!Secure"
echo "  Banco: quickvetpro"
echo ""
echo "Redis (Easypanel):"
echo "  Use as credenciais do Easypanel no arquivo .env"
echo ""
echo "IMPORTANTE: Altere a senha do PostgreSQL em producao!"
echo "=========================================="
