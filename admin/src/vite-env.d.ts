/// <reference types="vite/client" />
declare module "*.module.scss" {
  const styles: Readonly<Record<string, string>>;
  export default styles;
}
