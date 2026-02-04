import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./App.css";

// Tratamento de erros global
window.addEventListener('error', (event) => {
  console.error('Erro capturado:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('Promise rejeitada:', event.reason);
});

const container = document.getElementById("root");
if (container) {
  try {
    const root = createRoot(container);
    root.render(<App />);
  } catch (error) {
    console.error("Erro ao renderizar:", error);
    container.innerHTML = `
      <div style="padding: 2rem; text-align: center; color: #fff; font-family: sans-serif;">
        <h2>Erro ao carregar a aplicação</h2>
        <p>${error.message}</p>
        <button onclick="window.location.reload()" style="padding: 0.5rem 1rem; margin-top: 1rem; cursor: pointer;">
          Recarregar
        </button>
      </div>
    `;
  }
} else {
  console.error("Elemento root não encontrado!");
  document.body.innerHTML = `
    <div style="padding: 2rem; text-align: center; color: #fff; font-family: sans-serif;">
      <h2>Erro: Elemento root não encontrado</h2>
      <p>Verifique se o HTML contém um elemento com id="root"</p>
    </div>
  `;
}
