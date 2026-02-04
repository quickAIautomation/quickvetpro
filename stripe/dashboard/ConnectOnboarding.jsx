import React, { useState } from "react";
import { useAccount } from "./AccountProvider";
import AccountStatus from "./AccountStatus";

const ConnectOnboarding = () => {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { accountId, setAccountId } = useAccount();

  // URL do Checkout (página de planos)
  const CHECKOUT_URL = "http://localhost:3001";

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      // Verifica se o email já existe no banco (veio do Stripe após pagamento)
      const response = await fetch("/api/login-by-email", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (response.ok && data.account_id) {
        // Email encontrado - conta existe (cliente já pagou)
        setAccountId(data.account_id);
        // Salvar email também para referência
        localStorage.setItem("userEmail", email);
      } else if (response.status === 404) {
        // Email não encontrado - redirecionar para Checkout
        setError("Email não encontrado. Redirecionando para página de planos...");
        setTimeout(() => {
          window.location.href = CHECKOUT_URL;
        }, 2000);
      } else {
        throw new Error(data.detail || "Erro ao verificar email");
      }
    } catch (error) {
      console.error("Erro ao fazer login:", error);
      setError("Erro ao verificar email. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  const handleGoToCheckout = () => {
    window.location.href = CHECKOUT_URL;
  };

  return (
    <div className="container">
      {!accountId ? (
        <>
          <form onSubmit={handleLogin}>
            <div className="form-group">
              <label htmlFor="email">E-mail usado na assinatura:</label>
              <input
                type="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="contato@suaclinica.com.br"
                required
                disabled={loading}
              />
            </div>
            {error && <p className="error-message">{error}</p>}
            <button className="button" type="submit" disabled={loading}>
              {loading ? "Verificando..." : "Acessar Dashboard"}
            </button>
          </form>
          <div className="divider">
            <span>ou</span>
          </div>
          <button 
            className="button secondary" 
            onClick={handleGoToCheckout}
            disabled={loading}
          >
            Ainda não sou assinante - Ver Planos
          </button>
        </>
      ) : (
        <AccountStatus />
      )}
    </div>
  );
};

export default ConnectOnboarding;
