// Buttons: every variant and size, states (disabled, pressed toggle, with an icon, a link that looks
// like a button, the full width). Hover and keyboard focus are live: point at or Tab to a button
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button, type ButtonSize, type ButtonVariant } from ".";

const VARIANTS: ButtonVariant[] = ["default", "primary", "bare", "link", "danger"];
const SIZES: ButtonSize[] = ["sm", "md", "lg"];
const row = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 } as const;

const Plus = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>;

const meta = {
  title: "UI/Button",
  component: Button,
  args: { children: "Сохранить" },
  argTypes: {
    variant: { control: "inline-radio", options: VARIANTS },
    size: { control: "inline-radio", options: SIZES },
  },
  parameters: { layout: "padded" },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Primary: Story = { args: { variant: "primary" } };

export const Variants: Story = {
  render: (args) => <div style={row}>{VARIANTS.map((v) => <Button key={v} {...args} variant={v}>{v}</Button>)}</div>,
};

export const Sizes: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: 16 }}>
      {(["default", "primary"] as const).map((v) => (
        <div key={v} style={row}>{SIZES.map((s) => <Button key={s} {...args} variant={v} size={s}>{`${v} · ${s}`}</Button>)}</div>
      ))}
    </div>
  ),
};

export const Disabled: Story = {
  render: () => <div style={row}>{VARIANTS.map((v) => <Button key={v} variant={v} disabled>{v}</Button>)}</div>,
};

// A toggle: pressed is the accent fill and aria-pressed
export const Pressed: Story = {
  render: (args) => (
    <div style={row}>
      <Button {...args} variant="bare" pressed>3D</Button>
      <Button {...args} variant="bare" pressed={false}>3D</Button>
      <Button {...args} pressed>Изометрия</Button>
    </div>
  ),
};

export const WithIcon: Story = { args: { icon: <Plus />, children: "Добавить задачу" } };
export const AsLink: Story = { args: { href: "#", variant: "primary", children: "Скачать Excel" } };
export const Block: Story = { args: { block: true, size: "lg", variant: "primary", children: "Войти" }, parameters: { layout: "padded" } };
export const LinkInText: Story = {
  render: (args) => <p style={{ maxWidth: 360 }}>Есть вопросы к проекту? <Button {...args} variant="link">Оставьте отзыв</Button> — ответим в течение дня.</p>,
};
export const Dark: Story = { ...Variants, globals: { theme: "dark" } };
