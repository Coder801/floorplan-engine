// Dialog: a confirmation, a form (Esc and the veil close it), a blocking wait that cannot be
// closed, the small and large widths. On a narrow viewport (the Storybook viewport toolbar) the
// card is a sheet at the bottom
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type ReactNode } from "react";
import { Modal } from ".";

const buttons = (close: () => void) => (
  <div style={{ display: "flex", gap: 8 }}>
    <button onClick={close} style={{ minHeight: 36, padding: "0 12px", borderRadius: 6, background: "var(--accent)", color: "var(--accent-text)" }}>Принять</button>
    <button onClick={close} style={{ minHeight: 36, padding: "0 12px", borderRadius: 6, border: "1px solid var(--line)" }}>Отмена</button>
  </div>
);

// The story opens the dialog and gives a button to open it again
function Demo({ children, ...props }: Omit<Parameters<typeof Modal>[0], "children"> & { children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button onClick={() => setOpen(true)} style={{ minHeight: 36, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 6 }}>Открыть</button>
      {open && <Modal {...props} onClose={props.onClose === undefined ? undefined : () => setOpen(false)}>{children(() => setOpen(false))}</Modal>}
    </>
  );
}

const meta = {
  title: "UI/Modal",
  component: Modal,
  args: { children: null, onClose: () => {}, labelledBy: "modal-title" },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Modal>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Confirm: Story = {
  render: (args) => (
    <Demo {...args} size="sm">
      {(close) => (
        <>
          <h2 id="modal-title">Как клиент подтвердил?</h2>
          <p className="muted">Студия принимает работу за клиента — отметьте канал подтверждения.</p>
          {buttons(close)}
        </>
      )}
    </Demo>
  ),
};
export const Form: Story = {
  render: (args) => (
    <Demo {...args}>
      {(close) => (
        <>
          <h2 id="modal-title">Оставить отзыв</h2>
          <p className="muted">Ошибка, идея или вопрос по сервису. Esc или клик мимо — закрыть.</p>
          <textarea rows={4} style={{ padding: 8, border: "1px solid var(--line)", borderRadius: 6, background: "var(--paper)" }} />
          {buttons(close)}
        </>
      )}
    </Demo>
  ),
};
export const Blocking: Story = {
  args: { onClose: undefined, role: "alertdialog", busy: true },
  render: (args) => (
    <Demo {...args} size="sm">
      {() => (
        <div style={{ display: "grid", justifyItems: "center", gap: 8, textAlign: "center" }}>
          <b id="modal-title">Пересчитываю смету…</b>
          <span className="small muted">Закрыть нельзя: окно уйдёт само, когда сборка закончится.</span>
        </div>
      )}
    </Demo>
  ),
};
export const Large: Story = {
  render: (args) => (
    <Demo {...args} size="lg">
      {(close) => (<><h2 id="modal-title">Широкий диалог</h2><p>720 px: таблица или два столбца.</p>{buttons(close)}</>)}
    </Demo>
  ),
};
export const Dark: Story = { ...Form, globals: { theme: "dark" } };
