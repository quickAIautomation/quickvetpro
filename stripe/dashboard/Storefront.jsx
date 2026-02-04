import React, { useEffect } from "react";
import { useParams } from "react-router-dom";
import Products from "./Products";
import { useAccount } from "./AccountProvider";

const Storefront = () => {
  const { accountId: paramAccountId } = useParams();
  const { accountId, setAccountId } = useAccount();

  useEffect(() => {
    // Se veio um accountId na URL, usa ele
    if (paramAccountId && paramAccountId !== accountId) {
      setAccountId(paramAccountId);
    }
  }, [paramAccountId, accountId, setAccountId]);

  return (
    <div className="App">
      <div className="container">
        <div className="logo">
          {paramAccountId === "platform"
            ? "QuickVET | Produtos"
            : "Vitrine"}
        </div>
        <Products />
      </div>
    </div>
  );
};

export default Storefront;
