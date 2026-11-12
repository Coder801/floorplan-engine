// Card: surface and panel backgrounds, every padding step, interactive (a button card) and
// selected, content laid out inside by the grid gap
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Card } from ".";

const body = (
  <>
    <h2>Объект</h2>
    <p className="muted">Квартира 64 м², высота потолка 2700 мм</p>
    <p>Электрика: 14 групп, 52 точки. Сантехника: 9 приборов.</p>
  </>
);

const meta = {
  title: "UI/Card",
  component: Card,
  args: { children: body },
  parameters: { layout: "padded" },
  decorators: [(Story) => <div style={{ maxWidth: 480 }}><Story /></div>],
} satisfies Meta<typeof Card>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Surface: Story = {};
export const Panel: Story = { args: { variant: "panel" } };
export const Paddings: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: 16 }}>
      {(["sm", "md", "lg"] as const).map((p) => <Card key={p} {...args} padding={p}><b>padding {p}</b><span className="muted">Текст карточки</span></Card>)}
    </div>
  ),
};
export const Interactive: Story = {
  render: (args) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <Card {...args} as="button" type="button" padding="sm" interactive>
        <b>Заказчик</b><span className="small muted">Слежу за ремонтом своей квартиры</span>
      </Card>
      <Card {...args} as="button" type="button" padding="sm" interactive selected>
        <b>Студия</b><span className="small muted">Веду проекты клиентов</span>
      </Card>
    </div>
  ),
};
export const Dark: Story = { ...Interactive, globals: { theme: "dark" } };
