import React from 'react'
import './ConversationList.css'

function ConversationList({ conversations, selectedId, onSelect, filter, onFilterChange, loading }) {
  const formatPhone = (phone) => {
    if (!phone) return 'N/A'
    // Formatar número brasileiro
    if (phone.length === 13 && phone.startsWith('55')) {
      return `+${phone.slice(0, 2)} (${phone.slice(2, 4)}) ${phone.slice(4, 9)}-${phone.slice(9)}`
    }
    return phone
  }

  const formatTime = (timestamp) => {
    if (!timestamp) return ''
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)
    
    if (diffMins < 1) return 'Agora'
    if (diffMins < 60) return `${diffMins}m`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h`
    return date.toLocaleDateString('pt-BR')
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'active': return '#25d366'
      case 'pending': return '#ff9800'
      case 'resolved': return '#4caf50'
      case 'inactive': return '#999'
      default: return '#999'
    }
  }

  const getStatusLabel = (status) => {
    switch (status) {
      case 'active': return 'Ativa'
      case 'pending': return 'Pendente'
      case 'resolved': return 'Resolvida'
      case 'inactive': return 'Inativa'
      default: return status
    }
  }

  return (
    <div className="conversation-list">
      <div className="conversation-list-header">
        <h2>Conversas</h2>
        <div className="filter-buttons">
          <button
            className={filter === 'all' ? 'active' : ''}
            onClick={() => onFilterChange('all')}
          >
            Todas
          </button>
          <button
            className={filter === 'active' ? 'active' : ''}
            onClick={() => onFilterChange('active')}
          >
            Ativas
          </button>
          <button
            className={filter === 'pending' ? 'active' : ''}
            onClick={() => onFilterChange('pending')}
          >
            Pendentes
          </button>
          <button
            className={filter === 'resolved' ? 'active' : ''}
            onClick={() => onFilterChange('resolved')}
          >
            Resolvidas
          </button>
        </div>
      </div>

      <div className="conversation-items">
        {loading ? (
          <div className="loading">Carregando...</div>
        ) : conversations.length === 0 ? (
          <div className="empty">Nenhuma conversa encontrada</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.conversation_id}
              className={`conversation-item ${selectedId === conv.conversation_id ? 'selected' : ''}`}
              onClick={() => onSelect(conv)}
            >
              <div className="conversation-header">
                <div className="conversation-phone">
                  {formatPhone(conv.phone_number)}
                </div>
                <div className="conversation-time">
                  {formatTime(conv.last_message_at)}
                </div>
              </div>
              
              <div className="conversation-preview">
                {conv.last_message_preview || 'Sem mensagens'}
              </div>
              
              <div className="conversation-footer">
                <span
                  className="status-badge"
                  style={{ backgroundColor: getStatusColor(conv.status) }}
                >
                  {getStatusLabel(conv.status)}
                </span>
                <span className="message-count">{conv.total_messages} msgs</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default ConversationList
