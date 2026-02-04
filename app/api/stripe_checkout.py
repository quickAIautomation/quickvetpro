"""
Endpoints para checkout e pagamentos do Stripe
"""
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.stripe_service import StripeService
from app.services.plan_service import PlanService
from app.services.webhook_dispatcher import webhook_dispatcher
from app.infra.db import get_db_connection
from app.config import settings
from app.api.platform import handle_platform_checkout_completed

router = APIRouter()
logger = logging.getLogger(__name__)

stripe_service = StripeService()
plan_service = PlanService()


@router.get("/products")
async def get_stripe_products(active_only: bool = True):
    """
    Lista produtos e preços cadastrados no Stripe
    
    Args:
        active_only: Se True, retorna apenas produtos ativos
        
    Returns:
        Lista de produtos com seus preços
    """
    try:
        products = stripe_service.list_products(active_only=active_only)
        return JSONResponse({"products": products})
    except Exception as e:
        logger.error(f"Erro ao listar produtos do Stripe: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar produtos")


@router.get("/prices")
async def get_stripe_prices(lookup_key: str = None):
    """
    Lista preços cadastrados no Stripe
    
    Args:
        lookup_key: Filtrar por lookup_key (opcional)
        
    Returns:
        Lista de preços
    """
    try:
        prices = stripe_service.list_prices(lookup_key=lookup_key)
        return JSONResponse({"prices": prices})
    except Exception as e:
        logger.error(f"Erro ao listar preços do Stripe: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar preços")


@router.get("/status")
async def stripe_status():
    """
    Verifica status da integração Stripe
    
    Returns:
        Status da configuração e contagem de produtos/preços
    """
    try:
        configured = bool(settings.stripe_secret_key)
        
        if not configured:
            return JSONResponse({
                "configured": False,
                "message": "Stripe não configurado"
            })
        
        # Tentar listar produtos para verificar conexão
        try:
            products = stripe_service.list_products(active_only=True)
            prices = stripe_service.list_prices()
            
            return JSONResponse({
                "configured": True,
                "api_key_prefix": settings.stripe_secret_key[:7] + "..." if settings.stripe_secret_key else None,
                "products_count": len(products),
                "prices_count": len(prices),
                "webhook_secret_configured": bool(settings.stripe_webhook_secret)
            })
        except Exception as e:
            return JSONResponse({
                "configured": True,
                "api_key_prefix": settings.stripe_secret_key[:7] + "..." if settings.stripe_secret_key else None,
                "connection_error": str(e),
                "webhook_secret_configured": bool(settings.stripe_webhook_secret)
            })
            
    except Exception as e:
        logger.error(f"Erro ao verificar status Stripe: {str(e)}", exc_info=True)
        return JSONResponse({
            "configured": False,
            "error": str(e)
        }, status_code=500)


class CheckoutRequest(BaseModel):
    """Request para criar checkout session"""
    lookup_key: str
    user_id: Optional[str] = None
    customer_email: Optional[str] = None


@router.post("/create-checkout-session")
async def create_checkout_session(
    request: Request,
    lookup_key: Optional[str] = Form(None),
    price_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    customer_email: Optional[str] = Form(None),
    stripe_account: Optional[str] = Form(None),
    application_fee_amount: Optional[int] = Form(None),
    mode: str = Form("subscription"),
    line_items: Optional[str] = Form(None)  # JSON string
):
    """
    Cria sessão de checkout do Stripe e redireciona para página de pagamento
    
    Suporta:
    - Checkout padrão (subscription ou payment)
    - Stripe Connect (marketplace com stripe_account e application_fee_amount)
    - Line items customizados
    
    Args:
        lookup_key: Chave de lookup do preço no Stripe
        price_id: ID do preço diretamente
        user_id: ID do usuário (opcional)
        customer_email: Email do cliente (opcional)
        stripe_account: ID da conta Stripe Connect (para marketplace)
        application_fee_amount: Taxa da aplicação em centavos (para marketplace)
        mode: 'subscription' ou 'payment'
        line_items: JSON string com array de line items customizados
    """
    try:
        import json
        
        # Determinar URLs de sucesso e cancelamento
        base_url = str(request.base_url).rstrip('/')
        success_url = f"{base_url}/checkout?success=true&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/checkout?canceled=true"
        
        # Metadados para associar ao usuário
        metadata = {}
        if user_id:
            metadata['user_id'] = user_id
        
        # Parse line_items se fornecido
        parsed_line_items = None
        if line_items:
            try:
                parsed_line_items = json.loads(line_items)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="line_items deve ser um JSON válido")
        
        # Validar que pelo menos um método de especificar preço foi fornecido
        if not lookup_key and not price_id and not parsed_line_items:
            raise HTTPException(
                status_code=400,
                detail="É necessário fornecer lookup_key, price_id ou line_items"
            )
        
        # Criar sessão de checkout
        checkout_session = stripe_service.create_checkout_session(
            lookup_key=lookup_key,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata=metadata,
            stripe_account=stripe_account,
            application_fee_amount=application_fee_amount,
            mode=mode,
            line_items=parsed_line_items
        )
        
        # Redirecionar para página de checkout do Stripe
        return RedirectResponse(url=checkout_session.url, status_code=303)
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Erro ao criar checkout session: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erro inesperado ao criar checkout session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao processar checkout")


