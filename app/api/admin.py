"""
API de Administração
====================

Endpoints para o painel admin.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from app.services.admin_service import admin_service
from app.middleware.auth import get_current_user, AuthenticatedUser

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


# ==================== MODELOS ====================

class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    admin: dict


class ConversationResponse(BaseModel):
    conversation_id: int
    user_id: Optional[str]
    phone_number: str
    status: str
    message_status: str
    last_message_at: str
    last_message_from: str
    last_message_preview: Optional[str]
    total_messages: int
    started_at: str
    resolved_at: Optional[str]
    user_name: Optional[str]
    user_email: Optional[str]


class MessageResponse(BaseModel):
    message_id: int
    role: str
    content: str
    has_media: bool
    media_type: Optional[str]
    whatsapp_message_id: Optional[str]
    created_at: str


class UpdateStatusRequest(BaseModel):
    status: str


class DashboardStatsResponse(BaseModel):
    total_conversations: int
    active_conversations: int
    pending_conversations: int
    resolved_today: int
    messages_today: int
    total_users: int


class UserResponse(BaseModel):
    user_id: str
    phone_number: str
    email: Optional[str]
    name: Optional[str]
    created_at: str
    plan_type: Optional[str]
    plan_status: Optional[str]
    plan_expires_at: Optional[str]
    total_conversations: int
    total_messages: int
    messages_today: int
    last_message_at: Optional[str]


class UserStatsResponse(BaseModel):
    total_users: int
    plan_distribution: dict
    top_users_by_messages: List[dict]


# ==================== AUTENTICAÇÃO ====================

async def require_admin(
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> dict:
    """Dependency para verificar autenticação admin"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token de autenticação necessário")
    
    token = authorization.split(" ")[1]
    payload = await admin_service.verify_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    
    return payload


# ==================== ENDPOINTS ====================

@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(data: AdminLoginRequest):
    """Login do admin"""
    result = await admin_service.authenticate(data.email, data.password)
    
    if not result:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    
    return result


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(admin: dict = Depends(require_admin)):
    """Retorna estatísticas do dashboard"""
    stats = await admin_service.get_dashboard_stats()
    return stats


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin: dict = Depends(require_admin)
):
    """Lista conversas"""
    conversations = await admin_service.get_conversations(
        status=status,
        limit=limit,
        offset=offset
    )
    return conversations


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages(
    conversation_id: int,
    limit: int = 100,
    admin: dict = Depends(require_admin)
):
    """Busca mensagens de uma conversa"""
    messages = await admin_service.get_conversation_messages(
        conversation_id=conversation_id,
        limit=limit
    )
    return messages


@router.patch("/conversations/{conversation_id}/status")
async def update_conversation_status(
    conversation_id: int,
    data: UpdateStatusRequest,
    admin: dict = Depends(require_admin)
):
    """Atualiza status de uma conversa"""
    if data.status not in ["active", "inactive", "pending", "resolved"]:
        raise HTTPException(status_code=400, detail="Status inválido")
    
    success = await admin_service.update_conversation_status(
        conversation_id=conversation_id,
        status=data.status
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Erro ao atualizar status")
    
    return {"success": True}


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    limit: int = 100,
    offset: int = 0,
    plan_type: Optional[str] = None,
    admin: dict = Depends(require_admin)
):
    """Lista usuários com planos e estatísticas de mensagens"""
    users = await admin_service.get_users(
        limit=limit,
        offset=offset,
        plan_type=plan_type
    )
    return users


@router.get("/users/stats", response_model=UserStatsResponse)
async def get_user_stats(admin: dict = Depends(require_admin)):
    """Retorna estatísticas de usuários"""
    stats = await admin_service.get_user_stats()
    return stats
