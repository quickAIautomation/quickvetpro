# QuickVET PRO

Sistema SaaS de IA via WhatsApp para atendimento veterinário.

---

## 📋 Índice Rápido

Esta documentação está organizada por áreas. Encontre rapidamente o que precisa:

| Área | Seção | Descrição |
|------|-------|-----------|
| **💳 Stripe** | [Integração Stripe](#integração-stripe) | Checkout, assinaturas, webhooks, Stripe Connect |
| **📱 WhatsApp** | [Integração WhatsApp](#integração-whatsapp) | Webhook, envio de mensagens, templates, mídia |
| **🔐 Autenticação** | [Autenticação API](#autenticação-api) | API Keys, JWT, permissões |
| **📊 Rate Limiting** | [Rate Limiting por Plano](#rate-limiting-por-plano) | Limites dinâmicos por plano |
| **🧠 RAG** | [Sistema de RAG](#sistema-de-rag-retrieval-augmented-generation) | Busca vetorial e estrutural |
| **⚡ Performance** | [Otimizações](#otimizações-de-performance) | Cache, índices, warmup |
| **🔔 Webhooks** | [Webhooks Outbound](#webhooks-outbound-n8nzapier) | Eventos para sistemas externos |
| **📝 Logs** | [Logs Detalhados](#logs-detalhados) | Sistema de logging estruturado |
| **🧪 Testes** | [Testes Automatizados](#testes-automatizados) | Estrutura de testes com pytest |

---

## Stack

| Camada | Tecnologia |
|--------|------------|
| Backend | FastAPI (Python 3.11+) |
| Frontend | React (Vite) |
| LLM | OpenAI GPT-4 |
| Banco de Dados | PostgreSQL + pgvector |
| Cache/Sessões | Redis |
| Pagamentos | Stripe |
| WhatsApp | Meta Cloud API |

---

## Estrutura

```
QuickVET PRO/
├── app/                          # Backend FastAPI
│   ├── main.py                   # Entry point
│   ├── config.py                 # Configurações
│   ├── api/
│   │   ├── webhook_whatsapp.py   # Webhook WhatsApp (Meta Cloud API)
│   │   ├── stripe_checkout.py    # Checkout/Portal/Webhook Stripe
│   │   ├── platform.py           # API da Platform
│   │   └── knowledge.py          # API Base de Conhecimento
│   ├── agents/
│   │   └── vet_agent.py          # Agente IA + RAG
│   ├── services/
│   │   ├── mcp_knowledge_client.py         # 🔑 Cliente MCP (padroniza queries)
│   │   ├── quota_service.py                # Limite diário mensagens
│   │   ├── plan_service.py                 # Planos
│   │   ├── stripe_service.py               # Integração Stripe
│   │   ├── webhook_dispatcher.py           # Webhooks outbound (n8n)
│   │   ├── message_formatter.py            # Formatação mensagens WhatsApp
│   │   ├── knowledge_service.py            # RAG Vetorial (embeddings)
│   │   ├── structural_knowledge_service.py # RAG Estrutural (navegação)
│   │   ├── media_service.py                # Processamento de mídia (Vision/Whisper)
│   │   ├── conversation_memory.py          # Memória de contexto (Redis)
│   │   └── consent_service.py              # LGPD
│   ├── infra/
│   │   ├── db.py                 # PostgreSQL
│   │   ├── redis.py              # Redis
│   │   ├── cache.py              # Cache Redis para RAG
│   │   └── logging_config.py     # Logs estruturados
│   └── middleware/
│       └── observability.py      # Métricas e correlation_id
├── mcp/                          # MCP Server (conhecimento)
│   ├── server.py                 # Servidor MCP
│   └── knowledge.db              # SQLite com chunks
├── knowledge/                    # PDFs veterinários
├── stripe/                       # Frontend React
│   ├── src/                      # Checkout (3001)
│   └── dashboard/                # Dashboard (3000)
├── run.py
├── requirements.txt
└── .env
```

---

## Variáveis de Ambiente (.env)

```env
# Database
DATABASE_URL=postgresql://user:pass@host:port/quickvet

# Redis
REDIS_URL=redis://localhost:6379/0

# OpenAI
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o

# RAG - Modo de Recuperação
# Opções: vector, structural, hybrid, auto
RETRIEVAL_MODE=auto

# Cache TTL (segundos)
CACHE_TTL_VECTOR=3600
CACHE_TTL_STRUCTURAL=1800
CACHE_TTL_CONTEXT=3600
CACHE_TTL_TOC=86400

# Memória de Conversa
CONVERSATION_MAX_MESSAGES=20
CONVERSATION_MAX_TOKENS=4000
CONVERSATION_TTL_HOURS=24

# Webhooks Outbound (n8n)
N8N_WEBHOOK_URL=https://seu-n8n.com/webhook/quickvet
WEBHOOK_SECRET=seu_secret_aqui
WEBHOOK_TIMEOUT=10
WEBHOOK_RETRY_COUNT=3

# Stripe
STRIPE_SECRET_KEY=sk_xxx
STRIPE_PUBLISHABLE_KEY=pk_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
PLATFORM_PRICE_ID=price_xxx

# WhatsApp Business API (Meta)
WHATSAPP_API_TOKEN=EAAxxxxx              # Access Token do Meta
WHATSAPP_PHONE_NUMBER_ID=1234567890      # ID do número no Meta
WHATSAPP_VERIFY_TOKEN=quickvet_verify    # Token para verificar webhook
WHATSAPP_APP_SECRET=abcd1234             # App Secret do Meta

# App
DAILY_MESSAGE_LIMIT=50
ENVIRONMENT=production
FRONTEND_DOMAIN=https://app.quickvet.com.br
```

---

## Deploy em Produção

### 1. Servidor (VPS/Cloud)

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar com Gunicorn + Uvicorn workers
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# Ou com systemd service
sudo systemctl start quickvet
```

### 2. Nginx (Reverse Proxy)

```nginx
server {
    listen 80;
    server_name api.quickvet.com.br;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### 3. SSL com Certbot

```bash
sudo certbot --nginx -d api.quickvet.com.br
```

---

## Integração WhatsApp

Integração completa com WhatsApp Business API (Meta Cloud API) para receber e enviar mensagens.

### 📋 Visão Geral

O sistema processa mensagens recebidas via webhook, mantém contexto de conversa e responde automaticamente usando IA. Suporta texto, mídia (imagens, áudios, vídeos) e mensagens interativas.

### 🔧 Configuração Inicial

#### 1. Meta Business Suite

1. Acesse [developers.facebook.com](https://developers.facebook.com)
2. Crie um App → WhatsApp → Business
3. Configure o número de telefone
4. Copie as credenciais:
   - **Access Token** → `WHATSAPP_API_TOKEN`
   - **Phone Number ID** → `WHATSAPP_PHONE_NUMBER_ID`
   - **Business Account ID** → `WHATSAPP_BUSINESS_ACCOUNT_ID`
   - **App Secret** → `WHATSAPP_APP_SECRET`

#### 2. Configurar Webhook no Meta

| Campo | Valor |
|-------|-------|
| Callback URL | `https://api.quickvet.com.br/api/webhook/whatsapp` |
| Verify Token | `quickvet_verify` (mesmo do .env) |
| Webhook Fields | `messages` |

**Validação de Assinatura:**
- O sistema valida automaticamente usando `X-Hub-Signature-256`
- Requer `WHATSAPP_APP_SECRET` configurado no `.env`

#### 3. Variáveis de Ambiente

```env
WHATSAPP_API_TOKEN=EAAxxxxx              # Access Token do Meta
WHATSAPP_PHONE_NUMBER_ID=1234567890      # ID do número no Meta
WHATSAPP_BUSINESS_ACCOUNT_ID=1234567890  # ID da conta de negócio
WHATSAPP_VERIFY_TOKEN=quickvet_verify    # Token para verificar webhook
WHATSAPP_APP_SECRET=abcd1234             # App Secret do Meta
```

### 📨 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/webhook/whatsapp` | Verificação webhook Meta (challenge) |
| POST | `/api/webhook/whatsapp` | Recebe mensagens do WhatsApp |
| GET | `/api/webhook/status` | Status da integração |

### 🔄 Fluxo de Processamento

```
Mensagem recebida → Validação de assinatura → Extração de dados → 
Processamento de mídia (se houver) → Agente IA → Resposta formatada → 
Envio via API Meta → Log de conversa
```

### 📤 Envio de Mensagens

O sistema envia mensagens automaticamente após processar. Suporta:

- **Texto simples**: Mensagens de texto formatadas
- **Mensagens longas**: Divisão automática em partes
- **Botões interativos**: Até 3 botões de resposta rápida
- **Listas interativas**: Menu de seleção com até 10 itens
- **Templates**: Mensagens pré-aprovadas pelo Meta

### 🖼️ Processamento de Mídia

| Tipo | Processamento | Uso |
|------|---------------|-----|
| **Imagem** | GPT-4o Vision | Análise visual de sintomas, feridas |
| **Áudio** | Whisper | Transcrição automática |
| **Vídeo** | Extração de frames | Solicita foto específica |
| **Sticker** | GPT-4o Vision | Tratado como imagem |

### 🧠 Memória de Conversa

O sistema mantém contexto entre mensagens usando Redis:

- Últimas 20 mensagens mantidas (configurável)
- Expira após 24 horas de inatividade
- Comandos para reiniciar: `NOVA CONVERSA`, `LIMPAR`, `RESET`

### 📊 Rastreamento de Conversas

Todas as conversas são rastreadas no banco de dados:

- Tabela `conversations`: Status e metadados
- Tabela `conversation_messages`: Histórico completo
- Status: `active`, `inactive`, `pending`, `resolved`

### 🧪 Testar Integração

```bash
# Enviar mensagem de teste via API Meta
curl -X POST "https://graph.facebook.com/v18.0/PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "5511999999999",
    "type": "text",
    "text": {"body": "Teste QuickVET"}
  }'
```

### 🔒 Segurança

- Validação de assinatura HMAC-SHA256 em todos os webhooks
- Verificação de origem (Meta Cloud API)
- Logs de auditoria para todas as mensagens
- Rate limiting por usuário

### 📝 Formatação de Mensagens

Veja a seção [Formatação de Mensagens WhatsApp](#formatação-de-mensagens-whatsapp) para detalhes sobre:
- Quebra automática de mensagens longas
- Conversão de Markdown para WhatsApp
- Botões e listas interativas
- Emojis contextuais

---

## Integração Stripe

Integração completa com Stripe para pagamentos, assinaturas e Stripe Connect (marketplace).

### 📋 Visão Geral

O sistema gerencia:
- **Checkout Sessions**: Criação de sessões de pagamento
- **Subscriptions**: Assinaturas recorrentes
- **Customer Portal**: Gerenciamento de assinaturas pelos clientes
- **Webhooks**: Processamento de eventos do Stripe
- **Stripe Connect**: Contas conectadas para marketplace

### 🔧 Configuração Inicial

#### 1. Criar Conta Stripe

1. Acesse [stripe.com](https://stripe.com)
2. Crie uma conta e obtenha as chaves de API
3. Configure webhooks no Dashboard

#### 2. Variáveis de Ambiente

```env
STRIPE_SECRET_KEY=sk_live_xxx              # Chave secreta (live ou test)
STRIPE_PUBLISHABLE_KEY=pk_live_xxx         # Chave pública
STRIPE_WEBHOOK_SECRET=whsec_xxx            # Secret do webhook
PLATFORM_PRICE_ID=price_xxx                # ID do preço da plataforma (opcional)
```

#### 3. Configurar Webhook no Stripe Dashboard

| Campo | Valor |
|-------|-------|
| Endpoint URL | `https://api.quickvet.com.br/api/stripe/webhook` |
| Events to send | Todos os eventos relevantes (ver abaixo) |

**Eventos Processados:**
- `checkout.session.completed`
- `customer.subscription.*`
- `invoice.*`
- `payment_intent.*`
- `setup_intent.*`
- `charge.*`
- `customer.*`
- `account.*` (Stripe Connect)

### 💳 Checkout e Assinaturas

#### Criar Sessão de Checkout

```bash
POST /api/stripe/create-checkout-session
Content-Type: application/x-www-form-urlencoded

lookup_key=monthly_plan
user_id=user_123
customer_email=cliente@exemplo.com
```

**Suporta:**
- Checkout padrão (subscription ou payment)
- Stripe Connect (com `stripe_account` e `application_fee_amount`)
- Line items customizados

#### Customer Portal

```bash
POST /api/stripe/create-portal-session
Content-Type: application/x-www-form-urlencoded

session_id=cs_xxx
```

Permite que clientes gerenciem suas assinaturas (cancelar, atualizar método de pagamento, etc).

### 🔄 Webhooks

O sistema processa automaticamente eventos do Stripe:

#### Eventos de Assinatura

- `customer.subscription.created` - Nova assinatura
- `customer.subscription.updated` - Plano alterado
- `customer.subscription.deleted` - Assinatura cancelada
- `customer.subscription.trial_will_end` - Trial terminando

#### Eventos de Pagamento

- `invoice.paid` - Pagamento confirmado
- `invoice.payment_failed` - Pagamento falhou
- `payment_intent.succeeded` - Intent bem-sucedido
- `payment_intent.payment_failed` - Intent falhou

#### Eventos de Setup

- `setup_intent.created` - Setup iniciado
- `setup_intent.succeeded` - Método de pagamento salvo
- `setup_intent.setup_failed` - Setup falhou

#### Atualização Automática de Planos

Quando um webhook é recebido:
1. Identifica o tipo de plano (monthly, quarterly, semiannual, annual)
2. Atualiza a tabela `plans` no banco
3. Atualiza a tabela `subscriptions`
4. Invalida cache do rate limiter
5. Dispara webhook para n8n (se configurado)

### 🏪 Stripe Connect (Marketplace)

Suporte completo para contas conectadas (marketplace).

#### Criar Conta Conectada

```bash
POST /api/connect/accounts
Content-Type: application/json

{
  "account_id": "clinic_123",
  "email": "clinica@exemplo.com",
  "country": "BR",
  "type": "express",
  "risk_responsibility": "stripe"
}
```

#### Onboarding

```bash
POST /api/connect/accounts/{account_id}/onboard
Content-Type: application/json

{
  "return_url": "https://app.quickvet.com/onboard/return",
  "refresh_url": "https://app.quickvet.com/onboard/refresh"
}
```

Retorna URL do Account Link para onboarding.

#### Verificar Status

```bash
GET /api/connect/accounts/{account_id}/status
```

Retorna:
- `charges_enabled`: Se pode receber cobranças
- `payouts_enabled`: Se pode receber payouts
- `onboarding_status`: `pending`, `in_progress`, `complete`, `deauthorized`

#### Dashboard

```bash
GET /api/connect/accounts/{account_id}/dashboard
```

Retorna link para Express Dashboard da conta conectada.

#### Tipos de Charges

**Direct Charge** (cobrança direta):
```python
stripe_service.create_direct_charge(
    amount=10000,  # R$ 100.00
    currency="brl",
    connected_account_id="acct_xxx",
    application_fee_amount=1000  # R$ 10.00 de taxa
)
```

**Destination Charge** (com transfer imediato):
```python
stripe_service.create_destination_charge(
    amount=10000,
    currency="brl",
    destination="acct_xxx",
    application_fee_amount=1000
)
```

**Separate Transfer** (transferência separada):
```python
stripe_service.create_transfer(
    amount=9000,
    currency="brl",
    destination="acct_xxx"
)
```

### 📊 Produtos e Preços

#### Listar Produtos

```bash
GET /api/stripe/products?active_only=true
```

Retorna todos os produtos com seus preços cadastrados no Stripe.

#### Listar Preços

```bash
GET /api/stripe/prices?lookup_key=monthly_plan
```

### 🔒 Segurança

- Validação de assinatura em todos os webhooks
- Verificação de origem (Stripe)
- Logs de auditoria para todos os eventos
- Idempotência em processamento de webhooks

### 📝 Endpoints Completos

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/stripe/products` | Lista produtos |
| GET | `/api/stripe/prices` | Lista preços |
| GET | `/api/stripe/status` | Status da integração |
| POST | `/api/stripe/create-checkout-session` | Cria checkout |
| POST | `/api/stripe/create-portal-session` | Portal cliente |
| POST | `/api/stripe/webhook` | Webhook Stripe |
| POST | `/api/connect/accounts` | Criar conta conectada |
| POST | `/api/connect/accounts/{id}/onboard` | Iniciar onboarding |
| GET | `/api/connect/accounts/{id}/status` | Status da conta |
| GET | `/api/connect/accounts/{id}/dashboard` | Link do dashboard |
| GET | `/api/connect/accounts` | Listar contas conectadas |

### 🧪 Testar Integração

```bash
# Verificar status
curl https://api.quickvet.com.br/api/stripe/status

# Listar produtos
curl https://api.quickvet.com.br/api/stripe/products

# Criar checkout (exemplo)
curl -X POST https://api.quickvet.com.br/api/stripe/create-checkout-session \
  -d "lookup_key=monthly_plan&customer_email=test@exemplo.com"
```

---

## Endpoints

> **📌 Nota:** Para documentação completa e detalhada, consulte:
> - **WhatsApp**: [Integração WhatsApp](#integração-whatsapp)
> - **Stripe**: [Integração Stripe](#integração-stripe)

### WhatsApp
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/webhook/whatsapp` | Verificação webhook Meta |
| POST | `/api/webhook/whatsapp` | Recebe mensagens |
| GET | `/api/webhook/status` | Status da integração |

**📖 Ver seção completa:** [Integração WhatsApp](#integração-whatsapp)

### Stripe
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/stripe/products` | Lista produtos |
| GET | `/api/stripe/prices` | Lista preços |
| GET | `/api/stripe/status` | Status da integração |
| POST | `/api/stripe/create-checkout-session` | Cria checkout |
| POST | `/api/stripe/create-portal-session` | Portal cliente |
| POST | `/api/stripe/webhook` | Eventos Stripe |
| POST | `/api/connect/accounts` | Criar conta Stripe Connect |
| POST | `/api/connect/accounts/{id}/onboard` | Iniciar onboarding |
| GET | `/api/connect/accounts/{id}/status` | Status da conta |
| GET | `/api/connect/accounts/{id}/dashboard` | Link do dashboard |

**📖 Ver seção completa:** [Integração Stripe](#integração-stripe)

### Platform
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/login-by-email` | Login por email |
| POST | `/api/account` | Criar conta |
| GET | `/api/account/{id}` | Buscar conta |

### Knowledge - Vetorial (RAG tradicional)
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/knowledge/stats` | Estatísticas |
| POST | `/api/knowledge/search` | Busca por embeddings |
| POST | `/api/knowledge/ingest` | Ingerir PDFs |

### Knowledge - Estrutural (Navegação hierárquica)
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/structural/setup` | Criar tabelas estruturais |
| GET | `/api/structural/stats` | Estatísticas |
| POST | `/api/structural/navigate` | Navegação por query |
| GET | `/api/structural/context` | Contexto formatado |
| POST | `/api/structural/ingest` | Processar PDFs com estrutura |
| GET | `/api/structural/tree/{id}` | Árvore do documento |
| GET | `/api/structural/compare` | Compara vetorial vs estrutural |
| GET | `/api/structural/cache/stats` | Métricas do cache |
| DELETE | `/api/structural/cache/invalidate` | Invalida cache |

---

## Tabelas PostgreSQL

| Tabela | Função |
|--------|--------|
| `users` | Usuários WhatsApp |
| `plans` | Planos ativos |
| `subscriptions` | Assinaturas Stripe |
| `accounts` | Contas das clínicas |
| `products` | Produtos/serviços |
| `audit_logs` | Auditoria + idempotência |
| `user_consents` | LGPD |
| `message_logs` | Histórico mensagens |
| `knowledge_chunks` | RAG Vetorial - chunks + embeddings |
| `structural_documents` | RAG Estrutural - documentos |
| `structural_nodes` | RAG Estrutural - nós hierárquicos |
| `structural_toc` | RAG Estrutural - sumários |

---

## Formatação de Mensagens WhatsApp

O sistema formata automaticamente as mensagens para o WhatsApp.

### Recursos

| Recurso | Descrição |
|---------|-----------|
| **Quebra automática** | Mensagens longas divididas em partes (~4000 chars) |
| **Markdown → WhatsApp** | Converte `**bold**` → `*bold*` |
| **Emojis contextuais** | Adiciona 🚨 em emergências, 💊 em medicamentos, etc |
| **Listas** | Converte `- item` → `• item` |
| **Botões interativos** | Resposta rápida com até 3 botões |
| **Listas interativas** | Menu de seleção com até 10 itens |

### Formatação WhatsApp Suportada

```
*negrito*
_itálico_
~tachado~
```código```
```

### Mensagens Longas

Mensagens são divididas automaticamente com indicador:

```
[Parte 1 da resposta...]

_...continua (1/3)_
```

```
[Parte 2 da resposta...]

_...continua (2/3)_
```

### Botões Interativos

```python
from app.services.message_formatter import message_formatter, Button

msg = message_formatter.create_button_message(
    body="Como você avalia a urgência?",
    buttons=[
        Button(id="urgent", title="🔴 Urgente"),
        Button(id="normal", title="🟡 Normal"),
        Button(id="low", title="🟢 Baixa")
    ]
)
```

### Listas Interativas

```python
msg = message_formatter.create_list_message(
    body="Selecione os sintomas presentes:",
    button_text="Ver sintomas",
    sections=[{
        "title": "Sintomas",
        "rows": [
            {"id": "fever", "title": "Febre", "description": "Temperatura elevada"},
            {"id": "vomit", "title": "Vômito", "description": "Episódios de vômito"}
        ]
    }]
)
```

### Templates Prontos

```python
# Resposta de emergência com destaque
messages = message_formatter.format_emergency_response(text)

# Resposta com botões de urgência
messages = message_formatter.format_with_urgency_buttons(text)

# Resposta com botões de feedback
messages = message_formatter.format_with_feedback_buttons(text)
```

---

## Webhooks Outbound (n8n/Zapier)

O sistema dispara webhooks para sistemas externos quando eventos acontecem.

### Eventos Disponíveis

| Evento | Quando dispara |
|--------|----------------|
| `subscription.created` | Nova assinatura criada |
| `subscription.updated` | Plano alterado |
| `subscription.cancelled` | Assinatura cancelada |
| `subscription.expired` | Plano expirou |
| `payment.succeeded` | Pagamento confirmado |
| `payment.failed` | Pagamento falhou |
| `account.created` | Nova conta criada |
| `quota.exceeded` | Usuário excedeu limite |
| `emergency.detected` | Emergência detectada na conversa |

### Payload Enviado

```json
{
  "event": "payment.succeeded",
  "timestamp": "2024-01-15T10:30:00Z",
  "account_id": "clinic_123",
  "user_id": "5511999999999",
  "data": {
    "amount": 9900,
    "currency": "brl",
    "amount_formatted": "R$ 99.00",
    "invoice_url": "https://..."
  }
}
```

### Headers de Segurança

| Header | Descrição |
|--------|-----------|
| `X-Webhook-Signature` | HMAC-SHA256 do payload |
| `X-Webhook-Event` | Tipo do evento |
| `X-Webhook-Timestamp` | Timestamp ISO |

### Validação no n8n

```javascript
// No n8n, validar assinatura:
const crypto = require('crypto');
const payload = JSON.stringify($input.all()[0].json);
const signature = $input.all()[0].headers['x-webhook-signature'];
const expected = 'sha256=' + crypto
  .createHmac('sha256', 'SEU_WEBHOOK_SECRET')
  .update(payload)
  .digest('hex');

if (signature !== expected) {
  throw new Error('Assinatura inválida');
}
```

### Retry Automático

- 3 tentativas em caso de falha
- Webhooks falhos salvos no Redis para retry posterior
- Endpoint para reprocessar: chamar `webhook_dispatcher.retry_failed_webhooks()`

---

## Processamento de Mídia (Imagens, Áudios, Vídeos)

O sistema aceita e processa mídia enviada pelos tutores via WhatsApp.

### Tipos Suportados

| Tipo | Processamento | Uso |
|------|---------------|-----|
| **Imagem** | GPT-4o Vision | Análise visual de sintomas, feridas, etc |
| **Áudio** | Whisper | Transcrição automática para texto |
| **Vídeo** | Extração de frames | Solicita foto específica |
| **Sticker** | GPT-4o Vision | Tratado como imagem |

### Fluxo de Processamento

```
Mídia recebida → Download via API Meta → Processamento → Descrição textual → Agente
```

### Análise de Imagens (GPT-4o Vision)

Quando o tutor envia uma foto, o sistema analisa automaticamente:
- **Identificação**: Espécie, raça aproximada
- **Observações visuais**: Descrição objetiva
- **Sinais clínicos**: Feridas, inchaços, secreções
- **Urgência**: Indicação de necessidade de atendimento

### Solicitação Automática de Mídia

O agente detecta quando uma foto ajudaria e sugere:

```
Tutor: "Meu cachorro tem uma ferida na pata"
Agente: "... [resposta] ...
         💡 Para ajudar melhor, você poderia enviar uma foto da ferida?"
```

**Palavras que ativam sugestão**: ferida, inchaço, mancha, coceira, olho, orelha, vômito, fezes, etc.

---

## Memória de Conversa

O agente mantém contexto entre mensagens do mesmo usuário usando Redis.

### Funcionamento

```
Usuário: "Meu cachorro está com diarreia"
Agente: "Há quanto tempo está assim?"

Usuário: "2 dias"
Agente: "Entendi, 2 dias de diarreia. A consistência..." ← Contexto mantido!
```

### Configuração

```env
CONVERSATION_MAX_MESSAGES=20    # Últimas N mensagens mantidas
CONVERSATION_MAX_TOKENS=4000    # Limite de tokens no contexto
CONVERSATION_TTL_HOURS=24       # Expira após X horas de inatividade
```

### Estrutura no Redis

```
quickvet:conversation:{user_id}:messages  → Lista de mensagens
quickvet:conversation:{user_id}:metadata  → Metadados (início, última atividade)
```

### Comandos do Usuário

O usuário pode reiniciar a conversa enviando:
- `NOVA CONVERSA`
- `LIMPAR`
- `RESET`
- `REINICIAR`

### Variáveis de Contexto

O sistema pode armazenar informações extraídas da conversa:

```python
# Salvar informação do pet
await conversation_memory.set_context_variable(user_id, "pet_name", "Rex")
await conversation_memory.set_context_variable(user_id, "pet_species", "cachorro")

# Recuperar
pet_name = await conversation_memory.get_context_variable(user_id, "pet_name")
```

---

## Arquitetura MCP (Model Context Protocol)

O VetAgent usa **MCP Client** para TODAS as queries de conhecimento, garantindo padronização entre:
- Uso interno (VetAgent processando mensagens)
- Uso externo (Cursor IDE, outros clientes MCP)

### Fluxo Padronizado

```
                  ┌─────────────────────────────────────────────┐
                  │           MCP Knowledge Client               │
                  │       (app/services/mcp_knowledge_client.py) │
                  └─────────────────────┬───────────────────────┘
                                        │
          ┌─────────────────────────────┼─────────────────────────────┐
          │                             │                             │
          ▼                             ▼                             ▼
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│   VetAgent       │        │   MCP Server     │        │   API REST       │
│   (interno)      │        │   (Cursor IDE)   │        │   (externo)      │
└──────────────────┘        └──────────────────┘        └──────────────────┘
```

### Benefícios

| Benefício | Descrição |
|-----------|-----------|
| **Padronização** | Mesma lógica e formato em todas as interfaces |
| **Cache unificado** | Queries iguais usam mesmo cache |
| **Logs centralizados** | Todas as queries logadas no mesmo formato |
| **Detecção consistente** | Modo AUTO funciona igual em todos os contextos |

### Tools MCP Expostas

```python
# Via mcp_client (interno) ou MCP Server (externo)
await mcp_client.search_veterinary_knowledge(query, mode="auto")  # Busca principal
await mcp_client.vector_search(query)                              # Apenas vetorial
await mcp_client.structural_navigate(query)                        # Apenas estrutural
await mcp_client.get_knowledge_stats()                             # Estatísticas
```

### Uso no VetAgent

```python
# O VetAgent SEMPRE usa MCP Client
class VetAgent:
    async def _get_context_via_mcp(self, query: str, mode: RetrievalMode) -> str:
        result = await mcp_client.search_veterinary_knowledge(query, mode.value)
        return result.content if result.success else ""
```

---

## Sistema de RAG (Retrieval-Augmented Generation)

O sistema implementa **dois métodos de recuperação de conhecimento**:

### 1. RAG Vetorial (Tradicional)

Busca por **similaridade semântica** usando embeddings OpenAI + pgvector.

```
Query → Embedding → Busca no pgvector → Top-K chunks mais similares
```

**Quando usar:**
- Queries conceituais ("O que é cinomose?")
- Busca por sintomas gerais
- Definições

**Limitações:**
- Não encontra dados em tabelas numéricas
- Ignora anexos e apêndices com baixa similaridade textual
- Não segue referências cruzadas

### 2. RAG Estrutural (Navegação Hierárquica)

Inspirado no [PageIndex](https://arxiv.org/abs/2401.12123), navega pela **estrutura do documento** como um humano faria.

```
Query → LLM lê sumário → Decide caminho → Navega para seção → Segue referências
```

**Arquitetura:**
```
Documento
├── Capítulo 1
│   ├── Seção 1.1
│   │   └── Conteúdo...
│   └── Seção 1.2
├── Capítulo 2
└── Anexo A (tabelas, dados numéricos)
```

**Quando usar:**
- Queries com tabelas/anexos ("Qual dosagem na Tabela 3?")
- Protocolos e procedimentos
- Dados numéricos e referências
- Compliance e auditoria

**Vantagens:**
- Encontra dados em tabelas e anexos
- Segue referências cruzadas ("ver Anexo G")
- Rastreabilidade do caminho de navegação
- Não precisa de Vector DB (PostgreSQL puro)

### Modos de Recuperação

Configure via variável de ambiente `RETRIEVAL_MODE`:

| Modo | Comportamento |
|------|---------------|
| `vector` | Apenas busca vetorial (rápido, barato) |
| `structural` | Apenas navegação estrutural (preciso) |
| `hybrid` | Ambos os métodos combinados |
| `auto` | Detecta automaticamente pelo tipo de query |

**Detecção automática:** Queries com palavras como "tabela", "anexo", "protocolo", "dosagem" usam navegação estrutural.

---

## Sistema de Cache (Redis)

Cache inteligente para reduzir latência e custos de inferência.

### Funcionamento

```
Query → Hash → Busca no Redis → HIT? Retorna → MISS? Executa e cacheia
```

### Tipos de Cache

| Tipo | TTL Padrão | Descrição |
|------|------------|-----------|
| `vector_search` | 1 hora | Resultados de busca vetorial |
| `structural_navigation` | 30 min | Resultados de navegação |
| `context` | 1 hora | Contexto formatado |
| `toc` | 24 horas | Sumários de documentos |
| `embedding` | 7 dias | Embeddings de queries (novo!) |

### Cache de Embeddings

O sistema cacheia os embeddings das queries, não apenas os resultados:

```
Query "meu cachorro está vomitando"
  ↓
Embedding cacheado? SIM → Usa do cache
                    NÃO → Calcula e cacheia por 7 dias
```

**Benefício:** Embeddings são determinísticos - uma vez calculados, nunca mudam.

### Invalidação

- **Automática:** Ao ingerir novos documentos
- **Manual:** `DELETE /api/structural/cache/invalidate`

### Métricas

```bash
GET /cache/stats
```

Retorna hits, misses, hit rate e embeddings cacheados.

---

## Otimizações de Performance

O sistema implementa 4 otimizações principais:

### 1. Cache de Embeddings de Query

```env
CACHE_TTL_EMBEDDING=604800  # 7 dias
```

Evita recalcular embeddings para queries repetidas. Como embeddings são determinísticos, podem ter TTL muito longo.

### 2. Busca em Batch (Paralela)

```python
# Processar múltiplas queries em paralelo
results = await knowledge_service.search_batch([
    "cinomose em cães",
    "parvovirose sintomas",
    "vacinas filhote"
])
```

Processa até 3 queries em paralelo (configurável).

### 3. Índice HNSW (pgvector)

O PostgreSQL usa índice HNSW (Hierarchical Navigable Small World) para busca aproximada:

```sql
CREATE INDEX idx_knowledge_embedding 
ON knowledge_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

SET hnsw.ef_search = 60;  -- Balanceamento precisão/velocidade
```

**Performance:** 10-100x mais rápido que busca exata.

| Parâmetro | Valor | Descrição |
|-----------|-------|-----------|
| `m` | 16 | Conexões por nó (maior = mais preciso) |
| `ef_construction` | 64 | Qualidade na construção |
| `ef_search` | 60 | Qualidade nas buscas |

### 4. Pré-aquecimento de Cache (Warmup)

No startup, o sistema pré-carrega queries frequentes:

```env
CACHE_WARMUP_ENABLED=true  # Ativar warmup no startup
```

**Queries pré-aquecidas:**
- Emergências: "vomitando", "diarreia", "envenenado", etc
- Doenças comuns: "cinomose", "parvovirose", "giárdia", etc
- Cuidados básicos: "vacinas", "vermífugo", "castração", etc

**Endpoints:**

```bash
# Status do warmup
GET /cache/stats

# Disparar warmup manual
POST /cache/warmup
```

### Resumo de Ganhos

| Otimização | Ganho Estimado |
|------------|----------------|
| Cache de embeddings | ~200ms por query repetida |
| Busca em batch | 3x throughput |
| Índice HNSW | 10-100x velocidade de busca |
| Warmup | Latência zero na 1ª requisição |

---

## MCP Server

Servidor MCP com dois modos de RAG para uso no Cursor ou outros clientes MCP.

### Tools Disponíveis

| Tool | Descrição |
|------|-----------|
| `search_veterinary_knowledge` | Busca inteligente (auto, vector ou structural) |
| `vector_search` | Busca por similaridade semântica |
| `structural_navigate` | Navegação hierárquica estilo PageIndex |
| `get_knowledge_stats` | Estatísticas da base |

### Configuração no Cursor

Adicione em `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "quickvet-knowledge": {
      "command": "python",
      "args": ["C:/caminho/para/mcp/server.py"],
      "env": {
        "OPENAI_API_KEY": "sk-xxx",
        "OPENAI_MODEL": "gpt-4o",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/quickvet"
      }
    }
  }
}
```

### Exemplos de Uso

```
# Busca automática (detecta melhor modo)
search_veterinary_knowledge("Qual a dosagem de amoxicilina para cães?")

# Forçar busca vetorial
vector_search("O que é cinomose?")

# Forçar navegação estrutural (para tabelas, anexos)
structural_navigate("Qual o valor de referência na tabela de hemograma?")
```

### Modo AUTO

O modo `auto` detecta automaticamente:
- **Vetorial**: queries simples, conceituais
- **Estrutural**: queries com "tabela", "anexo", "dosagem", "protocolo", etc.

---

## Segurança

- Webhook WhatsApp validado com `X-Hub-Signature-256`
- Webhook Stripe validado com `STRIPE_WEBHOOK_SECRET`
- LGPD: consentimento obrigatório antes de processar
- Logs com `correlation_id` para rastreamento
- Idempotência em webhooks e criação de contas

---

## Rate Limiting por Plano

Sistema de rate limiting dinâmico similar à OpenAI, com limites baseados no plano do usuário.

### Limites por Plano

| Plano | RPM | RPD | Tokens/min | Burst | Concurrent |
|-------|-----|-----|------------|-------|------------|
| **Gratuito** | 10 | 100 | 5.000 | 5 | 2 |
| **Mensal** | 30 | 500 | 20.000 | 15 | 5 |
| **Trimestral** | 60 | 1.500 | 50.000 | 30 | 10 |
| **Semestral** | 100 | 3.000 | 100.000 | 50 | 15 |
| **Anual** | 200 | 10.000 | 200.000 | 100 | 25 |
| **Enterprise** | 1.000 | 100.000 | 1.000.000 | 500 | 100 |

**Legenda:**
- **RPM**: Requests por minuto
- **RPD**: Requests por dia
- **Burst**: Requests extras permitidas em picos
- **Concurrent**: Requests simultâneas

### Peso por Endpoint

Alguns endpoints consomem mais do limite:

| Endpoint | Peso | Descrição |
|----------|------|-----------|
| `/api/webhook/whatsapp` | 1x | Normal |
| `/api/knowledge/search` | 2x | Usa embedding |
| `/api/structural/navigate` | 3x | Usa LLM |
| `/api/knowledge/ingest` | 5x | Processa PDFs |

### Headers de Resposta

```http
X-RateLimit-Tier: monthly
X-RateLimit-Limit-RPM: 30
X-RateLimit-Limit-RPD: 500
X-RateLimit-Remaining-RPM: 25
X-RateLimit-Remaining-RPD: 450
Retry-After: 45  (quando excedido)
```

### Resposta quando excedido (429)

```json
{
  "error": "rate_limit_exceeded",
  "message": "Limite de rpm excedido para seu plano (free)",
  "limit_type": "rpm",
  "tier": "free",
  "retry_after_seconds": 45,
  "upgrade_url": "/api/stripe/upgrade"
}
```

### Verificar uso atual

```bash
GET /api/rate-limit/usage

# Resposta:
{
  "tier": "monthly",
  "limits": {"rpm": 30, "rpd": 500},
  "usage": {"rpm": 5, "rpd": 120},
  "remaining": {"rpm": 25, "rpd": 380},
  "reset": {
    "rpm_resets_in_seconds": 45,
    "rpd_resets_in_seconds": 43200
  }
}
```

### Configuração

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WHITELIST=127.0.0.1
RATE_LIMIT_BLACKLIST=
```

### Invalidar cache de plano

Quando um plano muda (via Stripe webhook):

```python
from app.middleware.rate_limit import on_plan_change

# Chamar quando plano mudar
await on_plan_change(user_id, "annual")
```

---

## Autenticação API

Sistema de autenticação com API Keys e JWT Tokens.

### API Keys

Para integrações server-to-server:

```bash
# Criar API Key (via código ou endpoint admin)
key_id, api_key = await create_api_key(
    account_id="clinic_123",
    name="Integração ERP",
    permissions=["read", "write"]
)

# Usar na requisição
curl -H "X-API-Key: qv_abc123_secretkey..." https://api.quickvet.com/...
```

### JWT Tokens

Para autenticação de usuários:

```python
# Gerar token
token = create_jwt_token(
    subject="user_123",
    token_type="user",
    permissions=["read", "write"],
    expiration_hours=24
)

# Usar na requisição
curl -H "Authorization: Bearer eyJ..." https://api.quickvet.com/...
```

### Dependências FastAPI

```python
from app.middleware.auth import require_auth, require_admin, require_permission

@router.get("/protected")
async def protected_route(user: AuthenticatedUser = Depends(require_auth)):
    return {"user_id": user.id}

@router.get("/admin-only")
async def admin_route(user: AuthenticatedUser = Depends(require_admin)):
    return {"admin": True}

@router.get("/specific-permission")
async def permission_route(user = Depends(require_permission("write:sensitive"))):
    return {"allowed": True}
```

---

## Sistema de Alertas

Monitoramento e notificações para erros críticos.

### Tipos de Alerta

| Tipo | Severidade | Descrição |
|------|------------|-----------|
| `error_rate_high` | WARNING/CRITICAL | Taxa de erro acima do limite |
| `rate_limit_abuse` | WARNING | IP excedendo rate limit repetidamente |
| `integration_failure` | ERROR/CRITICAL | Falha em Stripe, WhatsApp, OpenAI |
| `quota_exceeded` | INFO | Usuário excedeu quota de mensagens |
| `payment_failed` | WARNING | Pagamento falhou |
| `security_alert` | CRITICAL | Evento de segurança |
| `performance_degradation` | WARNING | Latência alta |

### Configuração

```env
ALERT_WEBHOOK_URL=https://n8n.exemplo.com/webhook/alerts
ALERT_COOLDOWN_MINUTES=15  # Evita spam de alertas
```

### Uso

```python
from app.services.alert_service import alert_service, AlertSeverity

# Alerta manual
await alert_service.send_alert(Alert(
    alert_type=AlertType.SECURITY_ALERT,
    severity=AlertSeverity.CRITICAL,
    title="Tentativa de acesso suspeita",
    message="Múltiplas tentativas de login falhas",
    metadata={"ip": "1.2.3.4"}
))

# Alertas prontos
await alert_service.alert_integration_failure("stripe", "Connection timeout")
await alert_service.alert_payment_failed("account_123", 9900, "Card declined")
```

### Endpoints

```bash
# Alertas recentes
GET /api/alerts?limit=50&severity=critical

# Estatísticas
GET /api/alerts/stats

# Reconhecer alerta
POST /api/alerts/{alert_id}/acknowledge
```

---

## Logs Detalhados

Sistema de logging estruturado em JSON com contexto completo.

### Arquivos de Log

| Arquivo | Conteúdo |
|---------|----------|
| `quickvet.log` | Todos os logs (DEBUG+) |
| `quickvet_errors.log` | Apenas erros (ERROR+) |
| `quickvet_payments.log` | Logs de Stripe/pagamentos |
| `quickvet_security.log` | Eventos de segurança |
| `quickvet_whatsapp.log` | Webhook WhatsApp |
| `quickvet_rag.log` | Logs do sistema RAG |

### Formato JSON

```json
{
  "timestamp": "2024-01-15T10:30:00.000Z",
  "level": "ERROR",
  "logger": "app.api.webhook_whatsapp",
  "message": "Erro ao processar mensagem",
  "correlation_id": "abc123",
  "source": {
    "module": "webhook_whatsapp",
    "function": "process_message",
    "line": 145
  },
  "request": {
    "path": "/api/webhook/whatsapp",
    "method": "POST",
    "client_ip": "1.2.3.4"
  },
  "exception": {
    "type": "ValueError",
    "message": "Invalid message format",
    "traceback": "...",
    "frames": [...]
  }
}
```

### Sanitização Automática

Dados sensíveis são automaticamente mascarados:

```json
{
  "api_key": "[REDACTED]",
  "password": "[REDACTED]",
  "token": "[REDACTED]"
}
```

---

## Testes Automatizados

Estrutura de testes com pytest.

### Executar Testes

```bash
# Todos os testes
pytest

# Com cobertura
pytest --cov=app --cov-report=html

# Testes unitários apenas
pytest tests/unit/

# Testes de integração
pytest tests/integration/

# Teste específico
pytest -k "test_message_formatter"

# Verbose
pytest -v --tb=long
```

### Estrutura

```
tests/
├── conftest.py           # Fixtures compartilhadas
├── unit/                 # Testes unitários (sem deps externas)
│   ├── test_message_formatter.py
│   ├── test_auth.py
│   └── ...
├── integration/          # Testes de integração
│   ├── test_api_endpoints.py
│   └── ...
└── e2e/                  # Testes end-to-end
```

### Fixtures Disponíveis

```python
# No conftest.py
@pytest.fixture
def client():                    # Cliente FastAPI síncrono
@pytest.fixture
def mock_redis():                # Mock do Redis
@pytest.fixture
def mock_db():                   # Mock do PostgreSQL
@pytest.fixture
def mock_openai():               # Mock do OpenAI
@pytest.fixture
def sample_whatsapp_message():   # Mensagem WhatsApp exemplo
@pytest.fixture
def jwt_token():                 # Token JWT válido
```

---

## Variáveis de Ambiente Completas

```env
# ==================== DATABASE ====================
DATABASE_URL=postgresql://user:pass@host:port/quickvet

# ==================== REDIS ====================
REDIS_URL=redis://localhost:6379/0

# ==================== OPENAI ====================
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o

# ==================== RAG ====================
RETRIEVAL_MODE=auto  # vector, structural, auto

# ==================== CACHE ====================
CACHE_TTL_VECTOR=3600
CACHE_TTL_STRUCTURAL=1800
CACHE_TTL_EMBEDDING=604800
CACHE_WARMUP_ENABLED=true

# ==================== RATE LIMITING ====================
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
RATE_LIMIT_WHITELIST=127.0.0.1

# ==================== AUTH ====================
JWT_SECRET=seu_secret_muito_seguro_aqui
JWT_EXPIRATION_HOURS=24

# ==================== ALERTAS ====================
ALERT_WEBHOOK_URL=https://n8n.exemplo.com/webhook/alerts
ALERT_COOLDOWN_MINUTES=15

# ==================== STRIPE ====================
STRIPE_SECRET_KEY=sk_xxx
STRIPE_PUBLISHABLE_KEY=pk_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
PLATFORM_PRICE_ID=price_xxx

# ==================== WHATSAPP ====================
WHATSAPP_API_TOKEN=EAAxxxxx
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_VERIFY_TOKEN=quickvet_verify
WHATSAPP_APP_SECRET=abcd1234

# ==================== WEBHOOKS ====================
N8N_WEBHOOK_URL=https://n8n.exemplo.com/webhook/quickvet
WEBHOOK_SECRET=seu_secret_aqui

# ==================== APP ====================
DAILY_MESSAGE_LIMIT=50
ENVIRONMENT=production
FRONTEND_DOMAIN=https://app.quickvet.com.br
LOG_LEVEL=INFO
LOG_DIR=logs
```
