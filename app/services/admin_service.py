"""
Serviço de Administração
========================

Gerencia autenticação e operações do painel admin.
"""
import os
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from passlib.context import CryptContext
from jose import jwt

from app.infra.db import get_db_connection

logger = logging.getLogger(__name__)

# Configurações
ADMIN_EMAIL = "quickai.automation@gmail.com"  # Sempre lowercase
ADMIN_PASSWORD = "#QuickAI2504."
JWT_SECRET = os.getenv("JWT_SECRET", "admin_secret_key_change_in_production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8

# Configurar bcrypt com fallback para pbkdf2 se houver problemas
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    # Testar se bcrypt funciona
    test_hash = pwd_context.hash("test")
except Exception as e:
    logger.warning(f"Bcrypt não disponível, usando pbkdf2: {e}")
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class AdminService:
    """Serviço para operações administrativas"""
    
    async def initialize_admin(self):
        """Inicializa o admin padrão se não existir"""
        try:
            db = await get_db_connection()
            
            # Verificar se já existe
            existing = await db.fetchrow(
                "SELECT admin_id FROM admins WHERE email = $1",
                ADMIN_EMAIL
            )
            
            if existing:
                logger.info("Admin já existe")
                return
            
            # Criar hash da senha (garantir que a senha não exceda 72 bytes para bcrypt)
            password_to_hash = ADMIN_PASSWORD.encode('utf-8')[:72].decode('utf-8')
            password_hash = pwd_context.hash(password_to_hash)
            
            # Inserir admin
            await db.execute("""
                INSERT INTO admins (email, password_hash, is_active)
                VALUES ($1, $2, TRUE)
                ON CONFLICT (email) DO NOTHING
            """, ADMIN_EMAIL, password_hash)
            
            logger.info("Admin inicializado com sucesso")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar admin: {e}", exc_info=True)
    
    async def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Autentica um admin
        
        Returns:
            Dict com token e dados do admin ou None
        """
        try:
            db = await get_db_connection()
            
            # Buscar admin
            admin = await db.fetchrow(
                "SELECT * FROM admins WHERE email = $1 AND is_active = TRUE",
                email.lower().strip()
            )
            
            if not admin:
                logger.warning(f"Tentativa de login com email inválido: {email}")
                return None
            
            # Verificar senha
            if not pwd_context.verify(password, admin["password_hash"]):
                logger.warning(f"Senha incorreta para: {email}")
                return None
            
            # Atualizar último login
            await db.execute("""
                UPDATE admins SET last_login_at = $1 WHERE admin_id = $2
            """, datetime.utcnow(), admin["admin_id"])
            
            # Gerar token JWT
            token = self._generate_token(admin["admin_id"], admin["email"])
            
            return {
                "token": token,
                "admin": {
                    "id": admin["admin_id"],
                    "email": admin["email"]
                }
            }
            
        except Exception as e:
            logger.error(f"Erro na autenticação: {e}", exc_info=True)
            return None
    
    def _generate_token(self, admin_id: int, email: str) -> str:
        """Gera token JWT para o admin"""
        expiration = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
        
        payload = {
            "sub": str(admin_id),
            "email": email,
            "type": "admin",
            "permissions": ["admin"],  # Adicionar permissão admin
            "exp": expiration,
            "iat": datetime.utcnow()
        }
        
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verifica e decodifica token JWT"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            
            if payload.get("type") != "admin":
                return None
            
            return payload
            
        except Exception as e:
            logger.debug(f"Token inválido: {e}")
            return None
    
    async def get_conversations(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lista conversas para o dashboard"""
        try:
            db = await get_db_connection()
            
            query = """
                SELECT 
                    c.conversation_id,
                    c.user_id,
                    c.phone_number,
                    c.status,
                    c.message_status,
                    c.last_message_at,
                    c.last_message_from,
                    c.last_message_preview,
                    c.total_messages,
                    c.started_at,
                    c.resolved_at,
                    u.name as user_name,
                    u.email as user_email
                FROM conversations c
                LEFT JOIN users u ON c.user_id = u.user_id
            """
            
            params = []
            conditions = []
            
            if status:
                conditions.append(f"c.status = ${len(params) + 1}")
                params.append(status)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY c.last_message_at DESC LIMIT $%d OFFSET $%d" % (len(params) + 1, len(params) + 2)
            params.extend([limit, offset])
            
            rows = await db.fetch(query, *params)
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Erro ao buscar conversas: {e}", exc_info=True)
            return []
    
    async def get_conversation_messages(
        self,
        conversation_id: int,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Busca mensagens de uma conversa"""
        try:
            db = await get_db_connection()
            
            rows = await db.fetch("""
                SELECT 
                    message_id,
                    role,
                    content,
                    has_media,
                    media_type,
                    whatsapp_message_id,
                    created_at
                FROM conversation_messages
                WHERE conversation_id = $1
                ORDER BY created_at ASC
                LIMIT $2
            """, conversation_id, limit)
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Erro ao buscar mensagens: {e}", exc_info=True)
            return []
    
    async def update_conversation_status(
        self,
        conversation_id: int,
        status: str
    ) -> bool:
        """Atualiza status de uma conversa"""
        try:
            db = await get_db_connection()
            
            resolved_at = datetime.utcnow() if status == "resolved" else None
            
            await db.execute("""
                UPDATE conversations
                SET status = $1, resolved_at = $2
                WHERE conversation_id = $3
            """, status, resolved_at, conversation_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao atualizar status: {e}", exc_info=True)
            return False
    
    async def get_dashboard_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do dashboard"""
        try:
            db = await get_db_connection()
            
            # Total de conversas
            total = await db.fetchval("SELECT COUNT(*) FROM conversations")
            
            # Conversas ativas
            active = await db.fetchval(
                "SELECT COUNT(*) FROM conversations WHERE status = 'active'"
            )
            
            # Conversas pendentes
            pending = await db.fetchval(
                "SELECT COUNT(*) FROM conversations WHERE status = 'pending'"
            )
            
            # Conversas resolvidas hoje
            resolved_today = await db.fetchval("""
                SELECT COUNT(*) FROM conversations
                WHERE status = 'resolved' 
                AND DATE(resolved_at) = CURRENT_DATE
            """)
            
            # Total de mensagens hoje
            messages_today = await db.fetchval("""
                SELECT COUNT(*) FROM conversation_messages
                WHERE DATE(created_at) = CURRENT_DATE
            """)
            
            # Total de usuários
            total_users = await db.fetchval("SELECT COUNT(*) FROM users")
            
            return {
                "total_conversations": total or 0,
                "active_conversations": active or 0,
                "pending_conversations": pending or 0,
                "resolved_today": resolved_today or 0,
                "messages_today": messages_today or 0,
                "total_users": total_users or 0
            }
            
        except Exception as e:
            logger.error(f"Erro ao buscar estatísticas: {e}", exc_info=True)
            return {}
    
    async def get_users(
        self,
        limit: int = 100,
        offset: int = 0,
        plan_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lista usuários com seus planos e estatísticas de mensagens
        
        Args:
            limit: Limite de resultados
            offset: Offset para paginação
            plan_type: Filtrar por tipo de plano (opcional)
            
        Returns:
            Lista de usuários com informações de plano e mensagens
        """
        try:
            db = await get_db_connection()
            
            # Usar subqueries para evitar problemas com GROUP BY
            query = """
                SELECT 
                    u.user_id,
                    u.phone_number,
                    u.email,
                    u.name,
                    u.created_at,
                    p.plan_type,
                    p.status as plan_status,
                    p.expires_at as plan_expires_at,
                    COALESCE(
                        (SELECT COUNT(DISTINCT conversation_id) 
                         FROM conversations 
                         WHERE user_id = u.user_id OR phone_number = u.phone_number), 
                        0
                    ) as total_conversations,
                    COALESCE(msg_stats.total_messages, 0) as total_messages,
                    COALESCE(msg_stats.messages_today, 0) as messages_today,
                    msg_stats.last_message_at
                FROM users u
                LEFT JOIN plans p ON u.user_id = p.user_id
                LEFT JOIN (
                    SELECT 
                        user_id,
                        COUNT(*) as total_messages,
                        COUNT(CASE WHEN DATE(created_at) = CURRENT_DATE THEN 1 END) as messages_today,
                        MAX(created_at) as last_message_at
                    FROM conversation_messages
                    GROUP BY user_id
                ) msg_stats ON u.user_id = msg_stats.user_id
            """
            
            conditions = []
            params = []
            
            if plan_type:
                conditions.append(f"p.plan_type = ${len(params) + 1}")
                params.append(plan_type)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += """
                ORDER BY u.created_at DESC
                LIMIT $%d OFFSET $%d
            """ % (len(params) + 1, len(params) + 2)
            
            params.extend([limit, offset])
            
            rows = await db.fetch(query, *params)
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Erro ao buscar usuários: {e}", exc_info=True)
            return []
    
    async def get_user_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas gerais de usuários"""
        try:
            db = await get_db_connection()
            
            # Total de usuários
            total_users = await db.fetchval("SELECT COUNT(*) FROM users")
            
            # Usuários por plano
            users_by_plan = await db.fetch("""
                SELECT 
                    COALESCE(p.plan_type, 'sem_plano') as plan_type,
                    COUNT(DISTINCT u.user_id) as count
                FROM users u
                LEFT JOIN plans p ON u.user_id = p.user_id AND p.status = 'active'
                GROUP BY p.plan_type
            """)
            
            plan_distribution = {row['plan_type']: row['count'] for row in users_by_plan}
            
            # Total de mensagens por usuário (top 10)
            top_users_messages = await db.fetch("""
                SELECT 
                    u.user_id,
                    u.phone_number,
                    u.name,
                    COUNT(cm.message_id) as message_count
                FROM users u
                LEFT JOIN conversation_messages cm ON u.user_id = cm.user_id
                GROUP BY u.user_id, u.phone_number, u.name
                ORDER BY message_count DESC
                LIMIT 10
            """)
            
            return {
                "total_users": total_users or 0,
                "plan_distribution": plan_distribution,
                "top_users_by_messages": [dict(row) for row in top_users_messages]
            }
            
        except Exception as e:
            logger.error(f"Erro ao buscar estatísticas de usuários: {e}", exc_info=True)
            return {}


# Instância global
admin_service = AdminService()
