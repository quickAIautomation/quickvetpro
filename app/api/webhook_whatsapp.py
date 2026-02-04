"""
Webhook para API oficial do WhatsApp Business (Meta Cloud API)
Documentação: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import os
import hmac
import hashlib
import httpx
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
import logging

from app.services.quota_service import QuotaService
from app.services.plan_service import PlanService
from app.services.consent_service import ConsentService
from app.services.media_service import media_service, MediaType
from app.services.message_formatter import message_formatter, MessageType
from app.services.conversation_tracker import conversation_tracker
from app.agents.vet_agent import VetAgent
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Configurações da API do WhatsApp
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "quickvet_verify_token")


# ==================== MODELOS ====================

class WhatsAppWebhookPayload(BaseModel):
    """Payload do webhook do WhatsApp"""
    object: str
    entry: List[Dict[str, Any]]


# ==================== VERIFICAÇÃO DO WEBHOOK ====================

@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Verificação do webhook pelo Meta (Facebook)
    Chamado quando você configura o webhook no Meta Business Suite
    """
    logger.info(f"Verificação de webhook recebida: mode={hub_mode}")
    
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("Webhook verificado com sucesso")
        return int(hub_challenge)
    
    logger.warning(f"Falha na verificação: token={hub_verify_token}")
    raise HTTPException(status_code=403, detail="Verificação falhou")


# ==================== RECEBIMENTO DE MENSAGENS ====================

@router.post("/whatsapp")
async def receive_webhook(request: Request):
    """
    Recebe mensagens do WhatsApp via webhook
    
    Fluxo:
    1. Validar assinatura do webhook
    2. Extrair mensagem do payload
    3. Processar mensagem (verificar plano, quota, consentimento)
    4. Chamar agente veterinário
    5. Enviar resposta via API do WhatsApp
    """
    # 1. Validar assinatura (segurança)
    signature = request.headers.get("X-Hub-Signature-256", "")
    body = await request.body()
    
    if not _verify_signature(body, signature):
        logger.warning("Assinatura inválida no webhook")
        raise HTTPException(status_code=401, detail="Assinatura inválida")
    
    # 2. Parse do payload
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ok"}
    
    # Verificar se é mensagem do WhatsApp
    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ok"}
    
    # 3. Processar cada mensagem
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            
            for message in messages:
                await _process_message(message, value)
    
    return {"status": "ok"}


async def _process_message(message: dict, value: dict):
    """Processa uma mensagem individual (texto, imagem, áudio, vídeo)"""
    try:
        # Extrair dados
        from_number = message.get("from")  # Número do remetente
        message_id = message.get("id")
        message_type = message.get("type")
        
        # Extrair conteúdo baseado no tipo
        message_body = ""
        media_content = None
        
        if message_type == "text":
            message_body = message.get("text", {}).get("body", "")
            
        elif message_type == "image":
            # Processar imagem
            image_data = message.get("image", {})
            media_id = image_data.get("id")
            caption = image_data.get("caption", "")
            
            logger.info(f"Imagem recebida de {from_number}, media_id: {media_id}")
            
            processed = await media_service.process_media(
                media_id=media_id,
                media_type=MediaType.IMAGE,
                context=caption
            )
            media_content = processed.description
            message_body = caption if caption else "[Imagem enviada]"
            
        elif message_type == "audio":
            # Processar áudio (transcrever com Whisper)
            audio_data = message.get("audio", {})
            media_id = audio_data.get("id")
            
            logger.info(f"Áudio recebido de {from_number}, media_id: {media_id}")
            
            processed = await media_service.process_media(
                media_id=media_id,
                media_type=MediaType.AUDIO
            )
            # Usar transcrição como mensagem
            media_content = processed.description
            message_body = processed.description.replace("[Transcrição do áudio]: ", "")
            
        elif message_type == "video":
            # Processar vídeo
            video_data = message.get("video", {})
            media_id = video_data.get("id")
            caption = video_data.get("caption", "")
            
            logger.info(f"Vídeo recebido de {from_number}, media_id: {media_id}")
            
            processed = await media_service.process_media(
                media_id=media_id,
                media_type=MediaType.VIDEO,
                context=caption
            )
            media_content = processed.description
            message_body = caption if caption else "[Vídeo enviado]"
            
        elif message_type == "sticker":
            # Stickers são tratados como imagens
            sticker_data = message.get("sticker", {})
            media_id = sticker_data.get("id")
            
            processed = await media_service.process_media(
                media_id=media_id,
                media_type=MediaType.STICKER
            )
            media_content = processed.description
            message_body = "[Sticker enviado]"
            
        elif message_type == "document":
            # Documentos não são processados por enquanto
            await send_whatsapp_message(
                to=from_number,
                message="Recebi seu documento. No momento, consigo analisar melhor imagens e áudios. Se possível, envie uma foto do que deseja consultar."
            )
            return
            
        else:
            await send_whatsapp_message(
                to=from_number,
                message="Desculpe, não consegui processar esse tipo de mensagem. Tente enviar texto, imagem ou áudio."
            )
            return
        
        logger.info(f"Mensagem recebida de {from_number}: {message_body[:50]}...")
        
        # Comandos especiais
        message_upper = message_body.strip().upper()
        
        # Consentimento LGPD
        if message_upper == "CONSENTO":
            consent_service = ConsentService()
            await consent_service.save_consent(from_number)
            await send_whatsapp_message(
                to=from_number,
                message="Obrigado! Seu consentimento foi registrado. Como posso ajudar com seu animal?"
            )
            return
        
        # Limpar histórico de conversa
        if message_upper in ["NOVA CONVERSA", "LIMPAR", "RESET", "REINICIAR"]:
            vet_agent = VetAgent()
            await vet_agent.clear_conversation(from_number)
            await send_whatsapp_message(
                to=from_number,
                message="Conversa reiniciada! Como posso ajudar você hoje?"
            )
            return
        
        # Verificar plano ativo
        plan_service = PlanService()
        if not await plan_service.is_plan_active(from_number):
            await send_whatsapp_message(
                to=from_number,
                message="Seu plano nao esta ativo. Acesse quickvet.com.br para assinar."
            )
            return
        
        # Verificar quota diária
        quota_service = QuotaService()
        if not await quota_service.check_and_increment_quota(from_number):
            await send_whatsapp_message(
                to=from_number,
                message="Voce atingiu o limite diario de mensagens. Tente novamente amanha."
            )
            return
        
        # Verificar consentimento LGPD
        consent_service = ConsentService()
        if not await consent_service.has_consent(from_number):
            await send_whatsapp_message(
                to=from_number,
                message="Para usar o QuickVET, precisamos do seu consentimento para processar dados. Digite CONSENTO para aceitar."
            )
            return
        
        # Rastrear mensagem do usuário
        await conversation_tracker.track_message(
            user_id=from_number,
            phone_number=from_number,
            role="user",
            content=message_body,
            has_media=bool(media_content),
            media_type=message_type if media_content else None,
            whatsapp_message_id=message_id
        )
        
        # Processar com agente veterinário
        vet_agent = VetAgent()
        response = await vet_agent.process_message(
            user_id=from_number,
            message=message_body,
            media_description=media_content  # Passa análise da mídia se houver
        )
        
        # Verificar se o agente quer solicitar mídia
        if not media_content:
            media_request = media_service.should_request_media(message_body)
            if media_request and "[MEDIA_REQUESTED]" not in response:
                # Adicionar sugestão de enviar mídia à resposta
                response = f"{response}\n\n💡 {media_request}"
        
        # Formatar e enviar resposta
        formatted_messages = message_formatter.format_response(response)
        
        for msg in formatted_messages:
            result = await send_formatted_message(to=from_number, message=msg)
            # Rastrear mensagem do assistente
            if result:
                whatsapp_id = result.get("messages", [{}])[0].get("id") if result.get("messages") else None
                # Extrair conteúdo da mensagem formatada
                if hasattr(msg, 'content'):
                    msg_content = msg.content if isinstance(msg.content, str) else str(msg.content)
                else:
                    msg_content = response  # Fallback para resposta original
                await conversation_tracker.track_message(
                    user_id=from_number,
                    phone_number=from_number,
                    role="assistant",
                    content=msg_content[:500],  # Limitar tamanho
                    whatsapp_message_id=whatsapp_id
                )
        
        # Log de auditoria
        await consent_service.log_message(from_number, message_body, response)
        
    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}", exc_info=True)
        try:
            await send_whatsapp_message(
                to=message.get("from"),
                message="Desculpe, ocorreu um erro. Tente novamente em instantes."
            )
        except:
            pass


