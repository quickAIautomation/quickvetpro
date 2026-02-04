"""
Serviço de integração com Stripe
Gerencia planos e pagamentos
"""
import logging
import os
import stripe
from app.config import settings

logger = logging.getLogger(__name__)

# Configurar Stripe
stripe.api_key = settings.stripe_secret_key


class StripeService:
    """
    Serviço para integração com Stripe
    Gerencia assinaturas e pagamentos
    """
    
    def __init__(self):
        self.stripe = stripe
    
    async def check_subscription_status(self, subscription_id: str) -> str:
        """
        Verifica status da assinatura no Stripe
        
        Args:
            subscription_id: ID da assinatura no Stripe
            
        Returns:
            Status da assinatura (active, canceled, past_due, etc.)
        """
        try:
            subscription = self.stripe.Subscription.retrieve(subscription_id)
            return subscription.status
        except Exception as e:
            logger.error(f"Erro ao verificar assinatura Stripe: {str(e)}", exc_info=True)
            return "unknown"
    
    async def create_customer(self, user_id: str, email: str) -> str:
        """
        Cria cliente no Stripe
        
        Args:
            user_id: ID do usuário no sistema
            email: Email do usuário
            
        Returns:
            Customer ID do Stripe
        """
        try:
            customer = self.stripe.Customer.create(
                email=email,
                metadata={"user_id": user_id}
            )
            return customer.id
        except Exception as e:
            logger.error(f"Erro ao criar cliente Stripe: {str(e)}", exc_info=True)
            raise
    
    async def create_subscription(
        self,
        customer_id: str,
        price_id: str
    ) -> dict:
        """
        Cria assinatura no Stripe
        
        Args:
            customer_id: ID do cliente no Stripe
            price_id: ID do preço/plano no Stripe
            
        Returns:
            Informações da assinatura
        """
        try:
            subscription = self.stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"]
            )
            return {
                "subscription_id": subscription.id,
                "client_secret": subscription.latest_invoice.payment_intent.client_secret,
                "status": subscription.status
            }
        except Exception as e:
            logger.error(f"Erro ao criar assinatura Stripe: {str(e)}", exc_info=True)
            raise
    
    async def cancel_subscription(self, subscription_id: str) -> bool:
        """
        Cancela assinatura no Stripe
        
        Args:
            subscription_id: ID da assinatura
            
        Returns:
            True se cancelado com sucesso
        """
        try:
            subscription = self.stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            return True
        except Exception as e:
            logger.error(f"Erro ao cancelar assinatura Stripe: {str(e)}", exc_info=True)
            return False
    
    def create_checkout_session(
        self,
        lookup_key: str = None,
        price_id: str = None,
        success_url: str = None,
        cancel_url: str = None,
        customer_email: str = None,
        metadata: dict = None,
        stripe_account: str = None,
        application_fee_amount: int = None,
        mode: str = "subscription",
        line_items: list = None
    ) -> stripe.checkout.Session:
        """
        Cria sessão de checkout do Stripe
        
        Args:
            lookup_key: Chave de lookup do preço (opcional se price_id fornecido)
            price_id: ID do preço diretamente (opcional se lookup_key fornecido)
            success_url: URL de redirecionamento em caso de sucesso
            cancel_url: URL de redirecionamento em caso de cancelamento
            customer_email: Email do cliente (opcional)
            metadata: Metadados adicionais (opcional)
            stripe_account: ID da conta Stripe Connect (para marketplace)
            application_fee_amount: Taxa da aplicação em centavos (para marketplace)
            mode: 'subscription' ou 'payment'
            line_items: Lista de itens customizada (opcional)
            
        Returns:
            Sessão de checkout do Stripe
        """
        try:
            checkout_session_params = {
                'mode': mode,
                'success_url': success_url or f"{settings.frontend_domain}/checkout?success=true&session_id={{CHECKOUT_SESSION_ID}}",
                'cancel_url': cancel_url or f"{settings.frontend_domain}/checkout?canceled=true",
                'payment_method_types': ['card'],
            }
            
            # Se line_items fornecido, usar diretamente
            if line_items:
                checkout_session_params['line_items'] = line_items
            else:
                # Buscar preço
                if price_id:
                    price = price_id
                elif lookup_key:
                    prices = self.stripe.Price.list(
                        lookup_keys=[lookup_key],
                        expand=['data.product']
                    )
                    
                    if not prices.data:
                        raise ValueError(f"Preço não encontrado para lookup_key: {lookup_key}")
                    
                    price = prices.data[0].id
                else:
                    raise ValueError("É necessário fornecer lookup_key, price_id ou line_items")
                
                checkout_session_params['line_items'] = [
                    {
                        'price': price,
                        'quantity': 1,
                    },
                ]
            
            # Stripe Connect (marketplace)
            if stripe_account:
                checkout_session_params['stripe_account'] = stripe_account
            
            if application_fee_amount:
                checkout_session_params['payment_intent_data'] = {
                    'application_fee_amount': application_fee_amount
                }
            
            if customer_email:
                checkout_session_params['customer_email'] = customer_email
            
            if metadata:
                checkout_session_params['metadata'] = metadata
            
            checkout_session = self.stripe.checkout.Session.create(**checkout_session_params)
            
            logger.info(f"Checkout session criada: {checkout_session.id}")
            return checkout_session
            
        except Exception as e:
            logger.error(f"Erro ao criar checkout session: {str(e)}", exc_info=True)
            raise
    
    def create_portal_session(
        self,
        customer_id: str,
        return_url: str
    ) -> stripe.billing_portal.Session:
        """
        Cria sessão do customer portal do Stripe
        
        Args:
            customer_id: ID do cliente no Stripe
            return_url: URL de retorno após gerenciar assinatura
            
        Returns:
            Sessão do portal do Stripe
        """
        try:
            portal_session = self.stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            
            logger.info(f"Portal session criada para cliente: {customer_id}")
            return portal_session
            
        except Exception as e:
            logger.error(f"Erro ao criar portal session: {str(e)}", exc_info=True)
            raise
    
    def get_checkout_session(self, session_id: str) -> stripe.checkout.Session:
        """
        Recupera sessão de checkout
        
        Args:
            session_id: ID da sessão de checkout
            
        Returns:
            Sessão de checkout
        """
        try:
            return self.stripe.checkout.Session.retrieve(session_id)
        except Exception as e:
            logger.error(f"Erro ao recuperar checkout session: {str(e)}", exc_info=True)
            raise
    
    def construct_webhook_event(
        self,
        payload: bytes,
        sig_header: str,
        webhook_secret: str
    ) -> stripe.Event:
        """
        Constrói e valida evento do webhook do Stripe
        
        Args:
            payload: Payload do webhook
            sig_header: Header de assinatura
            webhook_secret: Secret do webhook
            
        Returns:
            Evento do Stripe
        """
        try:
            return self.stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=webhook_secret
            )
        except ValueError as e:
            logger.error(f"Payload inválido: {str(e)}")
            raise
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Assinatura inválida: {str(e)}")
            raise
    
    def list_products(self, active_only: bool = True) -> list:
        """
        Lista produtos do Stripe com seus preços
        
        Args:
            active_only: Se True, retorna apenas produtos ativos
            
        Returns:
            Lista de produtos com preços
        """
        try:
            products = self.stripe.Product.list(active=active_only, expand=['data.default_price'])
            result = []
            
            for product in products.data:
                # Buscar todos os preços do produto
                prices = self.stripe.Price.list(product=product.id, active=True)
                
                product_data = {
                    'id': product.id,
                    'name': product.name,
                    'description': product.description,
                    'active': product.active,
                    'metadata': product.metadata,
                    'prices': []
                }
                
                for price in prices.data:
                    price_data = {
                        'id': price.id,
                        'lookup_key': price.lookup_key,
                        'unit_amount': price.unit_amount,
                        'currency': price.currency,
                        'recurring': {
                            'interval': price.recurring.interval if price.recurring else None,
                            'interval_count': price.recurring.interval_count if price.recurring else None
                        } if price.recurring else None,
                        'active': price.active
                    }
                    product_data['prices'].append(price_data)
                
                result.append(product_data)
            
            logger.info(f"Listados {len(result)} produtos do Stripe")
            return result
            
        except Exception as e:
            logger.error(f"Erro ao listar produtos do Stripe: {str(e)}", exc_info=True)
            raise
    
    def list_prices(self, lookup_key: str = None) -> list:
        """
        Lista preços do Stripe
        
        Args:
            lookup_key: Filtrar por lookup_key (opcional)
            
        Returns:
            Lista de preços
        """
        try:
            params = {'active': True, 'expand': ['data.product']}
            if lookup_key:
                params['lookup_keys'] = [lookup_key]
            
            prices = self.stripe.Price.list(**params)
            result = []
            
            for price in prices.data:
                price_data = {
                    'id': price.id,
                    'lookup_key': price.lookup_key,
                    'product_id': price.product.id if hasattr(price.product, 'id') else price.product,
                    'product_name': price.product.name if hasattr(price.product, 'name') else None,
                    'unit_amount': price.unit_amount,
                    'currency': price.currency,
                    'recurring': {
                        'interval': price.recurring.interval,
                        'interval_count': price.recurring.interval_count
                    } if price.recurring else None,
                    'active': price.active
                }
                result.append(price_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Erro ao listar preços do Stripe: {str(e)}", exc_info=True)
            raise
    
    # ==================== STRIPE CONNECT METHODS ====================
    
    def create_connect_account(
        self,
        email: str,
        country: str = "BR",
        type: str = "express",
        capabilities: dict = None,
        metadata: dict = None
    ) -> stripe.Account:
        """
        Cria uma conta Stripe Connect
        
        Args:
            email: Email da conta conectada
            country: Código do país (padrão: BR)
            type: Tipo de conta ('express', 'standard', 'custom')
            capabilities: Capacidades da conta (ex: {'card_payments': {'requested': True}})
            metadata: Metadados adicionais
            
        Returns:
            Conta Stripe Connect criada
        """
        try:
            account_params = {
                'type': type,
                'country': country,
                'email': email,
            }
            
            if capabilities:
                account_params['capabilities'] = capabilities
            
            if metadata:
                account_params['metadata'] = metadata
            
            account = self.stripe.Account.create(**account_params)
            
            logger.info(f"Conta Stripe Connect criada: {account.id} para {email}")
            return account
            
        except Exception as e:
            logger.error(f"Erro ao criar conta Stripe Connect: {str(e)}", exc_info=True)
            raise
    
    def create_account_link(
        self,
        account_id: str,
        refresh_url: str,
        return_url: str,
        type: str = "account_onboarding"
    ) -> stripe.AccountLink:
        """
        Cria Account Link para onboarding de conta conectada
        
        Args:
            account_id: ID da conta Stripe Connect
            refresh_url: URL para redirecionar se o link expirar
            return_url: URL para redirecionar após onboarding
            type: Tipo de link ('account_onboarding' ou 'account_update')
            
        Returns:
            Account Link criado
        """
        try:
            account_link = self.stripe.AccountLink.create(
                account=account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type=type
            )
            
            logger.info(f"Account Link criado para conta: {account_id}")
            return account_link
            
        except Exception as e:
            logger.error(f"Erro ao criar Account Link: {str(e)}", exc_info=True)
            raise
    
    def get_connect_account(self, account_id: str) -> stripe.Account:
        """
        Recupera informações de uma conta Stripe Connect
        
        Args:
            account_id: ID da conta Stripe Connect
            
        Returns:
            Informações da conta
        """
        try:
            account = self.stripe.Account.retrieve(account_id)
            return account
        except Exception as e:
            logger.error(f"Erro ao recuperar conta Stripe Connect: {str(e)}", exc_info=True)
            raise
    
    def list_connect_accounts(self, limit: int = 100) -> list:
        """
        Lista contas Stripe Connect
        
        Args:
            limit: Limite de resultados
            
        Returns:
            Lista de contas conectadas
        """
        try:
            accounts = self.stripe.Account.list(limit=limit)
            return [account for account in accounts.data]
        except Exception as e:
            logger.error(f"Erro ao listar contas Stripe Connect: {str(e)}", exc_info=True)
            raise
    
    def create_direct_charge(
        self,
        amount: int,
        currency: str,
        connected_account_id: str,
        customer: str = None,
        payment_method: str = None,
        application_fee_amount: int = None,
        metadata: dict = None
    ) -> stripe.Charge:
        """
        Cria uma cobrança direta na conta conectada (Direct Charge)
        
        Args:
            amount: Valor em centavos
            currency: Moeda (ex: 'brl')
            connected_account_id: ID da conta Stripe Connect
            customer: ID do customer (opcional)
            payment_method: ID do método de pagamento (opcional)
            application_fee_amount: Taxa da aplicação em centavos (opcional)
            metadata: Metadados adicionais
            
        Returns:
            Charge criado
        """
        try:
            charge_params = {
                'amount': amount,
                'currency': currency,
            }
            
            if customer:
                charge_params['customer'] = customer
            if payment_method:
                charge_params['payment_method'] = payment_method
            if application_fee_amount:
                charge_params['application_fee_amount'] = application_fee_amount
            if metadata:
                charge_params['metadata'] = metadata
            
            # Criar charge na conta conectada
            charge = self.stripe.Charge.create(
                **charge_params,
                stripe_account=connected_account_id
            )
            
            logger.info(f"Direct charge criado: {charge.id} na conta {connected_account_id}")
            return charge
            
        except Exception as e:
            logger.error(f"Erro ao criar direct charge: {str(e)}", exc_info=True)
            raise
    
    def create_destination_charge(
        self,
        amount: int,
        currency: str,
        destination: str,
        customer: str = None,
        payment_method: str = None,
        application_fee_amount: int = None,
        metadata: dict = None
    ) -> stripe.Charge:
        """
        Cria uma cobrança com transferência imediata (Destination Charge)
        
        Args:
            amount: Valor em centavos
            currency: Moeda (ex: 'brl')
            destination: ID da conta conectada de destino
            customer: ID do customer (opcional)
            payment_method: ID do método de pagamento (opcional)
            application_fee_amount: Taxa da aplicação em centavos (opcional)
            metadata: Metadados adicionais
            
        Returns:
            Charge criado
        """
        try:
            charge_params = {
                'amount': amount,
                'currency': currency,
                'destination': {
                    'account': destination
                }
            }
            
            if customer:
                charge_params['customer'] = customer
            if payment_method:
                charge_params['payment_method'] = payment_method
            if application_fee_amount:
                charge_params['application_fee_amount'] = application_fee_amount
            if metadata:
                charge_params['metadata'] = metadata
            
            charge = self.stripe.Charge.create(**charge_params)
            
            logger.info(f"Destination charge criado: {charge.id} para conta {destination}")
            return charge
            
        except Exception as e:
            logger.error(f"Erro ao criar destination charge: {str(e)}", exc_info=True)
            raise
    
    def create_transfer(
        self,
        amount: int,
        currency: str,
        destination: str,
        metadata: dict = None
    ) -> stripe.Transfer:
        """
        Cria uma transferência para conta conectada (Separate Transfer)
        
        Args:
            amount: Valor em centavos
            currency: Moeda (ex: 'brl')
            destination: ID da conta conectada de destino
            metadata: Metadados adicionais
            
        Returns:
            Transfer criado
        """
        try:
            transfer_params = {
                'amount': amount,
                'currency': currency,
                'destination': destination
            }
            
            if metadata:
                transfer_params['metadata'] = metadata
            
            transfer = self.stripe.Transfer.create(**transfer_params)
            
            logger.info(f"Transfer criado: {transfer.id} para conta {destination}")
            return transfer
            
        except Exception as e:
            logger.error(f"Erro ao criar transfer: {str(e)}", exc_info=True)
            raise
    
    def create_login_link(self, account_id: str) -> stripe.LoginLink:
        """
        Cria link de login para Express Dashboard
        
        Args:
            account_id: ID da conta Stripe Connect
            
        Returns:
            Login Link criado
        """
        try:
            login_link = self.stripe.Account.create_login_link(account_id)
            logger.info(f"Login link criado para conta: {account_id}")
            return login_link
        except Exception as e:
            logger.error(f"Erro ao criar login link: {str(e)}", exc_info=True)
            raise