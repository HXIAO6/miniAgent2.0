import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// 会话初始化有后端副作用，不在开发模式中重复挂载根组件。
createRoot(document.getElementById("root")!).render(<App />);
