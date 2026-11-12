// Choice cards in a fieldset: one chosen, a disabled one, without a description
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { RadioCard } from ".";

const KINDS = [
  { value: "studio", title: "Дизайн-студия", description: "Проекты для клиентов, своя команда монтажа" },
  { value: "installer", title: "Монтажная бригада", description: "Работаем по чужим проектам" },
  { value: "solo", title: "Частный мастер", description: "Один человек, небольшие объекты" },
];

const meta = {
  title: "UI/RadioCard",
  component: RadioCard,
  args: { name: "kind", value: "studio", checked: true, onChange: () => {}, title: KINDS[0].title, description: KINDS[0].description },
  parameters: { layout: "padded" },
} satisfies Meta<typeof RadioCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { render: (args) => <div style={{ maxWidth: 280 }}><RadioCard {...args} /></div> };
export const Group: Story = {
  render: function Render() {
    const [kind, setKind] = useState("studio");
    return (
      <fieldset style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, maxWidth: 560, margin: 0, padding: 0, border: 0 }}>
        <legend className="small muted" style={{ marginBottom: 4 }}>Кто вы</legend>
        {KINDS.map((k) => <RadioCard key={k.value} name="kind" {...k} checked={kind === k.value} onChange={setKind} />)}
        <RadioCard name="kind" value="other" title="Другое" checked={kind === "other"} onChange={setKind} disabled />
      </fieldset>
    );
  },
};
export const Dark: Story = { ...Group, globals: { theme: "dark" } };
