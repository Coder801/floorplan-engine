import { describe, expect, it } from "vitest";
import { addUiNames, blockName } from "./uiNames.ts";

const FILE = "/web/src/widgets/SheetTabs/index.tsx";
const out = (code: string, file = FILE): string => addUiNames(code, file)?.code ?? code;

describe("имена блоков data-ui", () => {
  it("имя — папка компонента, вспомогательный компонент — Папка.Имя", () => {
    expect(blockName(FILE, "SheetTabs")).toBe("SheetTabs");
    expect(blockName(FILE, "Tab")).toBe("SheetTabs.Tab");
    expect(blockName("/web/src/main.tsx", "App")).toBe("App");
  });

  it("корень того, что компонент возвращает: function, стрелка, memo, обе ветки ?:", () => {
    const code = out(`
      export function SheetTabs() { return <nav className="x"><span>a</span></nav>; }
      const Tab = () => <button type="button">b</button>;
      const Row = memo(function Row() { return <li>c</li>; });
      function Badge({ on }) { return on ? <b>1</b> : <i>0</i>; }
    `);
    expect(code).toContain('<nav data-ui="SheetTabs" className="x"><span>a</span>');
    expect(code).toContain('<button data-ui="SheetTabs.Tab" type="button">');
    expect(code).toContain('<li data-ui="SheetTabs.Row">');
    expect(code).toContain('<b data-ui="SheetTabs.Badge">1</b> : <i data-ui="SheetTabs.Badge">0</i>');
  });

  it("фрагмент передаёт имя DOM-детям; компоненты, колбэки и переменные — без имени", () => {
    const code = out(`
      export function SheetTabs({ items }) {
        const head = <h2>t</h2>;
        if (!items.length) return <Empty />;
        return (
          <>
            <div>{items.map((i) => <p key={i}>{i}</p>)}</div>
            <Popover />
          </>
        );
      }
      function helper() { return <div>x</div>; }
    `);
    expect(code).toContain('<div data-ui="SheetTabs">');
    expect(code).toContain("<p key={i}>");
    expect(code).toContain("const head = <h2>t</h2>");
    expect(code).toContain("<Empty />");
    expect(code).toContain("<Popover />");
    expect(code).toContain("return <div>x</div>"); // lowercase: not a component
  });

  it("портал, явный data-ui в коде главнее", () => {
    const code = out(`
      export function SheetTabs() { return createPortal(<dialog open>x</dialog>, document.body); }
      function Tab() { return <a data-ui="Свой">y</a>; }
    `);
    expect(code).toContain('<dialog data-ui="SheetTabs" open>');
    expect(code).toContain('<a data-ui="Свой">');
  });

  it("в 3D (react-three-fiber) — только DOM-теги, объекты three.js не трогает", () => {
    const code = out(
      `import { Canvas } from "@react-three/fiber";
       export function Scene3D() { return <div><Canvas><Walls /></Canvas></div>; }
       function Walls() { return <group><mesh /></group>; }`,
      "/web/src/widgets/Scene3D/index.tsx",
    );
    expect(code).toContain('<div data-ui="Scene3D">');
    expect(code).toContain("<group><mesh /></group>");
  });

  it("render() классового компонента и JSX в переменной хука — по имени папки", () => {
    const code = out(
      `export class Boundary extends Component { render() { return <section>e</section>; } }
       export function useTip() { const tip = shown && <div role="tooltip">t</div>; return { tip }; }
       function Other() { const x = <span>no</span>; return <em>{x}</em>; }`,
      "/web/src/ui/Boundary/index.tsx",
    );
    expect(code).toContain('<section data-ui="Boundary">');
    expect(code).toContain('<div data-ui="Boundary" role="tooltip">');
    expect(code).toContain("const x = <span>no</span>");
    expect(code).toContain('<em data-ui="Boundary.Other">');
  });

  it("без JSX и с ошибкой разбора — без изменений", () => {
    expect(addUiNames("export const a = 1;", FILE)).toBeNull();
    expect(addUiNames("export function A() { return <div>; }", FILE)).toBeNull();
  });
});
