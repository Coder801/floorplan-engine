// The client tour over a stand-in of the viewer: a header with the sheet tabs, "Questions", "?"
// and the gear, the overview and the side panel with "Set up the project" — the same data-tour
// anchors as pages/Viewer and widgets/OverviewStage. Narrow the canvas below 900 px for the card
// at the bottom, below 560 px for "⋯" instead of "Questions". "Got it", "Skip" or Esc closes it;
// the "Remount" button in the toolbar shows it again
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "@/ui/Button";
import { Heading } from "@/ui/Heading";
import { IconButton } from "@/ui/IconButton";
import { Text } from "@/ui/Text";
import { Tour } from ".";

function Stand() {
  const bar = { display: "flex", alignItems: "center", gap: 12, padding: "8px 16px", borderBottom: "1px solid var(--line)", background: "var(--panel)" };
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr", height: "100vh" }}>
      <header style={bar}>
        <b>kv42</b>
        <nav data-tour="sheets" style={{ display: "flex", gap: 12, flex: 1, overflow: "auto" }}>
          <span>Общие сведения</span><span>План</span><span>Электрика</span><span>Сантехника</span><span>Смета</span>
        </nav>
        <Button data-tour="questions">Вопросы 3</Button>
        <IconButton variant="framed" label="Как пользоваться" data-tour="help">?</IconButton>
        <IconButton variant="framed" label="Ещё" data-tour="questions-menu">⋯</IconButton>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px" }}>
        <main data-tour="overview" style={{ padding: 24, display: "grid", alignContent: "start", gap: 12 }}>
          <Heading level={1}>Общие сведения</Heading>
          <Text tone="muted">Квартира 42</Text>
          <Button variant="primary" data-tour="setup-page">Настроить проект</Button>
        </main>
        <aside style={{ padding: 16, borderLeft: "1px solid var(--line)", display: "grid", alignContent: "end" }}>
          <Button size="lg" block data-tour="setup">Настроить проект</Button>
        </aside>
      </div>
    </div>
  );
}

const meta = {
  title: "Widgets/Tour",
  component: Tour,
  parameters: { layout: "fullscreen" },
  args: {
    facts: { sheets: true, canAnswer: true, openQuestions: 3, canChoose: true, setupTotal: 4 },
    onClose: () => {},
  },
  render: (args) => <><Stand /><Tour {...args} /></>,
} satisfies Meta<typeof Tour>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

// A client without questions and without the right to choose: three steps
export const Short: Story = { args: { facts: { sheets: true, canAnswer: false, openQuestions: 0, canChoose: false, setupTotal: 0 } } };

export const Dark: Story = { globals: { theme: "dark" } };

export const Phone: Story = { globals: { viewport: { value: "mobile1" } } };

export const Ukrainian: Story = { globals: { lang: "uk" } };

export const English: Story = { globals: { lang: "en" } };
