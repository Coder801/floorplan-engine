// Ошибка отрисовки листа — видимое сообщение вместо пустого холста. Сбрасывается сменой
// key (другой лист, пересборка).

import { Component, type ReactNode } from "react";
import i18n from "@/shared/i18n";
import ui from "@/shared/styles/ui.module.scss";

interface State { error: Error | null }

export class Boundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error(error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className={ui.error}>
        {i18n.t("boundary.failed", { message: error.message })}
        {"\n"}{i18n.t("boundary.outdated")}
        {"\n"}<button onClick={() => location.reload()}>{i18n.t("boundary.reload")}</button>
      </div>
    );
  }
}
