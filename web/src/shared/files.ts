// Вид файла исходника по расширению: как его показать (SourceView) и подписать (Drawer)

const KIND: [RegExp, string][] = [[/\.pdf$/i, "pdf"], [/\.(png|jpe?g|webp|gif)$/i, "image"], [/\.(md|txt|ya?ml|csv)$/i, "text"]];
export const kindOf = (f: string) => (KIND.find(([re]) => re.test(f)) || [null, "file"])[1];
