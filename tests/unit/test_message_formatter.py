"""
Testes unitários para o MessageFormatter.
"""
import pytest
from app.services.message_formatter import MessageFormatter


class TestMessageFormatter:
    """Testes para formatação de mensagens WhatsApp"""
    
    @pytest.fixture
    def formatter(self):
        return MessageFormatter()
    
    # ==================== TESTES DE SPLIT DE MENSAGENS ====================
    
    def test_short_message_not_split(self, formatter):
        """Mensagens curtas não devem ser divididas"""
        text = "Esta é uma mensagem curta."
        result = formatter.format_text_message(text)
        
        assert len(result) == 1
        assert "curta" in result[0]
    
    def test_long_message_split(self, formatter):
        """Mensagens longas devem ser divididas"""
        # Criar mensagem maior que 4096 caracteres
        text = "Esta é uma frase. " * 300  # ~5400 chars
        result = formatter.format_text_message(text)
        
        assert len(result) > 1
        assert "continua" in result[0]
    
    def test_split_preserves_sentences(self, formatter):
        """Split deve preservar frases completas"""
        text = "Primeira frase completa. Segunda frase completa. Terceira frase."
        # Simular mensagem longa
        formatter.MAX_MESSAGE_LENGTH = 50
        result = formatter._split_long_message(text)
        
        # Nenhuma frase deve estar cortada no meio
        for part in result:
            # Remove indicador de continuação
            clean_part = part.replace("_...continua", "").strip()
            # Deve terminar com pontuação ou indicador
            assert clean_part[-1] in ".!?" or "continua" in part
    
    # ==================== TESTES DE CONVERSÃO MARKDOWN ====================
    
    def test_bold_conversion(self, formatter):
        """Negrito Markdown deve converter para WhatsApp"""
        text = "Isso é **negrito** aqui"
        result = formatter._markdown_to_whatsapp(text)
        
        assert "*negrito*" in result
        assert "**" not in result
    
    def test_italic_conversion(self, formatter):
        """Itálico Markdown deve converter para WhatsApp"""
        text = "Isso é _itálico_ aqui"
        result = formatter._markdown_to_whatsapp(text)
        
        assert "_itálico_" in result
    
    def test_strikethrough_conversion(self, formatter):
        """Tachado deve converter corretamente"""
        text = "Isso é ~~tachado~~ aqui"
        result = formatter._markdown_to_whatsapp(text)
        
        assert "~tachado~" in result
        assert "~~" not in result
    
    def test_code_conversion(self, formatter):
        """Código inline deve converter para WhatsApp"""
        text = "Use `comando` aqui"
        result = formatter._markdown_to_whatsapp(text)
        
        assert "```comando```" in result
    
    def test_link_conversion(self, formatter):
        """Links Markdown devem ser convertidos"""
        text = "Veja [este link](https://example.com)"
        result = formatter._markdown_to_whatsapp(text)
        
        assert "este link: https://example.com" in result
        assert "[" not in result
    
    # ==================== TESTES DE EMOJIS CONTEXTUAIS ====================
    
    def test_emergency_emoji(self, formatter):
        """Mensagens de emergência devem ter emoji de alerta"""
        text = "Esta é uma emergência veterinária"
        result = formatter._add_emojis_contextually(text)
        
        assert "🚨" in result
    
    def test_symptom_emoji(self, formatter):
        """Mensagens sobre sintomas devem ter emoji de busca"""
        text = "Os sintomas incluem febre e vômito"
        result = formatter._add_emojis_contextually(text)
        
        assert "🔍" in result
    
    def test_treatment_emoji(self, formatter):
        """Mensagens sobre tratamento devem ter emoji de medicamento"""
        text = "O tratamento inclui medicamentos"
        result = formatter._add_emojis_contextually(text)
        
        assert "💊" in result
    
    # ==================== TESTES DE BOTÕES ====================
    
    def test_button_message_format(self, formatter):
        """Formato de mensagem com botões"""
        text = "Escolha uma opção:"
        buttons = ["Opção 1", "Opção 2"]
        
        result = formatter.format_with_buttons(text, buttons)
        
        assert result["type"] == "interactive"
        assert result["interactive"]["type"] == "button"
        assert len(result["interactive"]["action"]["buttons"]) == 2
    
    def test_max_buttons_limit(self, formatter):
        """Máximo de 3 botões deve ser respeitado"""
        text = "Escolha uma opção:"
        buttons = ["1", "2", "3", "4", "5"]  # Mais que o limite
        
        result = formatter.format_with_buttons(text, buttons)
        
        # Deve retornar fallback de texto
        assert result["type"] == "text"
    
    # ==================== TESTES DE LISTAS ====================
    
    def test_list_message_format(self, formatter):
        """Formato de mensagem com lista"""
        result = formatter.format_with_list(
            header="Selecione",
            body="Escolha um item:",
            button_text="Ver opções",
            sections=[{
                "title": "Seção 1",
                "rows": [
                    {"title": "Item 1", "description": "Desc 1"},
                    {"title": "Item 2", "description": "Desc 2"}
                ]
            }]
        )
        
        assert result["type"] == "interactive"
        assert result["interactive"]["type"] == "list"
    
    # ==================== TESTES DE TEMPLATES ====================
    
    def test_emergency_response_format(self, formatter):
        """Resposta de emergência deve ter formatação especial"""
        text = "Leve ao veterinário imediatamente"
        result = formatter.format_emergency_response(text)
        
        assert len(result) >= 1
        assert "🚨" in result[0]
        assert "EMERGÊNCIA" in result[0]
        assert "IMEDIATAMENTE" in result[0]
    
    def test_urgency_buttons(self, formatter):
        """Botões de urgência devem estar corretos"""
        text = "Como você classifica a urgência?"
        result = formatter.format_with_urgency_buttons(text)
        
        assert result["type"] == "interactive"
        buttons = result["interactive"]["action"]["buttons"]
        assert len(buttons) == 3
        
        # Verificar títulos dos botões
        titles = [b["reply"]["title"] for b in buttons]
        assert "É uma emergência" in titles
    
    def test_feedback_buttons(self, formatter):
        """Botões de feedback devem estar corretos"""
        text = "Essa informação foi útil?"
        result = formatter.format_with_feedback_buttons(text)
        
        assert result["type"] == "interactive"
        buttons = result["interactive"]["action"]["buttons"]
        assert len(buttons) == 2
