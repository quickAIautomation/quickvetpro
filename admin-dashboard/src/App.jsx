import React, { useState, useEffect } from 'react'
import Login from './components/Login'
import Dashboard from './components/Dashboard'
import './App.css'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [token, setToken] = useState(null)

  useEffect(() => {
    // Verificar se há token salvo
    const savedToken = localStorage.getItem('admin_token')
    if (savedToken) {
      setToken(savedToken)
      setIsAuthenticated(true)
    }
  }, [])

  const handleLogin = (newToken) => {
    setToken(newToken)
    setIsAuthenticated(true)
    localStorage.setItem('admin_token', newToken)
  }

  const handleLogout = () => {
    setToken(null)
    setIsAuthenticated(false)
    localStorage.removeItem('admin_token')
  }

  return (
    <div className="App">
      {!isAuthenticated ? (
        <Login onLogin={handleLogin} />
      ) : (
        <Dashboard token={token} onLogout={handleLogout} />
      )}
    </div>
  )
}

export default App
