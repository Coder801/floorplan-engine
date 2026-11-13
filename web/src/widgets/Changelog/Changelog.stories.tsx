// "What's new": a few releases (newest is the current version), an empty changelog, dark and English
import type { Meta, StoryObj } from "@storybook/react-vite";
import { parseChangelog } from "@/shared/changelog";
import { APP_VERSION } from "@/shared/version";
import { Changelog } from ".";

const releases = parseChangelog(`## v${APP_VERSION} (2026-11-13)

### Feat

- **viewer**: draw an engineering grid under the sheets
- **viewer**: group the layers panel into sections with their own eye

### Fix

- **viewer**: centre the zoom rail buttons again

## v0.6.0 (2026-11-12)

### Feat

- **electrical,drawing,viewer**: route drops beside openings
`);

const meta = {
  title: "Widgets/Changelog",
  component: Changelog,
  args: { onClose: () => {}, releases },
} satisfies Meta<typeof Changelog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Empty: Story = { args: { releases: [] } };
export const Dark: Story = { globals: { theme: "dark" } };
export const English: Story = { globals: { lang: "en" } };
