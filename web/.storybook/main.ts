// Storybook of the viewer: components in isolation (npm run storybook, port 6006). Stories live
// next to the component: widgets/AlphaNotice/AlphaNotice.stories.tsx. The Vite config is the
// project's own vite.config.ts (alias @/, SCSS modules, __APP_VERSION__ and __BUILD_ID__)
import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  framework: { name: "@storybook/react-vite", options: {} },
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  core: { disableTelemetry: true },
};

export default config;
