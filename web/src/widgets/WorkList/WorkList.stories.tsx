// The client's list in work order: an approved plan (one task to accept, one extra to agree) and
// a plan waiting for approval. Best seen at the phone width of the Storybook viewport
import type { Meta, StoryObj } from "@storybook/react-vite";
import { CLIENT, draftState, noRun, workState } from "@/widgets/WorkStage/mock";
import { WorkList } from ".";

const meta = {
  title: "Widgets/WorkList",
  component: WorkList,
  decorators: [(Story) => <div style={{ position: "relative", height: "100vh" }}><Story /></div>],
  args: { state: workState({ can: CLIENT, assignees: [] }), run: noRun, busy: false, open: null, onOpen: () => {} },
} satisfies Meta<typeof WorkList>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Approved: Story = {};
export const ToApprove: Story = { args: { state: draftState("proposed", CLIENT) } };
export const Dark: Story = { globals: { theme: "dark" } };
export const Ukrainian: Story = { globals: { lang: "uk" } };
