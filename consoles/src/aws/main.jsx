import "@cloudscape-design/global-styles/index.css";
import { createRoot } from "react-dom/client";
import { NotifyProvider } from "../common/notify.jsx";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <NotifyProvider>
    <App />
  </NotifyProvider>,
);
