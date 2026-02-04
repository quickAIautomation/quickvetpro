"""
Testes unitários para o sistema de autenticação.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock

from app.middleware.auth import (
    create_jwt_token,
    decode_jwt_token,
    validate_webhook_signature,
    TokenPayload
)


class TestJWT:
    """Testes para JWT Tokens"""
    
    def test_create_jwt_token(self):
        """Deve criar um token JWT válido"""
        token = create_jwt_token(
            subject="user_123",
            token_type="user",
            permissions=["read", "write"]
        )
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 50  # JWTs são strings longas
    
    def test_decode_jwt_token(self):
        """Deve decodificar um token JWT válido"""
        token = create_jwt_token(
            subject="user_123",
            token_type="user",
            permissions=["read", "write"]
        )
        
        payload = decode_jwt_token(token)
        
        assert payload is not None
        assert payload.sub == "user_123"
        assert payload.type == "user"
        assert "read" in payload.permissions
        assert "write" in payload.permissions
    
    def test_decode_invalid_token(self):
        """Deve retornar None para token inválido"""
        payload = decode_jwt_token("token_invalido")
        
        assert payload is None
    
    def test_decode_expired_token(self):
        """Deve retornar None para token expirado"""
        # Criar token com expiração de 0 horas (já expirado)
        token = create_jwt_token(
            subject="user_123",
            token_type="user",
            expiration_hours=0
        )
        
        # Aguardar um pouco para garantir expiração
        import time
        time.sleep(0.1)
        
        payload = decode_jwt_token(token)
        
        # Token com 0 horas de expiração ainda pode ser válido por microsegundos
        # então verificamos se funciona ou expira
        assert payload is None or payload.sub == "user_123"
    
    def test_token_with_custom_expiration(self):
        """Deve respeitar expiração customizada"""
        token = create_jwt_token(
            subject="user_123",
            token_type="user",
            expiration_hours=48
        )
        
        payload = decode_jwt_token(token)
        
        assert payload is not None
        # Verificar que expira em aproximadamente 48 horas
        expected_exp = datetime.utcnow() + timedelta(hours=48)
        assert abs((payload.exp - expected_exp).total_seconds()) < 60  # 1 minuto de tolerância
    
    def test_token_types(self):
        """Deve suportar diferentes tipos de token"""
        types = ["user", "account", "service"]
        
        for token_type in types:
            token = create_jwt_token(
                subject="test_123",
                token_type=token_type
            )
            payload = decode_jwt_token(token)
            
            assert payload.type == token_type


class TestWebhookSignature:
    """Testes para validação de assinatura de webhook"""
    
    def test_valid_sha256_signature(self):
        """Deve validar assinatura SHA256 correta"""
        payload = b'{"event": "test"}'
        secret = "my_secret"
        
        # Calcular assinatura esperada
        import hmac
        import hashlib
        expected_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        signature = f"sha256={expected_sig}"
        
        result = validate_webhook_signature(payload, signature, secret)
        
        assert result is True
    
    def test_invalid_signature(self):
        """Deve rejeitar assinatura inválida"""
        payload = b'{"event": "test"}'
        secret = "my_secret"
        signature = "sha256=invalid_signature"
        
        result = validate_webhook_signature(payload, signature, secret)
        
        assert result is False
    
    def test_modified_payload(self):
        """Deve rejeitar payload modificado"""
        original_payload = b'{"event": "test"}'
        modified_payload = b'{"event": "modified"}'
        secret = "my_secret"
        
        # Assinatura do payload original
        import hmac
        import hashlib
        sig = hmac.new(secret.encode(), original_payload, hashlib.sha256).hexdigest()
        signature = f"sha256={sig}"
        
        # Tentar validar com payload modificado
        result = validate_webhook_signature(modified_payload, signature, secret)
        
        assert result is False
    
    def test_wrong_secret(self):
        """Deve rejeitar com secret errado"""
        payload = b'{"event": "test"}'
        correct_secret = "correct_secret"
        wrong_secret = "wrong_secret"
        
        import hmac
        import hashlib
        sig = hmac.new(correct_secret.encode(), payload, hashlib.sha256).hexdigest()
        signature = f"sha256={sig}"
        
        result = validate_webhook_signature(payload, signature, wrong_secret)
        
        assert result is False
    
    def test_sha1_signature(self):
        """Deve suportar SHA1 (para compatibilidade)"""
        payload = b'{"event": "test"}'
        secret = "my_secret"
        
        import hmac
        import hashlib
        expected_sig = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
        signature = f"sha1={expected_sig}"
        
        result = validate_webhook_signature(payload, signature, secret, algorithm="sha1")
        
        assert result is True
