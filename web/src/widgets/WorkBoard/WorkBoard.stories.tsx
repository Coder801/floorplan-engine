// The studio's board: an approved plan with tasks in every status, a draft from the estimate and
// the installer's view (no plan buttons). Writes do nothing here (mock.noRun)
import type { Meta, StoryObj } from "@storybook/react-vite";
import { draftState, INSTALLER, noRun, workState } from "@/widgets/WorkStage/mock";
import { WorkBoard } from ".";

const meta = {
  title: "Widgets/WorkBoard",
  component: WorkBoard,
  decorators: [(Story) => <div style={{ position: "relative", height: "100vh" }}><Story /></div>],
  args: { state: workState(), run: noRun, busy: false, open: null, onOpen: () => {} },
} satisfies Meta<typeof WorkBoard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Approved: Story = {};
export const Dark: Story = { globals: { theme: "dark" } };
export const Draft: Story = { args: { state: draftState("draft") } };
export const Installer: Story = { args: { state: workState({ can: INSTALLER, assignees: [] }), open: "cable" } };
export const English: Story = { globals: { lang: "en" } };
