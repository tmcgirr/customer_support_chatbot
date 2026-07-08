import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import AdminApp from "./AdminApp";
import "./admin.css";

const rootElement = document.getElementById("admin-root");
if (!rootElement) {
  throw new Error("Root element #admin-root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <AdminApp />
  </StrictMode>,
);
