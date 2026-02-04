"""
Configurações da aplicação
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Database
    database_url: str = "postgresql://user:password@localhost:5432/quickvet"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    
    # RAG - Modo de Recuperação
    # Opções: vector (busca semântica), structural (navegação hierárquica), 
    #         hybrid (ambos), auto (decide automaticamente)
    retrieval_mode: str = "auto"
    
    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    platform_price_id: str = ""
    
    # Frontend
    frontend_domain: str = "https://quickvetpro.com.br"
    
    # WhatsApp Business API (Meta Cloud API)
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_verify_token: str = "quickvet_verify_token"
    whatsapp_app_secret: str = ""
    
    # Limites
    daily_message_limit: int = 50
    
    # Ambiente
    environment: str = "development"
    debug: bool = False


settings = Settings()
