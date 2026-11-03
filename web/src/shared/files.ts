// Source file kind by extension: how to show it (SourceView) and label it (Drawer)

const KIND: [RegExp, string][] = [[/\.pdf$/i, "pdf"], [/\.(png|jpe?g|webp|gif)$/i, "image"], [/\.(md|txt|ya?ml|csv)$/i, "text"]];
export const kindOf = (f: string) => (KIND.find(([re]) => re.test(f)) || [null, "file"])[1];
