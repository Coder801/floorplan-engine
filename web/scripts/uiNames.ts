// Debug names of UI blocks (web/README.md, "Имена блоков"): the root DOM element of every component
// gets data-ui="Name" at build time, so a block is found in DevTools and named in a bug report by
// its component, not by a description. Name: the component folder (pages/widgets/ui), a helper
// component of the same folder — Folder.Helper. Nothing to write by hand: the plugin reads JSX.
//
// What a component "renders" is the JSX it returns (return, arrow body, both branches of ?: and
// &&, createPortal; render() of a class component); a fragment passes the name to its DOM
// children. A hook (useTooltip) renders the JSX it keeps in a variable: named after its folder. Components (<Popover>) are
// not labelled from outside: they label their own root. An explicit data-ui in the code wins.
import MagicString from "magic-string";
import { parseSync } from "oxc-parser";
import type { Plugin } from "vite";

export const ATTR = "data-ui";

type Node = { type: string; start: number; end: number; [key: string]: unknown };

// Between the returned JSX and return / the arrow body
const THROUGH = new Set([
  "ConditionalExpression",
  "LogicalExpression",
  "ParenthesizedExpression",
  "TSAsExpression",
  "TSSatisfiesExpression",
  "TSNonNullExpression",
]);
const FUNCTIONS = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"]);
// react-three-fiber: lowercase tags there are three.js objects (<mesh>), not DOM — only these are DOM
const DOM_IN_3D = new Set(["div", "section", "span", "button", "label", "p", "ul", "li", "header", "footer"]);

const isNode = (v: unknown): v is Node => typeof v === "object" && v !== null && typeof (v as Node).type === "string";
const isComponentName = (name: unknown): name is string => typeof name === "string" && /^[A-Z]/.test(name);
const isHookName = (name: unknown): name is string => typeof name === "string" && /^use[A-Z]/.test(name);

/** Block name of a component by file: Folder for the folder's own component and its hooks,
 * Folder.Helper otherwise. */
export function blockName(file: string, component: string): string {
  const parts = file.split(/[\\/]/);
  const folder = parts.at(-2);
  if (!folder || !isComponentName(folder)) return component;
  return component === folder || isHookName(component) ? folder : `${folder}.${component}`;
}

/** Name of a function by its declaration: function Name, const Name = () =>, memo(…), render()
 * of class Name; null — not named. */
function functionName(fn: Node, parents: Node[]): string | null {
  const own = (fn.id as Node | null)?.name;
  if (typeof own === "string") return own;
  for (let i = parents.length - 1; i >= 0; i--) {
    const p = parents[i];
    if (p.type === "CallExpression") continue; // memo(…), forwardRef(…)
    if (p.type === "VariableDeclarator") {
      const name = (p.id as Node).name;
      return typeof name === "string" ? name : null;
    }
    if (p.type === "MethodDefinition" && (p.key as Node).name === "render") {
      const cls = parents[i - 2]; // MethodDefinition ← ClassBody ← class
      return (cls?.id as Node | null)?.name as string | null;
    }
    return null;
  }
  return null;
}

/** Component name of a function, or null when the function is not a component. */
function componentName(fn: Node, parents: Node[]): string | null {
  const name = functionName(fn, parents);
  return isComponentName(name) ? name : null;
}

const isPortal = (call: Node): boolean => {
  const callee = call.callee as Node;
  const name = callee.type === "MemberExpression" ? (callee.property as Node).name : callee.name;
  return name === "createPortal";
};

/** The component whose output this JSX is, or null (JSX in a variable, a callback, props). */
function owner(parents: Node[], jsx: Node): string | null {
  let child = jsx;
  for (let i = parents.length - 1; i >= 0; i--) {
    const p = parents[i];
    if (THROUGH.has(p.type)) {
      if (p.type === "ConditionalExpression" && p.test === child) return null;
    } else if (p.type === "CallExpression" && isPortal(p) && (p.arguments as Node[])[0] === child) {
      // createPortal(<div/>, …) is what the component returns
    } else if (FUNCTIONS.has(p.type) && p.body === child) {
      return componentName(p, parents.slice(0, i)); // () => <div/>
    } else if (p.type === "VariableDeclarator" && p.init === child) {
      // const tip = <div/> right in a hook's body: the hook renders it (useTooltip → Tooltip)
      const fn = parents.findLastIndex((n, k) => k < i && FUNCTIONS.has(n.type));
      const name = fn < 0 ? null : functionName(parents[fn], parents.slice(0, fn));
      return isHookName(name) && parents[i - 2]?.type === "BlockStatement" && parents[i - 3] === parents[fn] ? name : null;
    } else if (p.type === "ReturnStatement") {
      const fn = parents.findLastIndex((n, k) => k < i && FUNCTIONS.has(n.type));
      return fn < 0 ? null : componentName(parents[fn], parents.slice(0, fn));
    } else {
      return null;
    }
    child = p;
  }
  return null;
}

/** Source with data-ui on the root DOM elements of components; null — nothing to change. */
export function addUiNames(code: string, file: string): { code: string; map: ReturnType<MagicString["generateMap"]> } | null {
  if (!code.includes("<")) return null;
  const { program, errors } = parseSync(file, code, { lang: "tsx" });
  if (errors.length) return null; // the compiler will report it
  const in3d = /from\s+["']@react-three\//.test(code);
  const s = new MagicString(code);
  const label = (el: Node, name: string): void => {
    if (el.type === "JSXFragment") {
      for (const c of el.children as Node[]) label(c, name);
      return;
    }
    if (el.type !== "JSXElement") return;
    const open = el.openingElement as Node;
    const tag = open.name as Node;
    if (tag.type !== "JSXIdentifier" || typeof tag.name !== "string") return;
    if (tag.name === "Fragment") {
      for (const c of el.children as Node[]) label(c, name);
      return;
    }
    if (!/^[a-z]/.test(tag.name) || (in3d && !DOM_IN_3D.has(tag.name))) return;
    const has = (open.attributes as Node[]).some((a) => a.type === "JSXAttribute" && (a.name as Node).name === ATTR);
    if (!has) s.appendLeft(tag.end, ` ${ATTR}="${name}"`);
  };
  const walk = (node: Node, parents: Node[]): void => {
    if (node.type === "JSXElement" || node.type === "JSXFragment") {
      const component = owner(parents, node);
      if (component) label(node, blockName(file, component));
    }
    parents.push(node);
    for (const key of Object.keys(node)) {
      const v = node[key];
      if (Array.isArray(v)) v.forEach((c) => isNode(c) && walk(c, parents));
      else if (isNode(v)) walk(v, parents);
    }
    parents.pop();
  };
  walk(program as unknown as Node, []);
  return s.hasChanged() ? { code: s.toString(), map: s.generateMap({ hires: true, source: file }) } : null;
}

/** Vite plugin: dev, build, Storybook and tests alike — names are the same everywhere. */
export function uiNames(): Plugin {
  return {
    name: "ui-names",
    enforce: "pre",
    transform(code, id) {
      const file = id.split("?", 1)[0];
      if (!file.endsWith(".tsx") || file.includes("/node_modules/") || /\.(test|stories)\.tsx$/.test(file)) return null;
      return addUiNames(code, file);
    },
  };
}
