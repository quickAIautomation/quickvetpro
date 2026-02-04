import React from "react";
import { BrowserRouter as Router, Route, Routes } from "react-router-dom";
import Home from "./Home";
import Done from "./Done";
import AccountProvider from "./AccountProvider";
import Storefront from "./Storefront";
import "./App.css";

const App = () => {
  return (
    <div className="App">
      <AccountProvider>
        <Router>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/done" element={<Done />} />
            <Route path="/storefront/:accountId" element={<Storefront />} />
          </Routes>
        </Router>
      </AccountProvider>
    </div>
  );
};

export default App;

