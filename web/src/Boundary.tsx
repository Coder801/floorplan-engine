// Ошибка отрисовки листа — видимое сообщение вместо пустого холста. Сбрасывается сменой
// key (другой лист, пересборка).

import { Component, type ReactNode } from "react";
import ui from "./styles/ui.module.scss";

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
        Лист не отрисовался: {error.message}
        {"\n"}Возможно, страница устарела после обновления сервиса.
        {"\n"}<button onClick={() => location.reload()}>Обновить страницу</button>
      </div>
    );
  }
}
