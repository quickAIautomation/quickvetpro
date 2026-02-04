import React, { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";

export default function Page() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get("session_id");
  const [accountId] = useState(localStorage.getItem("accountId"));

  return (
    <div className="container">
      <div className="success-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </div>
      <p className="message">Pagamento realizado com sucesso!</p>

      <a
        href={`https://dashboard.stripe.com/${accountId}`}
        className="button"
        target="_blank"
        rel="noopener noreferrer"
      >
        Ver no Dashboard Stripe
      </a>

      <form action="/api/create-portal-session" method="POST">
        <input type="hidden" name="session_id" value={sessionId} />
        <button className="button secondary" type="submit">
          Gerenciar pagamentos
        </button>
      </form>

      <Link to="/" className="button secondary">
        ← Voltar para produtos
      </Link>
    </div>
  );
}
