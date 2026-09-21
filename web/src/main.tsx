import { createRoot } from "react-dom/client";
import "./tailwind.css";
import "./base.css";
import "./extra.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(<App />);
