"""
Main FastAPI application for QuickVET PRO
Backend principal para IA WhatsApp Veterinários
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import os

from app.api.webhook_whatsapp import router as webhook_router
from app.api.stripe_checkout import router as stripe_router
from app.api.platform import router as platform_router
from app.api.knowledge import router as knowledge_router
from app.api.structural_knowledge import router as structural_router
from app.api.admin import router as admin_router
from app.api.oauth import router as oauth_router
from app.api.connect import router as connect_router
from app.infra.db import init_db, close_db
from app.infra.redis import init_redis, close_redis
from app.infra.logging_config import setup_logging, get_logger
from app.infra.cache import CacheWarmer, CacheMetrics
from app.middleware.observability import ObservabilityMiddleware, metrics
from app.middleware.rate_limit import RateLimitMiddleware, rate_limiter
from app.config import settings

# Configurar logging no início
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "logs")
setup_logging(log_level=LOG_LEVEL, log_dir=LOG_DIR)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicação"""
    # Inicialização (com tratamento de erros para desenvolvimento)
    try:
        await init_db()
    except Exception as e:
        print(f"Aviso: Não foi possível inicializar o banco de dados: {e}")
        print("A aplicação continuará rodando, mas funcionalidades de DB estarão desabilitadas.")
    
    try:
        await init_redis()
    except Exception as e:
        print(f"Aviso: Não foi possível inicializar o Redis: {e}")
        print("A aplicação continuará rodando, mas funcionalidades de cache estarão desabilitadas.")
    
    # Pré-aquecimento de cache (opcional, configurável via env)
    if os.getenv("CACHE_WARMUP_ENABLED", "true").lower() == "true":
        try:
            from app.services.knowledge_service import knowledge_service
            warmup_count = await CacheWarmer.warmup(knowledge_service.search)
            logger.info(f"Cache pré-aquecido com {warmup_count} queries")
        except Exception as e:
            logger.warning(f"Pré-aquecimento de cache falhou: {e}")
    
    # Iniciar Alert Monitor em background (opcional)
    if os.getenv("ALERT_MONITOR_ENABLED", "true").lower() == "true":
        try:
            from app.services.alert_service import alert_monitor
            import asyncio
            # Iniciar monitor em background
            asyncio.create_task(alert_monitor.start())
            logger.info("Alert Monitor iniciado")
        except Exception as e:
            logger.warning(f"Falha ao iniciar Alert Monitor: {e}")
    
    # Inicializar admin padrão
    try:
        from app.services.admin_service import admin_service
        await admin_service.initialize_admin()
        logger.info("Admin inicializado")
    except Exception as e:
        logger.warning(f"Falha ao inicializar admin: {e}")
    
    yield
    
    # Encerrar Alert Monitor
    try:
        from app.services.alert_service import alert_monitor
        alert_monitor.stop()
    except:
        pass
    
    # Encerramento
    try:
        await close_db()
    except:
        pass
    try:
        await close_redis()
    except:
        pass


app = FastAPI(
    title="QuickVET PRO API",
    description="API para IA WhatsApp Veterinários",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware de Observabilidade (deve ser primeiro)
app.add_middleware(ObservabilityMiddleware)

# Middleware de Rate Limiting
if os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true":
    app.add_middleware(RateLimitMiddleware)

# CORS middleware
allowed_origins = [
    settings.frontend_domain,
    "https://quickvetpro.com.br",
    "http://localhost:3000",  # Para desenvolvimento local
    "http://localhost:5173",  # Vite dev server
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas
app.include_router(webhook_router, prefix="/api/webhook", tags=["webhook"])
app.include_router(stripe_router, prefix="/api/stripe", tags=["stripe"])
app.include_router(platform_router, prefix="/api", tags=["platform"])
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(structural_router, prefix="/api/structural", tags=["structural-knowledge"])
app.include_router(admin_router, tags=["admin"])
app.include_router(oauth_router, tags=["oauth"])
app.include_router(connect_router, prefix="/api", tags=["stripe-connect"])

# Servir arquivos estáticos
public_path = Path(__file__).parent.parent / "public"
if public_path.exists():
    app.mount("/static", StaticFiles(directory=str(public_path)), name="static")


@app.get("/")
async def root():
    """Health check endpoint ou página inicial"""
    index_path = public_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"status": "ok", "service": "QuickVET PRO API"}


@app.get("/health")
async def health():
    """Health check detalhado"""
    return {
        "status": "healthy",
        "service": "QuickVET PRO API",
        "version": "1.0.0"
    }


@app.get("/metrics")
async def get_metrics():
    """
    Endpoint de métricas para observabilidade.
    Retorna estatísticas de uso da API.
    """
    return JSONResponse(metrics.get_stats())


@app.get("/logs/info")
async def logs_info():
    """
    Informações sobre a configuração de logs.
    """
    log_path = Path(LOG_DIR)
    log_files = []
    
    if log_path.exists():
        for f in log_path.iterdir():
            if f.is_file():
                log_files.append({
                    "name": f.name,
                    "size_kb": round(f.stat().st_size / 1024, 2),
                    "modified": f.stat().st_mtime
                })
    
    return JSONResponse({
        "log_level": LOG_LEVEL,
        "log_directory": str(log_path.absolute()),
        "log_files": sorted(log_files, key=lambda x: x["name"])
    })


@app.get("/cache/stats")
async def cache_stats():
    """
    Estatísticas do sistema de cache.
    Retorna hits, misses, hit rate por tipo de cache.
    """
    stats = await CacheMetrics.get_stats()
    warmup_status = await CacheWarmer.get_warmup_status()
    
    return JSONResponse({
        "cache_stats": stats,
        "warmup_status": warmup_status
    })


@app.post("/cache/warmup")
async def trigger_cache_warmup():
    """
    Dispara pré-aquecimento manual do cache.
    Útil após invalidação ou deploy.
    """
    try:
        from app.services.knowledge_service import knowledge_service
        warmup_count = await CacheWarmer.warmup(knowledge_service.search)
        return JSONResponse({
            "status": "success",
            "queries_warmed": warmup_count
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)
