"""
Configuração de Logging e Observabilidade para QuickVET PRO
===========================================================

Features:
- Logs estruturados em JSON
- Rotação de arquivos
- Níveis de log configuráveis
- Contexto de request (correlation_id)
- Stack traces completos com contexto
- Logs separados por categoria (erros, pagamentos, segurança)
- Sanitização de dados sensíveis
"""
import logging
import logging.handlers
import json
import sys
import os
import uuid
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextvars import ContextVar

# Context variables para rastreamento
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
request_context_var: ContextVar[Optional[Dict]] = ContextVar('request_context', default=None)

# Campos sensíveis para sanitização
SENSITIVE_FIELDS = [
    'password', 'senha', 'secret', 'token', 'api_key', 'apikey',
    'authorization', 'credit_card', 'cvv', 'card_number',
    'access_token', 'refresh_token', 'private_key'
]


def get_correlation_id() -> str:
    """Retorna o correlation_id atual ou gera um novo"""
    cid = correlation_id_var.get()
    if cid is None:
        cid = str(uuid.uuid4())[:8]
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(cid: str):
    """Define o correlation_id para o contexto atual"""
    correlation_id_var.set(cid)


def get_request_context() -> Optional[Dict]:
    """Retorna o contexto da request atual"""
    return request_context_var.get()


def set_request_context(context: Dict):
    """Define o contexto da request atual"""
    request_context_var.set(context)


