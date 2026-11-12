// Spacing and radii (shared/styles/_tokens.scss): the 4px grid every gap and padding comes from,
// the radii of controls, cards and dialogs, the control heights
import type { Meta, StoryObj } from "@storybook/react-vite";

const SPACE = [1, 2, 3, 4, 5, 6, 8, 10];
const RADII: [string, string][] = [["--radius-sm", "метка"], ["--radius", "кнопка, поле"], ["--radius-md", "группа кнопок, плитка"], ["--radius-lg", "карточка"], ["--radius-xl", "диалог"]];

function Scales() {
  return (
    <div style={{ display: "grid", gap: 40, padding: 24 }}>
      <section style={{ display: "grid", gap: 12 }}>
        <h4>Отступы — сетка 4 px</h4>
        {SPACE.map((n) => (
          <div key={n} style={{ display: "grid", gridTemplateColumns: "120px 1fr", alignItems: "center", gap: 12 }}>
            <span className="mono small">--space-{n} · {n * 4}px</span>
            <span style={{ width: `var(--space-${n})`, height: 16, background: "var(--hl)", borderRadius: 2 }} />
          </div>
        ))}
      </section>
      <section style={{ display: "grid", gap: 12 }}>
        <h4>Радиусы</h4>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
          {RADII.map(([n, note]) => (
            <div key={n} style={{ display: "grid", gap: 6, justifyItems: "center" }}>
              <span style={{ width: 88, height: 64, borderRadius: `var(${n})`, background: "var(--raise)", border: "1px solid var(--line)" }} />
              <span className="mono small">{n}</span>
              <span className="small muted">{note}</span>
            </div>
          ))}
        </div>
      </section>
      <section style={{ display: "grid", gap: 12 }}>
        <h4>Высота элементов управления</h4>
        <div style={{ display: "flex", gap: 16, alignItems: "end" }}>
          {[["--control-h", "36 — компьютер"], ["--control-h-lg", "44 — палец, формы входа"]].map(([n, note]) => (
            <div key={n} style={{ display: "grid", gap: 6 }}>
              <span style={{ height: `var(${n})`, width: 160, borderRadius: 6, border: "1px dashed var(--muted)" }} />
              <span className="mono small">{n}</span><span className="small muted">{note}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

const meta = { title: "Foundations/Spacing", component: Scales } satisfies Meta<typeof Scales>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
