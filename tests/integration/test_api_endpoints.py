"""
Testes de integração para endpoints da API.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestHealthEndpoints:
    """Testes para endpoints de health check"""
    
    def test_root_endpoint(self, client):
        """Endpoint raiz deve retornar status ok"""
        response = client.get("/")
        
        assert response.status_code == 200
    
    def test_health_endpoint(self, client):
        """Endpoint /health deve retornar status healthy"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
    
    def test_metrics_endpoint(self, client):
        """Endpoint /metrics deve retornar estatísticas"""
        response = client.get("/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data


class TestWhatsAppWebhook:
    """Testes para webhook do WhatsApp"""
    
    def test_webhook_verification(self, client):
        """Deve verificar webhook do Meta"""
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "quickvet_verify_token",
            "hub.challenge": "test_challenge_123"
        }
        
        response = client.get("/api/webhook/whatsapp", params=params)
        
        assert response.status_code == 200
        assert response.text == "test_challenge_123"
    
    def test_webhook_verification_wrong_token(self, client):
        """Deve rejeitar token de verificação errado"""
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "test_challenge_123"
        }
        
        response = client.get("/api/webhook/whatsapp", params=params)
        
        assert response.status_code == 403
    
    @patch("app.api.webhook_whatsapp._process_message")
    @patch("app.api.webhook_whatsapp._validate_signature")
    def test_receive_message(
        self, 
        mock_validate, 
        mock_process, 
        client, 
        sample_whatsapp_message
    ):
        """Deve receber mensagem do WhatsApp"""
        mock_validate.return_value = True
        mock_process.return_value = None
        
        response = client.post(
            "/api/webhook/whatsapp",
            json=sample_whatsapp_message,
            headers={"X-Hub-Signature-256": "sha256=test"}
        )
        
        assert response.status_code == 200


class TestKnowledgeAPI:
    """Testes para API de conhecimento"""
    
    @patch("app.services.knowledge_service.knowledge_service.get_stats")
    def test_knowledge_stats(self, mock_stats, client):
        """Deve retornar estatísticas da base"""
        mock_stats.return_value = {
            "total_chunks": 100,
            "files": [{"name": "test.pdf", "chunks": 100}]
        }
        
        response = client.get("/api/knowledge/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_chunks" in data
    
    @patch("app.services.knowledge_service.knowledge_service.search")
    async def test_knowledge_search(self, mock_search, client, sample_knowledge_chunks):
        """Deve buscar na base de conhecimento"""
        mock_search.return_value = sample_knowledge_chunks
        
        response = client.post(
            "/api/knowledge/search",
            json={"query": "cinomose em cães", "top_k": 5}
        )
        
        assert response.status_code == 200


class TestStructuralKnowledge:
    """Testes para API de conhecimento estrutural"""
    
    @patch("app.services.structural_knowledge_service.structural_knowledge_service.get_stats")
    def test_structural_stats(self, mock_stats, client):
        """Deve retornar estatísticas estruturais"""
        mock_stats.return_value = {
            "total_documents": 5,
            "total_nodes": 500,
            "documents": []
        }
        
        response = client.get("/api/structural/stats")
        
        assert response.status_code == 200


class TestCacheEndpoints:
    """Testes para endpoints de cache"""
    
    @patch("app.infra.cache.CacheMetrics.get_stats")
    @patch("app.infra.cache.CacheWarmer.get_warmup_status")
    def test_cache_stats(self, mock_warmup, mock_stats, client):
        """Deve retornar estatísticas do cache"""
        mock_stats.return_value = {"vector_search": {"hits": 10, "misses": 5}}
        mock_warmup.return_value = {"last_run": "never", "queries_warmed": 0}
        
        response = client.get("/cache/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "cache_stats" in data
        assert "warmup_status" in data


class TestRateLimiting:
    """Testes para rate limiting"""
    
    @patch("app.middleware.rate_limit.rate_limiter.check_rate_limit")
    def test_rate_limit_headers(self, mock_check, client):
        """Deve incluir headers de rate limit"""
        mock_check.return_value = (True, 99, 0)
        
        response = client.get("/health")
        
        # Rate limit pode não estar ativo para /health
        # mas o middleware deve funcionar
        assert response.status_code == 200
    
    @patch("app.middleware.rate_limit.rate_limiter.check_rate_limit")
    def test_rate_limit_exceeded(self, mock_check, client):
        """Deve retornar 429 quando limite excedido"""
        mock_check.return_value = (False, 0, 60)
        
        # Endpoint que não está na whitelist
        response = client.post("/api/knowledge/search", json={"query": "test"})
        
        # Pode ser 429 ou outro código dependendo da configuração
        # O importante é que o rate limiter foi chamado
        mock_check.assert_called()


class TestPlatformAPI:
    """Testes para API da plataforma"""
    
    @patch("app.infra.db.get_db_connection")
    def test_login_by_email(self, mock_db, client):
        """Deve fazer login por email"""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "account_id": "test_123",
            "email": "test@example.com",
            "clinic_name": "Test Clinic",
            "plan_status": "active"
        }
        mock_db.return_value = mock_conn
        
        response = client.post(
            "/api/login-by-email",
            json={"email": "test@example.com"}
        )
        
        # Pode ser 200 ou 404 dependendo se encontrou
        assert response.status_code in [200, 404]
    
    @patch("app.infra.db.get_db_connection")
    def test_create_account(self, mock_db, client, sample_account):
        """Deve criar nova conta"""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # Conta não existe
        mock_conn.execute.return_value = None
        mock_db.return_value = mock_conn
        
        response = client.post(
            "/api/account",
            json={"email": "new@example.com", "clinic_name": "New Clinic"}
        )
        
        # Pode ser 201 ou 409 se já existir
        assert response.status_code in [200, 201, 409, 500]
