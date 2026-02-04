"""
Serviço de gerenciamento de planos e assinaturas
Integração com Stripe
"""
import logging
from typing import Optional
from app.infra.db import get_db_connection
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


class PlanService:
    """
    Gerencia planos e assinaturas dos usuários veterinários
    """
    
    def __init__(self):
        self.stripe_service = StripeService()
    
    async def is_plan_active(self, user_id: str) -> bool:
        """
        Verifica se o usuário tem um plano ativo
        
        Args:
            user_id: ID do usuário
            
        Returns:
            True se plano está ativo, False caso contrário
        """
        try:
            # Verificar no banco de dados
            db = await get_db_connection()
            
            query = """
                SELECT 
                    p.status,
                    p.expires_at,
                    s.stripe_subscription_id
                FROM plans p
                LEFT JOIN subscriptions s ON p.user_id = s.user_id
                WHERE p.user_id = $1
                ORDER BY p.created_at DESC
                LIMIT 1
            """
            
            result = await db.fetchrow(query, user_id)
            
            if not result:
                logger.warning(f"Usuário {user_id} não possui plano")
                return False
            
            # Verificar status no Stripe se houver subscription_id
            if result['stripe_subscription_id']:
                stripe_status = await self.stripe_service.check_subscription_status(
                    result['stripe_subscription_id']
                )
                return stripe_status == 'active'
            
            # Verificar status local
            if result['status'] == 'active':
                # Verificar se não expirou
                if result['expires_at']:
                    from datetime import datetime
                    if result['expires_at'] > datetime.now():
                        return True
                    return False
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Erro ao verificar plano: {str(e)}", exc_info=True)
            return False
    
    async def get_user_plan(self, user_id: str) -> Optional[dict]:
        """
        Retorna informações do plano do usuário
        
        Args:
            user_id: ID do usuário
            
        Returns:
            Dict com informações do plano ou None
        """
        try:
            db = await get_db_connection()
            
            query = """
                SELECT 
                    p.*,
                    s.stripe_subscription_id,
                    s.stripe_customer_id
                FROM plans p
                LEFT JOIN subscriptions s ON p.user_id = s.user_id
                WHERE p.user_id = $1
                ORDER BY p.created_at DESC
                LIMIT 1
            """
            
            result = await db.fetchrow(query, user_id)
            
            if result:
                return dict(result)
            return None
            
        except Exception as e:
            logger.error(f"Erro ao obter plano: {str(e)}", exc_info=True)
            return None
