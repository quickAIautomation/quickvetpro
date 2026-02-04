"""
Endpoints da Platform - Dashboard das Clínicas Veterinárias
Conecta o checkout de pagamentos com a plataforma SaaS

IDEMPOTÊNCIA:
- Todas as operações de criação usam INSERT ... ON CONFLICT
- Email é a chave única para contas
- Webhooks podem ser processados múltiplas vezes sem duplicação
"""
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid
from datetime import datetime
import hashlib

from app.services.stripe_service import StripeService
from app.infra.db import get_db_connection
from app.infra.logging_config import get_logger, get_correlation_id
from app.config import settings

router = APIRouter()
logger = get_logger("app.api.platform")
stripe_service = StripeService()


# =============================================================================
# HELPERS PARA IDEMPOTÊNCIA
# =============================================================================

def generate_idempotency_key(email: str, action: str) -> str:
    """
    Gera uma chave de idempotência baseada no email e ação.
    Isso garante que a mesma operação não seja duplicada.
    """
    raw = f"{email.lower()}:{action}:{datetime.utcnow().strftime('%Y-%m-%d')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def log_audit_event(
    db,
    event_type: str,
    account_id: Optional[str],
    email: Optional[str],
    details: dict,
    idempotency_key: Optional[str] = None
):
    """
    Registra evento de auditoria no banco de dados.
    """
    try:
        await db.execute("""
            INSERT INTO audit_logs (
                log_id, event_type, account_id, email, 
                details, idempotency_key, correlation_id, created_at
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
            ON CONFLICT (idempotency_key) DO NOTHING
        """, 
            str(uuid.uuid4()),
            event_type,
            account_id,
            email,
            str(details).replace("'", '"'),  # Convert to JSON string
            idempotency_key or str(uuid.uuid4()),
            get_correlation_id(),
            datetime.utcnow()
        )
    except Exception as e:
        logger.warning(f"Falha ao registrar audit log: {str(e)}")


# =============================================================================
# MODELOS
# =============================================================================

class AccountCreate(BaseModel):
    """Criar nova conta de clínica"""
    email: EmailStr


class LoginRequest(BaseModel):
    """Login por email"""
    email: EmailStr


class AccountResponse(BaseModel):
    """Resposta da conta"""
    account_id: str
    email: str
    plan_type: Optional[str] = None
    plan_status: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    needs_onboarding: bool = True


class SubscribeRequest(BaseModel):
    """Request para assinar plataforma"""
    accountId: str
    lookupKey: Optional[str] = "professional_plan"


class ProductCreate(BaseModel):
    """Criar produto/serviço da clínica"""
    accountId: str
    productName: str
    productDescription: Optional[str] = ""
    productPrice: int  # em centavos


# =============================================================================
# ENDPOINTS DE CONTA
# =============================================================================

