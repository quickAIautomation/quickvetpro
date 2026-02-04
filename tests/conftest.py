"""
Configuração do pytest e fixtures compartilhadas.
"""
import os
import sys
import asyncio
from typing import Generator, AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Adicionar diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar variáveis de ambiente para testes
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/quickvet_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["OPENAI_API_KEY"] = "sk-test-key"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_key"
os.environ["WHATSAPP_API_TOKEN"] = "test_token"
os.environ["JWT_SECRET"] = "test_jwt_secret_for_testing_only"
os.environ["CACHE_WARMUP_ENABLED"] = "false"  # Desabilitar warmup em testes


# Event loop para testes async
@pytest.fixture(scope="session")
def event_loop():
    """Cria event loop para a sessão de testes"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Mock do Redis
@pytest.fixture
def mock_redis():
    """Mock do cliente Redis"""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    mock.exists = AsyncMock(return_value=False)
    mock.hincrby = AsyncMock(return_value=1)
    mock.hgetall = AsyncMock(return_value={})
    mock.zadd = AsyncMock(return_value=1)
    mock.zcard = AsyncMock(return_value=0)
    mock.zremrangebyscore = AsyncMock(return_value=0)
    mock.pipeline = MagicMock(return_value=mock)
    mock.execute = AsyncMock(return_value=[0, 0, True, True])
    return mock


# Mock do banco de dados
@pytest.fixture
def mock_db():
    """Mock do pool de conexões PostgreSQL"""
    mock = AsyncMock()
    mock.fetch = AsyncMock(return_value=[])
    mock.fetchrow = AsyncMock(return_value=None)
    mock.fetchval = AsyncMock(return_value=0)
    mock.execute = AsyncMock(return_value="INSERT 0 1")
    return mock


# Mock do OpenAI
@pytest.fixture
def mock_openai():
    """Mock do cliente OpenAI"""
    mock = MagicMock()
    
    # Mock para embeddings
    mock_embedding_response = MagicMock()
    mock_embedding_response.data = [MagicMock(embedding=[0.1] * 1536)]
    mock.embeddings.create = MagicMock(return_value=mock_embedding_response)
    
    # Mock para chat completions
    mock_chat_response = MagicMock()
    mock_chat_response.choices = [
        MagicMock(message=MagicMock(content="Resposta do agente veterinário"))
    ]
    mock.chat.completions.create = MagicMock(return_value=mock_chat_response)
    
    # Mock para transcrição de áudio
    mock_transcription_response = MagicMock()
    mock_transcription_response.text = "Transcrição do áudio"
    mock.audio.transcriptions.create = MagicMock(return_value=mock_transcription_response)
    
    return mock


# Cliente de teste da API
@pytest.fixture
def client():
    """Cliente de teste FastAPI síncrono"""
    from app.main import app
    
    with TestClient(app) as c:
        yield c


# Cliente assíncrono
@pytest.fixture
async def async_client():
    """Cliente de teste FastAPI assíncrono"""
    from app.main import app
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# Fixtures de dados de teste
@pytest.fixture
def sample_user():
    """Usuário de exemplo para testes"""
    return {
        "user_id": "test_user_123",
        "phone_number": "5511999999999",
        "email": "test@example.com",
        "name": "Usuário Teste"
    }


@pytest.fixture
def sample_account():
    """Conta de exemplo para testes"""
    return {
        "account_id": "test_account_123",
        "email": "clinic@example.com",
        "clinic_name": "Clínica Veterinária Teste",
        "plan_type": "premium",
        "plan_status": "active"
    }


@pytest.fixture
def sample_whatsapp_message():
    """Mensagem WhatsApp de exemplo"""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5511999999999",
                        "phone_number_id": "123456789"
                    },
                    "contacts": [{
                        "profile": {"name": "Usuário Teste"},
                        "wa_id": "5511999999999"
                    }],
                    "messages": [{
                        "from": "5511999999999",
                        "id": "msg_123",
                        "timestamp": "1234567890",
                        "type": "text",
                        "text": {"body": "Meu cachorro está vomitando"}
                    }]
                },
                "field": "messages"
            }]
        }]
    }


@pytest.fixture
def sample_stripe_event():
    """Evento Stripe de exemplo"""
    return {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_test_123",
                "customer_email": "test@example.com",
                "subscription": "sub_test_123",
                "metadata": {
                    "account_id": "test_account_123"
                }
            }
        }
    }


@pytest.fixture
def sample_knowledge_chunks():
    """Chunks de conhecimento de exemplo"""
    return [
        {
            "content": "A cinomose é uma doença viral grave que afeta cães...",
            "file": "manual_veterinario.pdf",
            "chunk": 1,
            "similarity": 0.95
        },
        {
            "content": "Os sintomas incluem febre, secreção nasal, vômitos...",
            "file": "manual_veterinario.pdf",
            "chunk": 2,
            "similarity": 0.88
        }
    ]


# Fixtures para autenticação
@pytest.fixture
def api_key():
    """API Key válida para testes"""
    return "qv_testkey_testsecret1234567890abcdef"


@pytest.fixture
def jwt_token():
    """JWT Token válido para testes"""
    from app.middleware.auth import create_jwt_token
    return create_jwt_token(
        subject="test_user_123",
        token_type="user",
        permissions=["read", "write"]
    )


@pytest.fixture
def admin_jwt_token():
    """JWT Token de admin para testes"""
    from app.middleware.auth import create_jwt_token
    return create_jwt_token(
        subject="admin_user",
        token_type="user",
        permissions=["admin", "read", "write"]
    )


# Utilitário para patches
@pytest.fixture
def patch_all_externals(mock_redis, mock_db, mock_openai):
    """Aplica todos os mocks de serviços externos"""
    with patch("app.infra.redis.get_redis_client", return_value=mock_redis), \
         patch("app.infra.db.get_db_connection", return_value=mock_db), \
         patch("openai.OpenAI", return_value=mock_openai):
        yield {
            "redis": mock_redis,
            "db": mock_db,
            "openai": mock_openai
        }
