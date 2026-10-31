import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Gate } from "@/pages/Gate";
import { Viewer } from "@/pages/Viewer";
import "@/shared/i18n";
import "@/shared/styles/global.scss";

createRoot(document.getElementById("root")!).render(<StrictMode><Gate>{(account) => <Viewer account={account} />}</Gate></StrictMode>);
