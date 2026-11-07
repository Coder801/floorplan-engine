// Source files of a project next to what was parsed from them (intake.yaml, sources)

export interface ParsedSource { file: string; note: string }

export interface SourceRow {
  file: string;
  used: boolean | null; // null: an old server without parsed, parsing status is unknown
  note: string;
  exists: boolean;
}

// macOS keeps file names decomposed (NFD), intake.yaml is written composed (NFC): the same name
// differs as a string in й, ї, є, so names are compared in one form. file stays as on disk: the
// link to the file needs exactly that spelling.
const same = (name: string) => name.normalize("NFC");

export function sourceRows(sources: string[], parsed?: ParsedSource[]): SourceRow[] {
  const notes = new Map((parsed || []).map((s) => [same(s.file), s]));
  const onDisk = new Set(sources.map(same));
  const rows: SourceRow[] = [...new Set(sources)].map((file) => {
    const hit = notes.get(same(file));
    return { file, used: parsed ? hit !== undefined : null, note: hit?.note || "", exists: true };
  });
  const missing = [...notes.values()].filter((s) => !onDisk.has(same(s.file)));
  return [...rows, ...missing.map((s) => ({ file: s.file, used: true, note: s.note, exists: false }))];
}