# ==================== ENVIO DE MENSAGENS ====================

async def send_formatted_message(to: str, message) -> Optional[dict]:
    """
    Envia mensagem formatada (texto, botões ou lista).
    
    Args:
        to: Número do destinatário
        message: FormattedMessage do message_formatter
        
    Returns:
        Resposta da API ou None em caso de erro
    """
    url = f"{WHATSAPP_API_URL}/{settings.whatsapp_phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_api_token}",
        "Content-Type": "application/json"
    }
    
    # Converter para payload do WhatsApp
    payload = message.to_whatsapp_payload(to)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                logger.info(f"Mensagem formatada enviada para {to} (tipo: {message.type.value})")
                return response.json()
            else:
                logger.error(f"Erro ao enviar mensagem formatada: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Erro na requisição WhatsApp: {e}")
        return None


async def send_whatsapp_message(to: str, message: str, message_type: str = "text"):
    """
    Envia mensagem via API oficial do WhatsApp
    
    Args:
        to: Número do destinatário (com código do país, ex: 5511999999999)
        message: Texto da mensagem
        message_type: Tipo da mensagem (text, template, etc)
    """
    url = f"{WHATSAPP_API_URL}/{settings.whatsapp_phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_api_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": message_type,
        "text": {
            "preview_url": False,
            "body": message
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                logger.info(f"Mensagem enviada para {to}")
                return response.json()
            else:
                logger.error(f"Erro ao enviar mensagem: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Erro na requisição WhatsApp: {e}")
        return None


async def send_whatsapp_template(to: str, template_name: str, language: str = "pt_BR", components: list = None):
    """
    Envia mensagem usando template aprovado pelo WhatsApp
    
    Templates precisam ser aprovados no Meta Business Suite
    """
    url = f"{WHATSAPP_API_URL}/{settings.whatsapp_phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_api_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language}
        }
    }
    
    if components:
        payload["template"]["components"] = components
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao enviar template: {e}")
        return None


# ==================== FUNÇÕES AUXILIARES ====================

def _verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verifica a assinatura do webhook do Meta
    """
    if not signature:
        # Em desenvolvimento, permitir sem assinatura
        return settings.environment == "development"
    
    app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not app_secret:
        return settings.environment == "development"
    
    expected_signature = hmac.new(
        app_secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(f"sha256={expected_signature}", signature)


# ==================== ENDPOINTS AUXILIARES ====================

@router.get("/status")
async def whatsapp_status():
    """Verifica status da integração WhatsApp"""
    return {
        "configured": bool(settings.whatsapp_api_token and settings.whatsapp_phone_number_id),
        "phone_number_id": settings.whatsapp_phone_number_id[:6] + "..." if settings.whatsapp_phone_number_id else None,
        "business_account_id": getattr(settings, 'whatsapp_business_account_id', None),
        "api_version": "v18.0"
    }
