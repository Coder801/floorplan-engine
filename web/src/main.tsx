import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Gate } from "./Gate";
import "./styles/global.scss";

createRoot(document.getElementById("root")!).render(<StrictMode><Gate>{(account) => <App account={account} />}</Gate></StrictMode>);
