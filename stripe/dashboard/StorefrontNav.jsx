import React from "react";
import { Link } from "react-router-dom";
import { useAccount } from "./AccountProvider";

const StorefrontNav = () => {
  const { accountId } = useAccount();

  if (!accountId) return null;

  return (
    <div className="container">
      <div style={{ marginTop: "10px" }}>
        <Link
          key={accountId}
          to={`/storefront/${accountId}`}
          className="button secondary"
          style={{ marginTop: "5px" }}
        >
          Ver Vitrine Pública
        </Link>
      </div>
    </div>
  );
};

export default StorefrontNav;