@router.post("/login-by-email")
async def login_by_email(data: LoginRequest):
    """
    Verifica se o email existe no banco (cliente que já pagou via Stripe).
    Retorna os dados da conta se existir, ou 404 se não existir.
    
    IDEMPOTENTE: Múltiplas chamadas retornam o mesmo resultado.
    """
    try:
        db = await get_db_connection()
        email_normalized = data.email.lower().strip()
        
        logger.info(
            f"Tentativa de login",
            email=email_normalized,
            action="login_attempt"
        )
        
        # Buscar conta pelo email
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE email = $1",
            email_normalized
        )
        
        if not account:
            logger.warning(
                f"Login falhou - email não encontrado",
                email=email_normalized,
                action="login_not_found"
            )
            raise HTTPException(
                status_code=404,
                detail="Email não encontrado. Faça uma assinatura primeiro."
            )
        
        # Verificar se o plano está ativo
        if account['plan_status'] != 'active':
            logger.warning(
                f"Login falhou - plano inativo",
                email=email_normalized,
                account_id=account['account_id'],
                plan_status=account['plan_status'],
                action="login_inactive"
            )
            raise HTTPException(
                status_code=403,
                detail="Assinatura não está ativa. Complete o pagamento."
            )
        
        # Registrar login bem-sucedido
        await log_audit_event(
            db,
            event_type="LOGIN_SUCCESS",
            account_id=account['account_id'],
            email=email_normalized,
            details={"plan_type": account['plan_type']}
        )
        
        logger.info(
            f"Login bem-sucedido",
            email=email_normalized,
            account_id=account['account_id'],
            plan_type=account['plan_type'],
            action="login_success"
        )
        
        return JSONResponse({
            "account_id": account['account_id'],
            "email": account['email'],
            "plan_type": account['plan_type'],
            "plan_status": account['plan_status'],
            "clinic_name": account['clinic_name'],
            "needs_onboarding": False
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro ao fazer login: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro ao verificar email")


@router.post("/account")
async def create_account(
    data: AccountCreate,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """
    Cria uma nova conta de clínica na plataforma.
    
    IDEMPOTENTE: 
    - Se a conta já existir (mesmo email), retorna a conta existente.
    - Usa INSERT ... ON CONFLICT para evitar duplicação em requests paralelas.
    - Aceita header X-Idempotency-Key para garantia adicional.
    """
    try:
        db = await get_db_connection()
        email_normalized = data.email.lower().strip()
        
        # Gerar chave de idempotência se não fornecida
        idempotency_key = x_idempotency_key or generate_idempotency_key(email_normalized, "create_account")
        
        logger.info(
            f"Criando conta",
            email=email_normalized,
            idempotency_key=idempotency_key,
            action="account_create_start"
        )
        
        # Gerar account_id antes do INSERT
        account_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        # INSERT com ON CONFLICT para IDEMPOTÊNCIA
        # Se email já existir, não faz nada (DO NOTHING)
        await db.execute("""
            INSERT INTO accounts (account_id, email, plan_type, plan_status, created_at)
            VALUES ($1, $2, 'free', 'pending', $3)
            ON CONFLICT (email) DO NOTHING
        """, account_id, email_normalized, now)
        
        # Buscar a conta (seja a nova ou a existente)
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE email = $1",
            email_normalized
        )
        
        if not account:
            # Isso não deveria acontecer, mas por segurança
            logger.error(
                f"Conta não encontrada após INSERT",
                email=email_normalized,
                action="account_create_error"
            )
            raise HTTPException(status_code=500, detail="Erro ao criar conta")
        
        # Verificar se é conta nova ou existente
        is_new = account['account_id'] == account_id
        
        # Registrar evento de auditoria
        await log_audit_event(
            db,
            event_type="ACCOUNT_CREATED" if is_new else "ACCOUNT_EXISTS",
            account_id=account['account_id'],
            email=email_normalized,
            details={"is_new": is_new, "plan_type": account['plan_type']},
            idempotency_key=idempotency_key
        )
        
        logger.info(
            f"Conta {'criada' if is_new else 'já existente'}",
            email=email_normalized,
            account_id=account['account_id'],
            is_new=is_new,
            action="account_create_complete"
        )
        
        return JSONResponse({
            "account_id": account['account_id'],
            "email": account['email'],
            "plan_type": account['plan_type'],
            "plan_status": account['plan_status'],
            "stripe_customer_id": account['stripe_customer_id'],
            "needs_onboarding": account['plan_status'] != 'active',
            "is_new": is_new  # Indica se foi criada agora ou já existia
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro ao criar conta: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro ao criar conta")


@router.get("/account/{account_id}")
async def get_account(account_id: str):
    """Retorna informações da conta"""
    try:
        db = await get_db_connection()
        
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE account_id = $1",
            account_id
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="Conta não encontrada")
        
        return JSONResponse({
            "account_id": account['account_id'],
            "email": account['email'],
            "plan_type": account['plan_type'],
            "plan_status": account['plan_status'],
            "stripe_customer_id": account['stripe_customer_id'],
            "needs_onboarding": account['plan_status'] != 'active'
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar conta: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar conta")


@router.get("/account-status")
async def get_account_status(account_id: str):
    """Retorna status da conta para o frontend"""
    try:
        db = await get_db_connection()
        
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE account_id = $1",
            account_id
        )
        
        if not account:
            return JSONResponse({
                "needsOnboarding": True,
                "chargesEnabled": False,
                "payoutsEnabled": False
            })
        
        return JSONResponse({
            "needsOnboarding": account['plan_status'] != 'active',
            "chargesEnabled": account['plan_status'] == 'active',
            "payoutsEnabled": account['plan_status'] == 'active'
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar status: {str(e)}", exc_info=True)
        return JSONResponse({
            "needsOnboarding": True,
            "chargesEnabled": False,
            "payoutsEnabled": False
        })


# =============================================================================
# ENDPOINTS DE ASSINATURA
# =============================================================================

@router.post("/subscribe-to-platform")
async def subscribe_to_platform(request: Request, data: SubscribeRequest):
    """
    Cria checkout session para assinatura da plataforma.
    Redireciona o cliente para o Stripe Checkout.
    """
    try:
        db = await get_db_connection()
        
        # Buscar conta
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE account_id = $1",
            data.accountId
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="Conta não encontrada")
        
        # Determinar URLs
        base_url = str(request.base_url).rstrip('/')
        # Redireciona para a Platform após sucesso
        success_url = f"http://localhost:3000/?success=true&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"http://localhost:3000/?canceled=true"
        
        # Criar checkout session
        checkout_session = stripe_service.create_checkout_session(
            lookup_key=data.lookupKey or "professional_plan",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=account['email'],
            metadata={
                'account_id': data.accountId,
                'platform': 'quickvet'
            }
        )
        
        logger.info(f"Checkout session criada para conta {data.accountId}")
        
        return JSONResponse({"url": checkout_session.url})
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Erro de validação: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erro ao criar checkout: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar checkout")


@router.post("/create-portal-session")
async def create_portal_session(request: Request, session_id: str = None, account_id: str = None):
    """
    Cria portal session para gerenciar assinatura.
    Pode receber session_id (do checkout) ou account_id diretamente.
    """
    try:
        db = await get_db_connection()
        customer_id = None
        
        if session_id:
            # Recuperar customer_id do checkout session
            checkout_session = stripe_service.get_checkout_session(session_id)
            customer_id = checkout_session.customer
        elif account_id:
            # Buscar customer_id da conta
            account = await db.fetchrow(
                "SELECT stripe_customer_id FROM accounts WHERE account_id = $1",
                account_id
            )
            if account:
                customer_id = account['stripe_customer_id']
        
        if not customer_id:
            raise HTTPException(
                status_code=400,
                detail="Customer não encontrado. Assine um plano primeiro."
            )
        
        # Criar portal session
        return_url = f"{settings.frontend_domain}/"
        portal_session = stripe_service.create_portal_session(
            customer_id=customer_id,
            return_url=return_url
        )
        
        return JSONResponse({"url": portal_session.url})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao criar portal: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar portal")


# =============================================================================
# ENDPOINTS DE PRODUTOS
# =============================================================================

@router.post("/create-product")
async def create_product(data: ProductCreate):
    """
    Cria um produto/serviço para a clínica.
    Este é o catálogo de serviços que a clínica oferece.
    """
    try:
        db = await get_db_connection()
        
        # Verificar se a conta existe e está ativa
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE account_id = $1",
            data.accountId
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="Conta não encontrada")
        
        if account['plan_status'] != 'active':
            raise HTTPException(
                status_code=403,
                detail="Assine um plano para criar produtos"
            )
        
        # Criar produto no banco local
        product_id = str(uuid.uuid4())
        
        await db.execute("""
            INSERT INTO products (
                product_id, account_id, name, description, price_cents, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6)
        """, product_id, data.accountId, data.productName, 
            data.productDescription, data.productPrice, datetime.utcnow())
        
        logger.info(f"Produto criado: {product_id} para conta {data.accountId}")
        
        return JSONResponse({
            "product_id": product_id,
            "name": data.productName,
            "description": data.productDescription,
            "price_cents": data.productPrice
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao criar produto: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar produto")


@router.get("/products/{account_id}")
async def get_products(account_id: str):
    """Lista produtos de uma conta"""
    try:
        db = await get_db_connection()
        
        products = await db.fetch(
            "SELECT * FROM products WHERE account_id = $1 ORDER BY created_at DESC",
            account_id
        )
        
        return JSONResponse({
            "products": [
                {
                    "product_id": p['product_id'],
                    "name": p['name'],
                    "description": p['description'],
                    "price_cents": p['price_cents']
                }
                for p in products
            ]
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar produtos: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar produtos")


# =============================================================================
# WEBHOOK HANDLER PARA ATUALIZAR CONTAS
# =============================================================================

async def handle_platform_checkout_completed(session: dict):
    """
    Processa checkout completado e atualiza a conta na plataforma.
    Chamado pelo webhook principal do Stripe.
    
    IDEMPOTENTE:
    - Usa INSERT ... ON CONFLICT para evitar duplicação
    - Mesmo evento pode ser processado múltiplas vezes sem efeitos colaterais
    - Chave de idempotência baseada no checkout_session_id
    """
    try:
        db = await get_db_connection()
        
        checkout_session_id = session.get('id')
        customer_id = session.get('customer')
        subscription_id = session.get('subscription')
        customer_email = session.get('customer_email') or session.get('customer_details', {}).get('email')
        metadata = session.get('metadata', {})
        account_id = metadata.get('account_id')
        
        # Chave de idempotência baseada no checkout session
        idempotency_key = f"checkout_{checkout_session_id}"
        
        logger.info(
            f"Processando checkout completado",
            checkout_session_id=checkout_session_id,
            account_id=account_id,
            customer_id=customer_id,
            email=customer_email,
            idempotency_key=idempotency_key,
            action="webhook_checkout_start"
        )
        
        # Verificar se já foi processado (idempotência)
        already_processed = await db.fetchrow(
            "SELECT 1 FROM audit_logs WHERE idempotency_key = $1",
            idempotency_key
        )
        
        if already_processed:
            logger.info(
                f"Checkout já processado anteriormente",
                idempotency_key=idempotency_key,
                action="webhook_checkout_idempotent"
            )
            return
        
        # Determinar o tipo de plano baseado no preço
        plan_type = 'professional'  # default
        
        if subscription_id:
            import stripe
            stripe.api_key = settings.stripe_secret_key
            try:
                subscription = stripe.Subscription.retrieve(subscription_id)
                
                if subscription.items and subscription.items.data:
                    price = subscription.items.data[0].price
                    if hasattr(price, 'lookup_key') and price.lookup_key:
                        if 'starter' in price.lookup_key:
                            plan_type = 'starter'
                        elif 'enterprise' in price.lookup_key:
                            plan_type = 'enterprise'
                        else:
                            plan_type = 'professional'
            except Exception as e:
                logger.warning(f"Erro ao buscar subscription: {str(e)}")
        
        now = datetime.utcnow()
        email_normalized = customer_email.lower().strip() if customer_email else None
        final_account_id = None
        
        # Atualizar conta se temos account_id
        if account_id:
            await db.execute("""
                UPDATE accounts
                SET stripe_customer_id = $1,
                    stripe_subscription_id = $2,
                    plan_type = $3,
                    plan_status = 'active',
                    updated_at = $4
                WHERE account_id = $5
            """, customer_id, subscription_id, plan_type, now, account_id)
            
            final_account_id = account_id
            logger.info(
                f"Conta atualizada com plano",
                account_id=account_id,
                plan_type=plan_type,
                action="webhook_account_updated"
            )
            
        # Ou criar/atualizar conta pelo email (IDEMPOTENTE com ON CONFLICT)
        elif email_normalized:
            # Usar INSERT ... ON CONFLICT para idempotência
            new_account_id = str(uuid.uuid4())
            
            await db.execute("""
                INSERT INTO accounts (
                    account_id, email, stripe_customer_id, stripe_subscription_id,
                    plan_type, plan_status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, 'active', $6, $6)
                ON CONFLICT (email) DO UPDATE SET
                    stripe_customer_id = EXCLUDED.stripe_customer_id,
                    stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                    plan_type = EXCLUDED.plan_type,
                    plan_status = 'active',
                    updated_at = EXCLUDED.updated_at
            """, new_account_id, email_normalized, customer_id, 
                subscription_id, plan_type, now)
            
            # Buscar o account_id final (pode ser novo ou existente)
            result = await db.fetchrow(
                "SELECT account_id FROM accounts WHERE email = $1",
                email_normalized
            )
            final_account_id = result['account_id'] if result else new_account_id
            
            logger.info(
                f"Conta criada/atualizada via checkout",
                account_id=final_account_id,
                email=email_normalized,
                plan_type=plan_type,
                action="webhook_account_upserted"
            )
        
        # Registrar evento de auditoria (com idempotência)
        await log_audit_event(
            db,
            event_type="CHECKOUT_COMPLETED",
            account_id=final_account_id,
            email=email_normalized,
            details={
                "checkout_session_id": checkout_session_id,
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "plan_type": plan_type
            },
            idempotency_key=idempotency_key
        )
        
        logger.info(
            f"Checkout processado com sucesso",
            account_id=final_account_id,
            plan_type=plan_type,
            idempotency_key=idempotency_key,
            action="webhook_checkout_complete"
        )
        
    except Exception as e:
        logger.exception(f"Erro ao processar platform checkout: {str(e)}")
