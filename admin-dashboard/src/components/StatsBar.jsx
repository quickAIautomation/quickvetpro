import React from 'react'
import './StatsBar.css'

function StatsBar({ stats }) {
  return (
    <div className="stats-bar">
      <div className="stat-item">
        <div className="stat-value">{stats.total_conversations || 0}</div>
        <div className="stat-label">Conversas</div>
      </div>
      <div className="stat-item active">
        <div className="stat-value">{stats.active_conversations || 0}</div>
        <div className="stat-label">Ativas</div>
      </div>
      <div className="stat-item pending">
        <div className="stat-value">{stats.pending_conversations || 0}</div>
        <div className="stat-label">Pendentes</div>
      </div>
      <div className="stat-item resolved">
        <div className="stat-value">{stats.resolved_today || 0}</div>
        <div className="stat-label">Resolvidas Hoje</div>
      </div>
      <div className="stat-item messages">
        <div className="stat-value">{stats.messages_today || 0}</div>
        <div className="stat-label">Mensagens Hoje</div>
      </div>
      <div className="stat-item users">
        <div className="stat-value">{stats.total_users || 0}</div>
        <div className="stat-label">Usuários</div>
      </div>
    </div>
  )
}

export default StatsBar
