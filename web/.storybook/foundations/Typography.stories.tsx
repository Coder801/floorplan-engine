// Typography and vertical rhythm. The scale: every role with its size / line-height (multiples of
// 4px). The rhythm: a real block (page title, lead, section, paragraphs, buttons) laid out only
// by Stack gaps — the baseline grid behind it shows that every line falls on the 4px grid
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading, type HeadingSize } from "@/ui/Heading";
import { Stack } from "@/ui/Stack";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";

const HEADINGS: [HeadingSize, string][] = [
  ["display", "display · 32/40 · 600"], ["title", "title · 22/28 · 500 · h1"], ["heading", "heading · 16/24 · 600 · h2"],
  ["subheading", "subheading · 14/20 · 600 · h3"], ["caps", "caps · 11/16 · 600 · h4"],
];
const TEXTS = [["lead", "lead · 16/24"], ["body", "body · 14/20"], ["small", "small · 12/16"], ["caps", "caps · 11/16"]] as const;

function Scale() {
  return (
    <Stack gap={8} style={{ padding: 24, maxWidth: 720 }}>
      <Stack gap={4}>
        <Heading level={2} size="caps">Заголовки</Heading>
        {HEADINGS.map(([size, note]) => (
          <Stack key={size} gap={1}>
            <Heading level={3} size={size}>Знаем, что в стене</Heading>
            <Text size="small" tone="muted" mono>{note}</Text>
          </Stack>
        ))}
      </Stack>
      <Stack gap={4}>
        <Heading level={2} size="caps">Текст</Heading>
        {TEXTS.map(([size, note]) => (
          <Stack key={size} gap={1}>
            <Text size={size}>Розетка у окна на 300 мм от пола, кабель по стене вверх до распределительной коробки.</Text>
            <Text size="small" tone="muted" mono>{note}</Text>
          </Stack>
        ))}
      </Stack>
    </Stack>
  );
}

const grid = {
  backgroundImage: "linear-gradient(to bottom, color-mix(in srgb, var(--hl) 18%, transparent) 1px, transparent 1px)",
  backgroundSize: "100% 4px",
};

function Rhythm({ baseline }: { baseline: boolean }) {
  return (
    <div style={{ padding: 24, ...(baseline ? grid : {}) }}>
      <Stack gap={6} style={{ maxWidth: 640 }}>
        <Stack gap={2}>
          <Heading level={1}>Смета электрики</Heading>
          <Text size="lead" tone="muted">Квартира 64 м², 14 групп, 52 точки. Цены студии на ноябрь.</Text>
        </Stack>
        <Card>
          <Stack gap={1}>
            <Heading level={2}>Штробление <Tag variant="outline">как в проекте</Tag></Heading>
            <Text size="small" tone="muted">Бетон, глубина 25 мм</Text>
          </Stack>
          <Text>Штробы под кабель и подрозетники по всем стенам, кроме санузла. В цену входит вывоз мусора до контейнера.</Text>
          <Text>Итого 186 м штроб и 52 подрозетника.</Text>
          <Stack direction="row" gap={2}>
            <Button variant="primary">Принять</Button>
            <Button>Вернуть с комментарием</Button>
          </Stack>
        </Card>
        <Stack gap={3}>
          <Heading level={2} size="caps">Что дальше</Heading>
          <Text>Студия согласует смету с вами, затем монтажники получат план работ по задачам.</Text>
        </Stack>
      </Stack>
    </div>
  );
}

const meta = { title: "Foundations/Typography", component: Scale } satisfies Meta<typeof Scale>;
export default meta;
type Story = StoryObj<typeof meta>;

export const TypeScale: Story = {};
export const VerticalRhythm: Story = { render: () => <Rhythm baseline={false} /> };
export const BaselineGrid: Story = { render: () => <Rhythm baseline /> };
export const Dark: Story = { render: () => <Rhythm baseline={false} />, globals: { theme: "dark" } };