def sanitize_data(data: Any, depth: int = 0) -> Any:
    """
    Sanitiza dados sensíveis recursivamente.
    Substitui valores de campos sensíveis por '[REDACTED]'.
    """
    if depth > 10:  # Evitar recursão infinita
        return str(data)
    
    if isinstance(data, dict):
        return {
            k: '[REDACTED]' if any(s in k.lower() for s in SENSITIVE_FIELDS) 
               else sanitize_data(v, depth + 1)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [sanitize_data(item, depth + 1) for item in data]
    elif isinstance(data, str):
        # Sanitizar strings que parecem ser tokens/keys
        if len(data) > 20 and any(s in data.lower() for s in ['sk_', 'pk_', 'eyj', 'bearer']):
            return '[REDACTED]'
        return data
    else:
        return data


class DetailedJSONFormatter(logging.Formatter):
    """
    Formatter que gera logs em JSON estruturado com contexto detalhado.
    
    Inclui:
    - Timestamp ISO 8601
    - Stack trace completo para exceções
    - Contexto da request (path, method, user, IP)
    - Dados sanitizados
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
            "source": {
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
                "file": record.pathname.split(os.sep)[-1] if record.pathname else None
            }
        }
        
        # Adicionar contexto da request se disponível
        request_ctx = get_request_context()
        if request_ctx:
            log_data["request"] = sanitize_data(request_ctx)
        
        # Adicionar exceção com detalhes completos
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            
            # Stack trace formatado
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            
            # Extrair informações úteis do traceback
            tb_frames = []
            if exc_tb:
                for frame_info in traceback.extract_tb(exc_tb):
                    tb_frames.append({
                        "file": frame_info.filename,
                        "line": frame_info.lineno,
                        "function": frame_info.name,
                        "code": frame_info.line
                    })
            
            log_data["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": "".join(tb_lines),
                "frames": tb_frames[-5:] if tb_frames else [],  # Últimos 5 frames
            }
            
            # Adicionar causa se existir
            if exc_value and exc_value.__cause__:
                log_data["exception"]["cause"] = {
                    "type": type(exc_value.__cause__).__name__,
                    "message": str(exc_value.__cause__)
                }
        
        # Adicionar campos extras (sanitizados)
        if hasattr(record, 'extra_fields'):
            log_data["extra"] = sanitize_data(record.extra_fields)
        
        return json.dumps(log_data, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Formatter colorido para console com contexto"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        cid = get_correlation_id()
        
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        # Formato base
        base = (
            f"{color}[{timestamp}] "
            f"[{record.levelname:8}] "
            f"[{cid}] "
            f"{record.name}: "
            f"{record.getMessage()}{self.RESET}"
        )
        
        # Adicionar stack trace para erros
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            base += f"\n{self.COLORS['ERROR']}{exc_text}{self.RESET}"
        
        return base


class ErrorContextFilter(logging.Filter):
    """
    Filter que adiciona contexto extra para logs de erro.
    Captura variáveis locais e estado do sistema.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            # Adicionar informações do sistema
            if not hasattr(record, 'extra_fields'):
                record.extra_fields = {}
            
            # Métricas de sistema (se disponíveis)
            try:
                import psutil
                record.extra_fields['system'] = {
                    'cpu_percent': psutil.cpu_percent(),
                    'memory_percent': psutil.virtual_memory().percent
                }
            except ImportError:
                pass
        
        return True


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    json_logs: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5
):
    """
    Configura o sistema de logging.
    
    Args:
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Diretório para arquivos de log
        json_logs: Se True, logs em JSON; se False, texto simples
        max_bytes: Tamanho máximo do arquivo antes de rotacionar
        backup_count: Número de arquivos de backup a manter
    """
    # Criar diretório de logs
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Limpar handlers existentes
    root_logger.handlers.clear()
    
    # Adicionar filter de contexto
    error_filter = ErrorContextFilter()
    
    # Handler para console (sempre texto legível)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)
    
    # Formatter para arquivos
    file_formatter = DetailedJSONFormatter() if json_logs else logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Handler para arquivo principal (JSON estruturado)
    main_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    main_handler.setLevel(logging.DEBUG)
    main_handler.setFormatter(file_formatter)
    main_handler.addFilter(error_filter)
    root_logger.addHandler(main_handler)
    
    # Handler separado para erros (com mais detalhes)
    error_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet_errors.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    error_handler.addFilter(error_filter)
    root_logger.addHandler(error_handler)
    
    # Handler separado para Stripe/pagamentos (auditoria)
    stripe_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet_payments.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    stripe_handler.setLevel(logging.INFO)
    stripe_handler.setFormatter(file_formatter)
    stripe_logger = logging.getLogger("app.api.stripe")
    stripe_logger.addHandler(stripe_handler)
    
    # Handler separado para Platform (contas/clientes)
    platform_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet_platform.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    platform_handler.setLevel(logging.INFO)
    platform_handler.setFormatter(file_formatter)
    platform_logger = logging.getLogger("app.api.platform")
    platform_logger.addHandler(platform_handler)
    
    # Handler separado para segurança
    security_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet_security.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    security_handler.setLevel(logging.WARNING)
    security_handler.setFormatter(file_formatter)
    security_logger = logging.getLogger("app.security")
    security_logger.addHandler(security_handler)
    
    # Handler separado para WhatsApp
    whatsapp_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet_whatsapp.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    whatsapp_handler.setLevel(logging.INFO)
    whatsapp_handler.setFormatter(file_formatter)
    whatsapp_logger = logging.getLogger("app.api.webhook_whatsapp")
    whatsapp_logger.addHandler(whatsapp_handler)
    
    # Handler separado para RAG/Knowledge
    rag_handler = logging.handlers.RotatingFileHandler(
        log_path / "quickvet_rag.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    rag_handler.setLevel(logging.DEBUG)
    rag_handler.setFormatter(file_formatter)
    rag_logger = logging.getLogger("app.services.knowledge")
    rag_logger.addHandler(rag_handler)
    logging.getLogger("app.services.structural_knowledge").addHandler(rag_handler)
    logging.getLogger("app.services.mcp_knowledge_client").addHandler(rag_handler)
    
    # Configurar níveis específicos
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    root_logger.info(f"Logging configurado - Nível: {log_level}, Diretório: {log_path}")
    
    return root_logger


class LoggerWithContext:
    """Logger wrapper que adiciona contexto automaticamente"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def _log(self, level: int, msg: str, **kwargs):
        extra = {'extra_fields': sanitize_data(kwargs)} if kwargs else {}
        self.logger.log(level, msg, extra=extra)
    
    def debug(self, msg: str, **kwargs):
        self._log(logging.DEBUG, msg, **kwargs)
    
    def info(self, msg: str, **kwargs):
        self._log(logging.INFO, msg, **kwargs)
    
    def warning(self, msg: str, **kwargs):
        self._log(logging.WARNING, msg, **kwargs)
    
    def error(self, msg: str, **kwargs):
        self._log(logging.ERROR, msg, **kwargs)
    
    def critical(self, msg: str, **kwargs):
        self._log(logging.CRITICAL, msg, **kwargs)
    
    def exception(self, msg: str, **kwargs):
        """Log de exceção com stack trace completo"""
        self.logger.exception(msg, extra={'extra_fields': sanitize_data(kwargs)} if kwargs else {})
    
    def log_error_with_context(
        self,
        msg: str,
        exception: Exception = None,
        request_data: Dict = None,
        user_id: str = None,
        **kwargs
    ):
        """
        Log de erro com contexto completo.
        
        Args:
            msg: Mensagem de erro
            exception: Exceção ocorrida
            request_data: Dados da request (serão sanitizados)
            user_id: ID do usuário
            **kwargs: Campos adicionais
        """
        context = {
            "user_id": user_id,
            "request": sanitize_data(request_data) if request_data else None,
            "correlation_id": get_correlation_id(),
            **kwargs
        }
        
        if exception:
            context["exception_type"] = type(exception).__name__
            context["exception_message"] = str(exception)
        
        self.logger.error(
            msg,
            exc_info=exception is not None,
            extra={'extra_fields': context}
        )


def get_logger(name: str) -> LoggerWithContext:
    """Retorna um logger com contexto para o módulo especificado"""
    return LoggerWithContext(name)


# Logger de segurança específico
security_logger = get_logger("app.security")


def log_security_event(
    event_type: str,
    message: str,
    ip: str = None,
    user_id: str = None,
    **kwargs
):
    """
    Log específico para eventos de segurança.
    
    Args:
        event_type: Tipo do evento (login_failed, rate_limit, suspicious_activity, etc)
        message: Descrição do evento
        ip: IP do cliente
        user_id: ID do usuário (se conhecido)
        **kwargs: Dados adicionais
    """
    security_logger.warning(
        f"[SECURITY] {event_type}: {message}",
        event_type=event_type,
        ip=ip,
        user_id=user_id,
        **kwargs
    )
