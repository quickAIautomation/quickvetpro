"""
Configuração do banco de dados PostgreSQL
"""
import logging
import asyncpg
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Pool de conexões
_db_pool: Optional[asyncpg.Pool] = None


async def init_db():
    """
    Inicializa pool de conexões do PostgreSQL
    """
    global _db_pool
    
    try:
        database_url = settings.database_url
        
        _db_pool = await asyncpg.create_pool(
            database_url,
            min_size=5,
            max_size=20,
            command_timeout=60
        )
        
        logger.info(f"Pool de conexões PostgreSQL inicializado: {database_url[:50]}...")
        
        # Criar tabelas se não existirem
        await create_tables()
        
    except Exception as e:
        logger.error(f"Erro ao inicializar banco de dados: {str(e)}", exc_info=True)
        raise


async def close_db():
    """
    Fecha pool de conexões
    """
    global _db_pool
    
    if _db_pool:
        await _db_pool.close()
        logger.info("Pool de conexões PostgreSQL fechado")


async def get_db_connection():
    """
    Obtém conexão do pool
    
    Returns:
        Conexão do banco de dados
    """
    if _db_pool is None:
        await init_db()
    
    return _db_pool


async def create_tables():
    """
    Cria tabelas necessárias no banco de dados
    """
    try:
        conn = await get_db_connection()
        
        # Habilitar extensão pgvector para embeddings (opcional)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            logger.info("Extensão pgvector habilitada")
        except Exception as e:
            logger.warning(f"Extensão pgvector não disponível (opcional): {str(e)[:100]}")
            logger.info("Continuando sem pgvector - funcionalidades de RAG vetorial estarão desabilitadas")
        
        # Tabela de usuários
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(255) PRIMARY KEY,
                phone_number VARCHAR(20) UNIQUE NOT NULL,
                email VARCHAR(255),
                name VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de planos
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                plan_id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(user_id),
                plan_type VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'inactive',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Adicionar constraint única para user_id se não existir
        await conn.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'plans_user_id_unique'
                ) THEN
                    ALTER TABLE plans ADD CONSTRAINT plans_user_id_unique UNIQUE (user_id);
                END IF;
            END $$;
        """)
        
        # Tabela de assinaturas Stripe
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                subscription_id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(user_id),
                stripe_customer_id VARCHAR(255),
                stripe_subscription_id VARCHAR(255) UNIQUE,
                status VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Tabela de consentimentos (LGPD)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_consents (
                consent_id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(user_id),
                consent_given BOOLEAN NOT NULL,
                consent_date TIMESTAMP NOT NULL,
                revoked_at TIMESTAMP,
                ip_address VARCHAR(45),
                CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Tabela de logs de mensagens (auditoria)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_logs (
                log_id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(user_id),
                incoming_message TEXT,
                outgoing_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Tabela de contas (Clínicas/Consultórios) - Platform SaaS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                clinic_name VARCHAR(255),
                stripe_customer_id VARCHAR(255),
                stripe_subscription_id VARCHAR(255),
                plan_type VARCHAR(50) DEFAULT 'free',
                plan_status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de contas Stripe Connect
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS connected_accounts (
                account_id VARCHAR(255) PRIMARY KEY REFERENCES accounts(account_id),
                stripe_account_id VARCHAR(255) UNIQUE NOT NULL,
                charges_enabled BOOLEAN DEFAULT FALSE,
                payouts_enabled BOOLEAN DEFAULT FALSE,
                onboarding_status VARCHAR(50) DEFAULT 'pending',
                risk_responsibility VARCHAR(50) DEFAULT 'stripe',
                account_type VARCHAR(50) DEFAULT 'express',
                country VARCHAR(2) DEFAULT 'BR',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de logs de auditoria (Observabilidade e Idempotência)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id VARCHAR(255) PRIMARY KEY,
                event_type VARCHAR(100) NOT NULL,
                account_id VARCHAR(255),
                email VARCHAR(255),
                details JSONB,
                idempotency_key VARCHAR(255) UNIQUE,
                correlation_id VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de produtos/serviços das clínicas
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id VARCHAR(255) PRIMARY KEY,
                account_id VARCHAR(255) REFERENCES accounts(account_id),
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price_cents INTEGER NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de chunks de conhecimento (RAG) - com suporte opcional para vector
        try:
            # Tentar criar com vector se a extensão estiver disponível
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding vector(1536),
                    file_name VARCHAR(255),
                    file_hash VARCHAR(64),
                    chunk_index INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception:
            # Criar sem vector se a extensão não estiver disponível
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding BYTEA,
                    file_name VARCHAR(255),
                    file_hash VARCHAR(64),
                    chunk_index INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.warning("Tabela knowledge_chunks criada sem suporte a vector (pgvector não disponível)")
        
        # Índices para performance
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_plans_user_id ON plans(user_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_consents_user_id ON user_consents(user_id);
            CREATE INDEX IF NOT EXISTS idx_message_logs_user_id ON message_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_message_logs_created_at ON message_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
            CREATE INDEX IF NOT EXISTS idx_accounts_stripe_customer ON accounts(stripe_customer_id);
            CREATE INDEX IF NOT EXISTS idx_products_account_id ON products(account_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs(event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_account_id ON audit_logs(account_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_idempotency ON audit_logs(idempotency_key);
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_phone ON conversations(phone_number);
            CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
            CREATE INDEX IF NOT EXISTS idx_conversations_last_message ON conversations(last_message_at DESC);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv ON conversation_messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_user ON conversation_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_created ON conversation_messages(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_admins_email ON admins(email);
        """)
        
        # Índice vetorial HNSW otimizado para busca por similaridade (opcional)
        # HNSW (Hierarchical Navigable Small World) - busca ANN 10-100x mais rápida
        # m = 16: número de conexões por nó (padrão 16, maior = mais preciso mas mais memória)
        # ef_construction = 64: qualidade do índice na construção (padrão 64)
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_embedding 
                ON knowledge_chunks 
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """)
        except Exception as e:
            logger.warning(f"Índice vetorial não criado (pgvector não disponível): {str(e)[:100]}")
        
        # Configurar ef_search para queries (quanto maior, mais preciso mas mais lento)
        # Recomendado: 40-100 para produção
        await conn.execute("SET hnsw.ef_search = 60")
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_file_hash ON knowledge_chunks(file_hash);
        """)
        
        # ==================== TABELAS PARA NAVEGAÇÃO ESTRUTURAL ====================
        # Sistema alternativo ao RAG vetorial, baseado em hierarquia de documentos
        
        # Tabela de documentos estruturados
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS structural_documents (
                document_id SERIAL PRIMARY KEY,
                file_name VARCHAR(255) NOT NULL,
                file_hash VARCHAR(64) UNIQUE NOT NULL,
                title TEXT,
                total_pages INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{}'
            )
        """)
        
        # Tabela de nós hierárquicos (árvore)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS structural_nodes (
                node_id SERIAL PRIMARY KEY,
                document_id INTEGER REFERENCES structural_documents(document_id) ON DELETE CASCADE,
                parent_id INTEGER REFERENCES structural_nodes(node_id) ON DELETE CASCADE,
                node_type VARCHAR(50) NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                page_start INTEGER,
                page_end INTEGER,
                level INTEGER DEFAULT 0,
                order_index INTEGER DEFAULT 0,
                references TEXT[],
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de sumário (TOC) - cache para navegação rápida
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS structural_toc (
                toc_id SERIAL PRIMARY KEY,
                document_id INTEGER REFERENCES structural_documents(document_id) ON DELETE CASCADE UNIQUE,
                toc_text TEXT NOT NULL,
                toc_json JSONB NOT NULL
            )
        """)
        
        # Índices para navegação estrutural
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_document ON structural_nodes(document_id);
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_parent ON structural_nodes(parent_id);
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_type ON structural_nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_level ON structural_nodes(level);
            CREATE INDEX IF NOT EXISTS idx_structural_docs_hash ON structural_documents(file_hash);
        """)
        
        # ==================== TABELAS PARA AUTENTICAÇÃO API ====================
        
        # Tabela de API Keys
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id VARCHAR(50) PRIMARY KEY,
                account_id VARCHAR(255) REFERENCES accounts(account_id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                secret_hash VARCHAR(64) NOT NULL,
                permissions TEXT[] DEFAULT '{}',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        
        # Índices para API Keys
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_account ON api_keys(account_id);
            CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active);
        """)
        
        # ==================== TABELAS PARA ALERTAS ====================
        
        # Tabela de alertas
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id SERIAL PRIMARY KEY,
                alert_type VARCHAR(50) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                title VARCHAR(255) NOT NULL,
                message TEXT,
                metadata JSONB DEFAULT '{}',
                is_acknowledged BOOLEAN DEFAULT FALSE,
                acknowledged_by VARCHAR(255),
                acknowledged_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Índices para alertas
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(is_acknowledged);
            CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
        """)
        
        # ==================== TABELAS PARA DASHBOARD ADMIN ====================
        
        # Tabela de conversas para dashboard admin
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(user_id),
                phone_number VARCHAR(20) NOT NULL,
                status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'pending', 'resolved')),
                message_status VARCHAR(20) DEFAULT 'pending' CHECK (message_status IN ('pending', 'sent', 'delivered', 'read', 'failed')),
                last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_message_from VARCHAR(10) CHECK (last_message_from IN ('user', 'assistant')),
                last_message_preview TEXT,
                total_messages INTEGER DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                metadata JSONB DEFAULT '{}',
                CONSTRAINT fk_user_conv FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Tabela de mensagens individuais para histórico detalhado
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_messages (
                message_id SERIAL PRIMARY KEY,
                conversation_id INTEGER REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                user_id VARCHAR(255) REFERENCES users(user_id),
                role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                has_media BOOLEAN DEFAULT FALSE,
                media_type VARCHAR(20),
                whatsapp_message_id VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_conv FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id),
                CONSTRAINT fk_user_msg FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Tabela de administradores
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Índices para dashboard admin
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_phone ON conversations(phone_number);
            CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
            CREATE INDEX IF NOT EXISTS idx_conversations_last_message ON conversations(last_message_at DESC);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv ON conversation_messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_user ON conversation_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_created ON conversation_messages(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_admins_email ON admins(email);
        """)
        
        logger.info("Tabelas do banco de dados criadas/verificadas (incluindo estrutura hierárquica e dashboard admin)")
        
    except Exception as e:
        logger.error(f"Erro ao criar tabelas: {str(e)}", exc_info=True)
        raise