@router.post("/create-portal-session")
async def create_portal_session(
    request: Request,
    session_id: str = Form(...)
):
    """
    Cria sessão do customer portal do Stripe para gerenciar assinatura
    
    Args:
        session_id: ID da sessão de checkout (para obter customer_id)
    """
    try:
        # Recuperar sessão de checkout para obter customer_id
        checkout_session = stripe_service.get_checkout_session(session_id)
        
        if not checkout_session.customer:
            raise HTTPException(
                status_code=400,
                detail="Sessão de checkout não possui cliente associado"
            )
        
        # Determinar URL de retorno
        base_url = str(request.base_url).rstrip('/')
        return_url = f"{base_url}/checkout"
        
        # Criar sessão do portal
        portal_session = stripe_service.create_portal_session(
            customer_id=checkout_session.customer,
            return_url=return_url
        )
        
        # Redirecionar para portal do Stripe
        return RedirectResponse(url=portal_session.url, status_code=303)
        
    except Exception as e:
        logger.error(f"Erro ao criar portal session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao processar portal")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Webhook do Stripe para receber eventos de pagamento
    
    Processa eventos como:
    - checkout.session.completed
    - customer.subscription.*
    - invoice.*
    - payment_intent.*
    - setup_intent.*
    - charge.*
    - customer.*
    - account.* (Stripe Connect)
    
    Estrutura esperada do evento:
    {
        "id": "evt_...",
        "type": "event.type",
        "data": {
            "object": {...}
        },
        "livemode": false,
        ...
    }
    """
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        # Obter webhook secret das variáveis de ambiente
        webhook_secret = settings.stripe_webhook_secret or settings.stripe_secret_key
        
        event = None
        event_type = None
        data_object = None
        
        if not webhook_secret:
            logger.warning("Webhook secret não configurado, processando sem validação")
            # Processar sem validação (apenas para desenvolvimento)
            import json
            try:
                event_data = await request.json()
                event = event_data
                event_type = event_data.get('type')
                data_object = event_data.get('data', {}).get('object', {})
            except Exception:
                # Tentar parse do payload raw
                event_data = json.loads(payload.decode('utf-8'))
                event = event_data
                event_type = event_data.get('type')
                data_object = event_data.get('data', {}).get('object', {})
        else:
            # Validar e construir evento
            try:
                event = stripe_service.construct_webhook_event(
                    payload=payload,
                    sig_header=sig_header,
                    webhook_secret=webhook_secret
                )
                event_type = event['type']
                data_object = event['data']['object']
            except Exception as e:
                logger.error(f"Erro ao validar webhook: {str(e)}")
                # Tentar processar mesmo assim (para desenvolvimento)
                import json
                event_data = json.loads(payload.decode('utf-8'))
                event = event_data
                event_type = event_data.get('type')
                data_object = event_data.get('data', {}).get('object', {})
        
        # Log detalhado do evento
        event_id = event.get('id') if isinstance(event, dict) else data_object.get('id', 'unknown')
        logger.info(
            f"Evento recebido do Stripe",
            event_type=event_type,
            event_id=event_id,
            livemode=event.get('livemode', False) if isinstance(event, dict) else False
        )
        
        # Processar eventos principais
        if event_type == 'checkout.session.completed':
            await handle_checkout_completed(data_object)
            # Também processar para a Platform (contas de clínicas)
            await handle_platform_checkout_completed(data_object)
        
        # Eventos de Subscription
        elif event_type == 'customer.subscription.created':
            await handle_subscription_created(data_object)
        elif event_type == 'customer.subscription.updated':
            await handle_subscription_updated(data_object)
        elif event_type == 'customer.subscription.deleted':
            await handle_subscription_deleted(data_object)
        elif event_type == 'customer.subscription.trial_will_end':
            await handle_subscription_trial_will_end(data_object)
        
        # Eventos de Invoice
        elif event_type == 'invoice.paid':
            await handle_invoice_paid(data_object)
        elif event_type == 'invoice.payment_failed':
            await handle_invoice_payment_failed(data_object)
        elif event_type == 'invoice.payment_action_required':
            await handle_invoice_payment_action_required(data_object)
        
        # Eventos de Payment Intent
        elif event_type == 'payment_intent.succeeded':
            await handle_payment_intent_succeeded(data_object)
        elif event_type == 'payment_intent.payment_failed':
            await handle_payment_intent_failed(data_object)
        elif event_type == 'payment_intent.requires_action':
            await handle_payment_intent_requires_action(data_object)
        
        # Eventos de Setup Intent
        elif event_type == 'setup_intent.created':
            await handle_setup_intent_created(data_object)
        elif event_type == 'setup_intent.succeeded':
            await handle_setup_intent_succeeded(data_object)
        elif event_type == 'setup_intent.setup_failed':
            await handle_setup_intent_failed(data_object)
        
        # Eventos de Customer
        elif event_type == 'customer.created':
            await handle_customer_created(data_object)
        elif event_type == 'customer.updated':
            await handle_customer_updated(data_object)
        elif event_type == 'customer.deleted':
            await handle_customer_deleted(data_object)
        
        # Eventos de Charge
        elif event_type == 'charge.succeeded':
            await handle_charge_succeeded(data_object)
        elif event_type == 'charge.failed':
            await handle_charge_failed(data_object)
        elif event_type == 'charge.refunded':
            await handle_charge_refunded(data_object)
        
        # Eventos de Connect (Marketplace)
        elif event_type == 'account.updated':
            await handle_account_updated(data_object)
        elif event_type == 'account.application.deauthorized':
            await handle_account_deauthorized(data_object)
        
        # Eventos de Entitlements
        elif event_type == 'entitlements.active_entitlement_summary.updated':
            logger.info(f"Resumo de entitlements atualizado: {data_object.get('id')}")
        
        # Eventos não críticos (apenas log)
        elif event_type in [
            'checkout.session.async_payment_succeeded',
            'checkout.session.async_payment_failed',
            'customer.source.created',
            'customer.source.updated',
            'customer.source.deleted',
            'payment_method.attached',
            'payment_method.detached'
        ]:
            logger.info(f"Evento recebido (não processado): {event_type} - {data_object.get('id', 'N/A')}")
        
        else:
            logger.info(f"Evento não mapeado: {event_type} - {data_object.get('id', 'N/A')}")
        
        return JSONResponse({"status": "success", "event_type": event_type})
        
    except ValueError as e:
        logger.error(f"Payload inválido: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao processar webhook")


async def handle_checkout_completed(session: dict):
    """Processa checkout completado"""
    try:
        customer_id = session.get('customer')
        subscription_id = session.get('subscription')
        metadata = session.get('metadata', {})
        user_id = metadata.get('user_id')
        
        logger.info(f"Checkout completado - Customer: {customer_id}, Subscription: {subscription_id}")
        
        if user_id and subscription_id:
            # Obter informações da subscription do Stripe para identificar o plano
            import stripe
            stripe.api_key = settings.stripe_secret_key
            
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Extrair tipo de plano do price/product
            plan_type = "free"  # Default
            
            if subscription.items.data:
                price = subscription.items.data[0].price
                product = price.product if hasattr(price, 'product') else None
                
                # Tentar extrair do lookup_key do price
                if price.lookup_key:
                    lookup_key = price.lookup_key.lower()
                    # Mapear lookup_key para tipo de plano
                    if 'monthly' in lookup_key or 'mensal' in lookup_key:
                        plan_type = "monthly"
                    elif 'quarterly' in lookup_key or 'trimestral' in lookup_key:
                        plan_type = "quarterly"
                    elif 'semiannual' in lookup_key or 'semestral' in lookup_key:
                        plan_type = "semiannual"
                    elif 'annual' in lookup_key or 'anual' in lookup_key or 'yearly' in lookup_key:
                        plan_type = "annual"
                    elif 'enterprise' in lookup_key:
                        plan_type = "enterprise"
                
                # Se não encontrou no lookup_key, tentar no nome do produto
                elif product and isinstance(product, str):
                    product_obj = stripe.Product.retrieve(product)
                    product_name = product_obj.name.lower()
                    if 'monthly' in product_name or 'mensal' in product_name:
                        plan_type = "monthly"
                    elif 'quarterly' in product_name or 'trimestral' in product_name:
                        plan_type = "quarterly"
                    elif 'semiannual' in product_name or 'semestral' in product_name:
                        plan_type = "semiannual"
                    elif 'annual' in product_name or 'anual' in product_name:
                        plan_type = "annual"
                    elif 'enterprise' in product_name:
                        plan_type = "enterprise"
                
                # Fallback: inferir do intervalo de cobrança
                elif price.recurring:
                    interval = price.recurring.interval
                    interval_count = price.recurring.interval_count or 1
                    
                    if interval == 'month' and interval_count == 1:
                        plan_type = "monthly"
                    elif interval == 'month' and interval_count == 3:
                        plan_type = "quarterly"
                    elif interval == 'month' and interval_count == 6:
                        plan_type = "semiannual"
                    elif interval == 'year' or (interval == 'month' and interval_count == 12):
                        plan_type = "annual"
            
            logger.info(f"Plano identificado: {plan_type} para usuário {user_id}")
            
            # Atualizar plano do usuário no banco de dados
            db = await get_db_connection()
            
            # Verificar se já existe subscription
            query = """
                SELECT subscription_id FROM subscriptions
                WHERE user_id = $1
            """
            existing = await db.fetchrow(query, user_id)
            
            if existing:
                # Atualizar subscription existente
                update_query = """
                    UPDATE subscriptions
                    SET stripe_subscription_id = $1,
                        stripe_customer_id = $2,
                        status = 'active',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = $3
                """
                await db.execute(update_query, subscription_id, customer_id, user_id)
            else:
                # Criar nova subscription
                insert_query = """
                    INSERT INTO subscriptions (
                        user_id, stripe_customer_id, stripe_subscription_id, status
                    )
                    VALUES ($1, $2, $3, 'active')
                """
                await db.execute(insert_query, user_id, customer_id, subscription_id)
            
            # Atualizar plano do usuário com o tipo correto
            plan_query = """
                INSERT INTO plans (user_id, plan_type, status)
                VALUES ($1, $2, 'active')
                ON CONFLICT (user_id) DO UPDATE
                SET plan_type = $2, status = 'active', updated_at = CURRENT_TIMESTAMP
            """
            await db.execute(plan_query, user_id, plan_type)
            
            logger.info(f"Plano {plan_type} ativado para usuário {user_id}")
            
            # Invalidar cache do rate limiter
            from app.middleware.rate_limit import on_plan_change
            await on_plan_change(user_id, plan_type)
            
            # Disparar webhook para n8n
            await webhook_dispatcher.notify_subscription_created(
                account_id=user_id,
                plan_type=plan_type,
                stripe_subscription_id=subscription_id,
                email=session.get('customer_email', '')
            )
            
    except Exception as e:
        logger.error(f"Erro ao processar checkout completado: {str(e)}", exc_info=True)


async def handle_subscription_trial_will_end(subscription: dict):
    """Processa aviso de término de trial"""
    try:
        subscription_id = subscription.get('id')
        customer_id = subscription.get('customer')
        
        logger.info(f"Trial vai terminar: {subscription_id} para customer {customer_id}")
        
        # Buscar user_id
        db = await get_db_connection()
        result = await db.fetchrow(
            "SELECT user_id FROM subscriptions WHERE stripe_subscription_id = $1",
            subscription_id
        )
        
        if result:
            user_id = result['user_id']
            # Disparar webhook para n8n (aviso de trial terminando)
            await webhook_dispatcher.notify_subscription_expired(
                account_id=user_id,
                plan_type="trial",
                reason="trial_ending"
            )
        
    except Exception as e:
        logger.error(f"Erro ao processar trial_will_end: {str(e)}", exc_info=True)


async def handle_subscription_created(subscription: dict):
    """Processa criação de assinatura"""
    try:
        subscription_id = subscription.get('id')
        customer_id = subscription.get('customer')
        
        logger.info(f"Assinatura criada: {subscription_id} para cliente: {customer_id}")
        
    except Exception as e:
        logger.error(f"Erro ao processar assinatura criada: {str(e)}", exc_info=True)


async def handle_subscription_updated(subscription: dict):
    """Processa atualização de assinatura"""
    try:
        subscription_id = subscription.get('id')
        status = subscription.get('status')
        customer_id = subscription.get('customer')
        
        logger.info(f"Assinatura atualizada: {subscription_id} - Status: {status}")
        
        # Obter user_id da subscription
        db = await get_db_connection()
        user_query = """
            SELECT user_id FROM subscriptions
            WHERE stripe_subscription_id = $1
        """
        result = await db.fetchrow(user_query, subscription_id)
        
        if not result:
            logger.warning(f"Subscription {subscription_id} não encontrada no banco")
            return
        
        user_id = result['user_id']
        
        # Atualizar status no banco de dados
        update_query = """
            UPDATE subscriptions
            SET status = $1, updated_at = CURRENT_TIMESTAMP
            WHERE stripe_subscription_id = $2
        """
        await db.execute(update_query, status, subscription_id)
        
        # Se cancelada ou inativa, desativar plano
        if status in ['canceled', 'unpaid', 'past_due', 'incomplete_expired']:
            plan_query = """
                UPDATE plans
                SET status = 'inactive', updated_at = CURRENT_TIMESTAMP
                WHERE user_id = $1
            """
            await db.execute(plan_query, user_id)
            logger.info(f"Plano desativado para usuário {user_id}")
            
            # Invalidar cache do rate limiter (volta para free)
            from app.middleware.rate_limit import on_plan_change
            await on_plan_change(user_id, "free")
            
            # Disparar webhook para n8n
            if status == 'canceled':
                await webhook_dispatcher.notify_subscription_cancelled(
                    account_id=user_id,
                    plan_type="free",
                    reason="subscription_updated"
                )
            elif status in ['unpaid', 'past_due']:
                await webhook_dispatcher.notify_payment_failed(
                    account_id=user_id,
                    amount=0,
                    currency="brl",
                    error_message=f"Status: {status}"
                )
        
        # Se ativa, verificar se o plano mudou
        elif status == 'active':
            # Obter informações da subscription do Stripe para identificar o plano
            import stripe
            stripe.api_key = settings.stripe_secret_key
            
            try:
                stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                plan_type = "free"  # Default
                
                if stripe_subscription.items.data:
                    price = stripe_subscription.items.data[0].price
                    
                    # Extrair tipo de plano (mesma lógica do handle_checkout_completed)
                    if price.lookup_key:
                        lookup_key = price.lookup_key.lower()
                        if 'monthly' in lookup_key or 'mensal' in lookup_key:
                            plan_type = "monthly"
                        elif 'quarterly' in lookup_key or 'trimestral' in lookup_key:
                            plan_type = "quarterly"
                        elif 'semiannual' in lookup_key or 'semestral' in lookup_key:
                            plan_type = "semiannual"
                        elif 'annual' in lookup_key or 'anual' in lookup_key or 'yearly' in lookup_key:
                            plan_type = "annual"
                        elif 'enterprise' in lookup_key:
                            plan_type = "enterprise"
                    elif price.recurring:
                        interval = price.recurring.interval
                        interval_count = price.recurring.interval_count or 1
                        
                        if interval == 'month' and interval_count == 1:
                            plan_type = "monthly"
                        elif interval == 'month' and interval_count == 3:
                            plan_type = "quarterly"
                        elif interval == 'month' and interval_count == 6:
                            plan_type = "semiannual"
                        elif interval == 'year' or (interval == 'month' and interval_count == 12):
                            plan_type = "annual"
                
                # Verificar se o plano mudou
                current_plan = await db.fetchrow(
                    "SELECT plan_type FROM plans WHERE user_id = $1",
                    user_id
                )
                
                if current_plan and current_plan['plan_type'] != plan_type:
                    logger.info(f"Plano mudou de {current_plan['plan_type']} para {plan_type} para usuário {user_id}")
                    
                    # Atualizar plano
                    plan_query = """
                        UPDATE plans
                        SET plan_type = $1, status = 'active', updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = $2
                    """
                    await db.execute(plan_query, plan_type, user_id)
                    
                    # Invalidar cache do rate limiter
                    from app.middleware.rate_limit import on_plan_change
                    await on_plan_change(user_id, plan_type)
                    
                    # Disparar webhook para n8n
                    await webhook_dispatcher.notify_subscription_updated(
                        account_id=user_id,
                        old_plan=current_plan['plan_type'],
                        new_plan=plan_type
                    )
                else:
                    # Apenas garantir que está ativo
                    plan_query = """
                        UPDATE plans
                        SET status = 'active', updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = $1
                    """
                    await db.execute(plan_query, user_id)
                    
            except Exception as e:
                logger.warning(f"Erro ao buscar subscription do Stripe: {e}")
        
    except Exception as e:
        logger.error(f"Erro ao processar assinatura atualizada: {str(e)}", exc_info=True)


async def handle_subscription_deleted(subscription: dict):
    """Processa cancelamento de assinatura"""
    try:
        subscription_id = subscription.get('id')
        
        logger.info(f"Assinatura cancelada: {subscription_id}")
        
        # Atualizar no banco de dados
        db = await get_db_connection()
        
        # Obter user_id
        user_query = """
            SELECT user_id FROM subscriptions
            WHERE stripe_subscription_id = $1
        """
        result = await db.fetchrow(user_query, subscription_id)
        
        if result:
            user_id = result['user_id']
            
            # Atualizar subscription
            update_query = """
                UPDATE subscriptions
                SET status = 'canceled', updated_at = CURRENT_TIMESTAMP
                WHERE stripe_subscription_id = $1
            """
            await db.execute(update_query, subscription_id)
            
            # Desativar plano
            plan_query = """
                UPDATE plans
                SET status = 'inactive', updated_at = CURRENT_TIMESTAMP
                WHERE user_id = $1
            """
            await db.execute(plan_query, user_id)
            
            logger.info(f"Plano cancelado para usuário {user_id}")
            
            # Disparar webhook para n8n
            await webhook_dispatcher.notify_subscription_cancelled(
                account_id=user_id,
                plan_type="premium",
                reason="subscription_deleted"
            )
        
    except Exception as e:
        logger.error(f"Erro ao processar assinatura cancelada: {str(e)}", exc_info=True)


async def handle_invoice_paid(invoice: dict):
    """Processa pagamento de fatura confirmado"""
    try:
        customer_id = invoice.get('customer')
        amount = invoice.get('amount_paid', 0)
        currency = invoice.get('currency', 'brl')
        invoice_url = invoice.get('hosted_invoice_url')
        subscription_id = invoice.get('subscription')
        
        logger.info(f"Pagamento confirmado: {amount} {currency} - Customer: {customer_id}")
        
        # Buscar account_id pelo customer_id
        db = await get_db_connection()
        result = await db.fetchrow(
            "SELECT user_id FROM subscriptions WHERE stripe_customer_id = $1",
            customer_id
        )
        
        account_id = result['user_id'] if result else customer_id
        
        # Disparar webhook para n8n
        await webhook_dispatcher.notify_payment_succeeded(
            account_id=account_id,
            amount=amount,
            currency=currency,
            invoice_url=invoice_url
        )
        
    except Exception as e:
        logger.error(f"Erro ao processar pagamento confirmado: {str(e)}", exc_info=True)


async def handle_invoice_payment_failed(invoice: dict):
    """Processa falha no pagamento de fatura"""
    try:
        customer_id = invoice.get('customer')
        amount = invoice.get('amount_due', 0)
        currency = invoice.get('currency', 'brl')
        attempt_count = invoice.get('attempt_count', 0)
        
        logger.warning(f"Pagamento falhou: {amount} {currency} - Customer: {customer_id} (tentativa {attempt_count})")
        
        # Buscar account_id pelo customer_id
        db = await get_db_connection()
        result = await db.fetchrow(
            "SELECT user_id FROM subscriptions WHERE stripe_customer_id = $1",
            customer_id
        )
        
        account_id = result['user_id'] if result else customer_id
        
        # Disparar webhook para n8n
        await webhook_dispatcher.notify_payment_failed(
            account_id=account_id,
            amount=amount,
            currency=currency,
            error_message=f"Tentativa {attempt_count} de cobrança falhou"
        )
        
    except Exception as e:
        logger.error(f"Erro ao processar falha de pagamento: {str(e)}", exc_info=True)


# ==================== HANDLERS PARA EVENTOS ADICIONAIS ====================

async def handle_setup_intent_created(setup_intent: dict):
    """Processa criação de setup intent"""
    try:
        setup_intent_id = setup_intent.get('id')
        customer_id = setup_intent.get('customer')
        
        logger.info(f"Setup Intent criado: {setup_intent_id} para customer {customer_id}")
        # Setup intents são usados para salvar métodos de pagamento
        # Geralmente não requerem ação imediata
        
    except Exception as e:
        logger.error(f"Erro ao processar setup_intent.created: {str(e)}", exc_info=True)


async def handle_setup_intent_succeeded(setup_intent: dict):
    """Processa setup intent bem-sucedido"""
    try:
        setup_intent_id = setup_intent.get('id')
        customer_id = setup_intent.get('customer')
        payment_method = setup_intent.get('payment_method')
        
        logger.info(
            f"Setup Intent bem-sucedido: {setup_intent_id}",
            extra={
                "customer_id": customer_id,
                "payment_method": payment_method
            }
        )
        # Método de pagamento foi salvo com sucesso
        
    except Exception as e:
        logger.error(f"Erro ao processar setup_intent.succeeded: {str(e)}", exc_info=True)


async def handle_setup_intent_failed(setup_intent: dict):
    """Processa falha de setup intent"""
    try:
        setup_intent_id = setup_intent.get('id')
        customer_id = setup_intent.get('customer')
        error = setup_intent.get('last_setup_error', {})
        
        logger.warning(
            f"Setup Intent falhou: {setup_intent_id}",
            extra={
                "customer_id": customer_id,
                "error_type": error.get('type'),
                "error_message": error.get('message')
            }
        )
        
    except Exception as e:
        logger.error(f"Erro ao processar setup_intent.setup_failed: {str(e)}", exc_info=True)


async def handle_payment_intent_succeeded(payment_intent: dict):
    """Processa pagamento bem-sucedido"""
    try:
        payment_intent_id = payment_intent.get('id')
        customer_id = payment_intent.get('customer')
        amount = payment_intent.get('amount')
        currency = payment_intent.get('currency')
        
        logger.info(
            f"Payment Intent bem-sucedido: {payment_intent_id}",
            extra={
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency
            }
        )
        
        # Buscar user_id se possível
        if customer_id:
            db = await get_db_connection()
            result = await db.fetchrow(
                "SELECT user_id FROM subscriptions WHERE stripe_customer_id = $1 LIMIT 1",
                customer_id
            )
            
            if result:
                await webhook_dispatcher.notify_payment_succeeded(
                    account_id=result['user_id'],
                    amount=amount / 100 if amount else 0,  # Converter centavos para reais
                    currency=currency or "brl"
                )
        
    except Exception as e:
        logger.error(f"Erro ao processar payment_intent.succeeded: {str(e)}", exc_info=True)


async def handle_payment_intent_failed(payment_intent: dict):
    """Processa falha de pagamento"""
    try:
        payment_intent_id = payment_intent.get('id')
        customer_id = payment_intent.get('customer')
        error = payment_intent.get('last_payment_error', {})
        
        logger.warning(
            f"Payment Intent falhou: {payment_intent_id}",
            extra={
                "customer_id": customer_id,
                "error_type": error.get('type'),
                "error_message": error.get('message')
            }
        )
        
        # Buscar user_id se possível
        if customer_id:
            db = await get_db_connection()
            result = await db.fetchrow(
                "SELECT user_id FROM subscriptions WHERE stripe_customer_id = $1 LIMIT 1",
                customer_id
            )
            
            if result:
                await webhook_dispatcher.notify_payment_failed(
                    account_id=result['user_id'],
                    amount=0,
                    currency="brl",
                    error_message=error.get('message', 'Pagamento falhou')
                )
        
    except Exception as e:
        logger.error(f"Erro ao processar payment_intent.payment_failed: {str(e)}", exc_info=True)


async def handle_payment_intent_requires_action(payment_intent: dict):
    """Processa payment intent que requer ação do usuário"""
    try:
        payment_intent_id = payment_intent.get('id')
        customer_id = payment_intent.get('customer')
        
        logger.info(
            f"Payment Intent requer ação: {payment_intent_id}",
            extra={"customer_id": customer_id}
        )
        # Usuário precisa completar autenticação 3D Secure ou similar
        
    except Exception as e:
        logger.error(f"Erro ao processar payment_intent.requires_action: {str(e)}", exc_info=True)


async def handle_invoice_payment_action_required(invoice: dict):
    """Processa invoice que requer ação do usuário"""
    try:
        invoice_id = invoice.get('id')
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        
        logger.warning(
            f"Invoice requer ação do usuário: {invoice_id}",
            extra={
                "customer_id": customer_id,
                "subscription_id": subscription_id
            }
        )
        # Usuário precisa autenticar pagamento (3D Secure)
        
    except Exception as e:
        logger.error(f"Erro ao processar invoice.payment_action_required: {str(e)}", exc_info=True)


async def handle_customer_created(customer: dict):
    """Processa criação de customer"""
    try:
        customer_id = customer.get('id')
        email = customer.get('email')
        
        logger.info(f"Customer criado: {customer_id} - {email}")
        # Customer criado no Stripe (pode ser útil para sincronização)
        
    except Exception as e:
        logger.error(f"Erro ao processar customer.created: {str(e)}", exc_info=True)


async def handle_customer_updated(customer: dict):
    """Processa atualização de customer"""
    try:
        customer_id = customer.get('id')
        email = customer.get('email')
        
        logger.info(f"Customer atualizado: {customer_id} - {email}")
        # Atualizar dados do customer se necessário
        
    except Exception as e:
        logger.error(f"Erro ao processar customer.updated: {str(e)}", exc_info=True)


async def handle_customer_deleted(customer: dict):
    """Processa exclusão de customer"""
    try:
        customer_id = customer.get('id')
        
        logger.info(f"Customer deletado: {customer_id}")
        # Customer foi deletado no Stripe
        
    except Exception as e:
        logger.error(f"Erro ao processar customer.deleted: {str(e)}", exc_info=True)


async def handle_charge_succeeded(charge: dict):
    """Processa charge bem-sucedido"""
    try:
        charge_id = charge.get('id')
        customer_id = charge.get('customer')
        amount = charge.get('amount')
        currency = charge.get('currency')
        
        logger.info(
            f"Charge bem-sucedido: {charge_id}",
            extra={
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency
            }
        )
        
    except Exception as e:
        logger.error(f"Erro ao processar charge.succeeded: {str(e)}", exc_info=True)


async def handle_charge_failed(charge: dict):
    """Processa charge falhado"""
    try:
        charge_id = charge.get('id')
        customer_id = charge.get('customer')
        failure_code = charge.get('failure_code')
        failure_message = charge.get('failure_message')
        
        logger.warning(
            f"Charge falhou: {charge_id}",
            extra={
                "customer_id": customer_id,
                "failure_code": failure_code,
                "failure_message": failure_message
            }
        )
        
    except Exception as e:
        logger.error(f"Erro ao processar charge.failed: {str(e)}", exc_info=True)


async def handle_charge_refunded(charge: dict):
    """Processa charge reembolsado"""
    try:
        charge_id = charge.get('id')
        customer_id = charge.get('customer')
        amount_refunded = charge.get('amount_refunded')
        
        logger.info(
            f"Charge reembolsado: {charge_id}",
            extra={
                "customer_id": customer_id,
                "amount_refunded": amount_refunded
            }
        )
        
    except Exception as e:
        logger.error(f"Erro ao processar charge.refunded: {str(e)}", exc_info=True)


async def handle_account_updated(account: dict):
    """Processa atualização de conta Stripe Connect"""
    try:
        stripe_account_id = account.get('id')
        charges_enabled = account.get('charges_enabled', False)
        payouts_enabled = account.get('payouts_enabled', False)
        details_submitted = account.get('details_submitted', False)
        
        logger.info(
            f"Conta Stripe Connect atualizada: {stripe_account_id}",
            extra={
                "charges_enabled": charges_enabled,
                "payouts_enabled": payouts_enabled,
                "details_submitted": details_submitted
            }
        )
        
        # Atualizar status da conta conectada no banco
        db = await get_db_connection()
        
        # Determinar status de onboarding
        onboarding_status = 'pending'
        if charges_enabled and payouts_enabled:
            onboarding_status = 'complete'
        elif details_submitted:
            onboarding_status = 'in_progress'
        
        # Atualizar tabela connected_accounts
        update_query = """
            UPDATE connected_accounts
            SET charges_enabled = $1,
                payouts_enabled = $2,
                onboarding_status = $3,
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_account_id = $4
        """
        await db.execute(
            update_query,
            charges_enabled,
            payouts_enabled,
            onboarding_status,
            stripe_account_id
        )
        
        logger.info(f"Status da conta conectada atualizado: {stripe_account_id} -> {onboarding_status}")
        
    except Exception as e:
        logger.error(f"Erro ao processar account.updated: {str(e)}", exc_info=True)


async def handle_account_deauthorized(account: dict):
    """Processa desautorização de conta Stripe Connect"""
    try:
        stripe_account_id = account.get('id')
        
        logger.warning(f"Conta Stripe Connect desautorizada: {stripe_account_id}")
        
        # Atualizar status no banco - desativar conta
        db = await get_db_connection()
        
        update_query = """
            UPDATE connected_accounts
            SET charges_enabled = FALSE,
                payouts_enabled = FALSE,
                onboarding_status = 'deauthorized',
                updated_at = CURRENT_TIMESTAMP
            WHERE stripe_account_id = $1
        """
        await db.execute(update_query, stripe_account_id)
        
        logger.warning(f"Conta conectada desativada: {stripe_account_id}")
        
    except Exception as e:
        logger.error(f"Erro ao processar account.application.deauthorized: {str(e)}", exc_info=True)
