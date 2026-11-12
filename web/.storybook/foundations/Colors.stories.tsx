// Theme colours (shared/styles/_tokens.scss): every token as a swatch with its current value.
// Switch the theme in the toolbar: the values are read from the page, so both themes show here
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";

const GROUPS: [string, [string, string][]][] = [
  ["Поверхности", [["--bg", "фон страницы"], ["--panel", "боковые панели"], ["--raise", "карточки, кнопки, поля"], ["--soft", "мягкая заливка, наведение"], ["--paper", "лист чертежа"], ["--line", "рамки и разделители"]]],
  ["Текст", [["--text", "основной"], ["--muted", "второстепенный"], ["--ink", "линии чертежа в тёмной теме"]]],
  ["Акцент", [["--accent", "главная кнопка"], ["--accent-text", "текст на акценте"], ["--hl", "выделение, фокус"], ["--hl-row", "выделенная строка"], ["--pin", "закреплённое"], ["--badge", "счётчик"]]],
  ["Состояния", [["--critical", "критично, ошибка"], ["--major", "важно, предупреждение"], ["--warn", "жёлтый знак"], ["--minor", "уточнение"], ["--ok", "готово"]]],
];

function Swatch({ name, note }: { name: string; note: string }) {
  const [value, setValue] = useState("");
  useEffect(() => {
    const read = () => setValue(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
    read();
    const watch = new MutationObserver(read);
    watch.observe(document.documentElement, { attributes: true });
    return () => watch.disconnect();
  });
  return (
    <div style={{ display: "grid", gridTemplateColumns: "48px 1fr", gap: 12, alignItems: "center" }}>
      <span style={{ width: 48, height: 48, borderRadius: 8, background: `var(${name})`, border: "1px solid var(--line)" }} />
      <span style={{ display: "grid" }}>
        <span className="mono">{name}</span>
        <span className="small muted">{note} · {value || "—"}</span>
      </span>
    </div>
  );
}

function Palette() {
  return (
    <div style={{ display: "grid", gap: 32, padding: 24 }}>
      {GROUPS.map(([title, tokens]) => (
        <section key={title} style={{ display: "grid", gap: 12 }}>
          <h4>{title}</h4>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
            {tokens.map(([n, note]) => <Swatch key={n} name={n} note={note} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

const meta = { title: "Foundations/Colors", component: Palette } satisfies Meta<typeof Palette>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = { globals: { theme: "light" } };
export const Dark: Story = { globals: { theme: "dark" } };
