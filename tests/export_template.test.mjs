// Tests for the pure logic at the top of the Export tunes template.
// Run with: node --test tests/  (tests/test_export_template.py runs it under pytest)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const TEMPLATE = fileURLToPath(new URL("../trad_split/obsidian/Export tunes.md", import.meta.url));
const source = readFileSync(TEMPLATE, "utf8");

export function loadLogic(text = source) {
  const start = text.indexOf("const EXPORT = ");
  const end = text.indexOf("// ===================== end pure logic");
  return new Function(`${text.slice(start, end)}\nreturn EXPORT;`)();
}
const E = loadLogic();

test("the whole template parses as JavaScript", () => {
  const body = source.slice(source.indexOf("<%*") + 3, source.lastIndexOf("-%>"));
  const AsyncFunction = (async () => {}).constructor;
  assert.doesNotThrow(() => new AsyncFunction("tp", "app", body));
});

const SESSION = `---
type: session
---
## Set 1
\`\`\`loops
file: Sessions/S/01 Set 1.m4a
select: 2
0:00 - 1:43 | Geese in the Bog
1:43 - 2:31.5 | Lad O'Beirne's ?
2:31.5 - 6:55.5 | Tune 2
6:55.5 - 8:00 | Tune 3 ?
\`\`\`
Identified tunes:
- 0:00 - 1:43: [[Geese in the Bog]], Jig, A min ([thesession](https://thesession.org/tunes/43#setting24277))
- 1:43.1 - 2:31.6: Lad O'Beirne's, Reel, G ([thesession](https://thesession.org/tunes/406#setting53618))

## Set 2
\`\`\`loops
file: Sessions/S/03 Set 2.m4a
0:00 - 1:40 | Ríl an Spidéil
1:40 - 3:00 | Lad O'Beirne's
\`\`\`
\`\`\`loops
0:00 - 1:00 | No file line
\`\`\`
`;

test("sections: every loops block, ' ?' stripped, lines without a file: ignored", () => {
  const s = E.parseSections(SESSION);
  assert.deepEqual(s.map((x) => x.name), ["Geese in the Bog", "Lad O'Beirne's", "Tune 2", "Tune 3",
    "Ríl an Spidéil", "Lad O'Beirne's"]);
  assert.equal(s[1].file, "Sessions/S/01 Set 1.m4a");
  assert.equal(s[1].start, 103);
  assert.equal(s[1].end, 151.5);
  assert.equal(E.isPlaceholder("Tune 2"), true);
  assert.equal(E.isPlaceholder("Tune 2 Reel"), false);
});

test("list lines: commas in names, link, type and key from the right, label", () => {
  const a = E.parseListLine("- 0:00 - 2:19.5 (Tune 1): [[Shaskeen Reel]], Reel, G ([thesession](https://thesession.org/tunes/615#setting58147))");
  assert.equal(a.link, "Shaskeen Reel");
  assert.equal(a.label, "Tune 1");
  assert.deepEqual([a.type, a.key, a.url], ["Reel", "G", "https://thesession.org/tunes/615#setting58147"]);
  const b = E.parseListLine("- 2:07.5 - 4:56: Farewell, My Love, Slip Jig, E dor ([thesession](https://thesession.org/tunes/1#setting2))");
  assert.deepEqual([b.name, b.link, b.type, b.key, b.end], ["Farewell, My Love", "", "Slip Jig", "E dor", 296]);
  const c = E.parseListLine("- 1:00 - 2:00 (Tune 4 ?): [[Hughie Travers' in A|Hughie]], Reel ([thesession](https://thesession.org/tunes/3#setting3))");
  assert.deepEqual([c.link, c.type, c.key], ["Hughie Travers' in A", "Reel", ""]);
  assert.equal(E.parseListLine("- 20250101"), null);
  assert.equal(E.parseListLine("0:00 - 1:43 | Geese in the Bog"), null);
});

test("time matching: same strings or within 0.25 s", () => {
  const list = E.parseIdentified(SESSION);
  const [, lad] = E.parseSections(SESSION);
  assert.equal(E.findIdentified(lad, list).name, "Lad O'Beirne's");
  assert.equal(E.findIdentified({ startText: "1:43", start: 103, endText: "2:32", end: 152 }, list), null);
});

const note = (name, extra = {}) => ({ name, path: `Trad Tunes/${name}.md`, aliases: [], tune: true, ...extra });

test("rows: named tunes with no note, once each, NFC and case matching", () => {
  const notes = [note("Geese in the Bog"), note("ríl an spidéil")];
  const rows = E.buildRows(E.parseSections(SESSION), E.parseIdentified(SESSION), notes);
  assert.deepEqual(rows.map((r) => r.name), ["Lad O'Beirne's"]);
  const [lad] = rows;
  assert.equal(lad.sections.length, 2);
  assert.deepEqual([lad.type, lad.key, lad.url], ["Reel", "G", "https://thesession.org/tunes/406#setting53618"]);
  assert.equal(lad.action, "create");
  assert.deepEqual(lad.candidates, []);
});

test("rows: a note that only matches the session note itself does not count", () => {
  // buildRows is given every note except the session, so a section named like it is listed.
  const text = "```loops\nfile: a.m4a\n0:00 - 1:00 | My Session\n```\n";
  assert.equal(E.buildRows(E.parseSections(text), [], []).length, 1);
});

test("loose matching on the near misses", () => {
  assert.equal(E.looseMatch("Primrose Lasses", "Primrose Lass"), true);
  assert.equal(E.looseMatch("Hughie Travers'", "Hughie Travers' in G"), true);
  assert.equal(E.looseMatch("Hughie Travers' in A dor", "Hughie Travers' in G"), false);
  assert.equal(E.looseMatch("Hugh Travers' in G", "Hughie Travers' in G"), false); // Tune Finder's link catches this one
  assert.equal(E.looseMatch("The Cooley's Reel", "Cooley’s"), true);
  assert.equal(E.looseMatch("Ríl an Spidéil", "Ril an Spideil"), true);
  assert.equal(E.looseMatch("The Moving Bog", "The Moving Cloud"), false);
});

test("candidates: Tune Finder's link first, then loose matches and aliases; defaults", () => {
  const text = [
    "```loops", "file: Sessions/X/12 Set 6.m4a",
    "0:00 - 1:32.5 | Primrose Lasses",
    "5:29 - 7:04.5 | Hugh Travers' in G",
    "7:04.5 - 8:48.5 | Hughie Travers' in A dor",
    "8:48.5 - 9:00 | Hughie Travers'",
    "9:00 - 9:30 | Frieze Breeches",
    "9:30 - 9:40 | Bad: Name",
    "```",
    "Identified tunes:",
    "- 0:00 - 1:32.5 (Primrose Lasses): [[Primrose Lass]], Reel, G ([thesession](https://thesession.org/tunes/789#setting44185))",
    "- 5:29 - 7:04.5 (Tune 3 ?): [[Hughie Travers' in G]], Reel, G ([thesession](https://thesession.org/tunes/1518#setting1518))",
    "- 7:04.5 - 8:48.5 (Tune 4 ?): [[Hughie Travers' in A]], Reel, A dor ([thesession](https://thesession.org/tunes/3996#setting3996))",
  ].join("\n");
  const notes = [note("Primrose Lass"), note("Hughie Travers' in G"), note("Hughie Travers' in D"),
    note("The Humours of Ennistymon", { aliases: ["The Frieze Breeches"] }),
    { name: "Primrose Lasses notes", path: "Wiki/x.md", aliases: [], tune: false }];
  const rows = Object.fromEntries(E.buildRows(E.parseSections(text), E.parseIdentified(text), notes).map((r) => [r.name, r]));
  const pick = (r) => [r.action, r.existing, r.candidates.map((c) => c.name)];
  assert.deepEqual(pick(rows["Primrose Lasses"]), ["existing", "Primrose Lass", ["Primrose Lass"]]);
  assert.deepEqual(pick(rows["Hugh Travers' in G"]), ["existing", "Hughie Travers' in G", ["Hughie Travers' in G"]]);
  assert.deepEqual(pick(rows["Hughie Travers' in A dor"]), ["create", "", []]);
  assert.deepEqual(pick(rows["Hughie Travers'"]), ["existing", "Hughie Travers' in G", ["Hughie Travers' in G", "Hughie Travers' in D"]]);
  assert.deepEqual(pick(rows["Frieze Breeches"]), ["existing", "The Humours of Ennistymon", ["The Humours of Ennistymon"]]);
  assert.deepEqual([rows["Bad: Name"].action, rows["Bad: Name"].problem], ["none", "has characters a file name cannot hold"]);
});

test("identified key decides between several loose matches", () => {
  const text = "```loops\nfile: a.m4a\n0:00 - 1:00 | Hughie Travers'\n```\n"
    + "- 0:00 - 1:00: Hughie Travers', Reel, D ([thesession](https://thesession.org/tunes/1#setting1))\n";
  const [row] = E.buildRows(E.parseSections(text), E.parseIdentified(text), [note("Hughie Travers' in G"), note("Hughie Travers' in D")]);
  assert.equal(row.existing, "Hughie Travers' in D");
});

// Clock Tavern 19: two different tunes both called Hughie Travers'.
const TWINS = "```loops\nfile: Sessions/C/10 Set 5.m4a\n5:12 - 6:59 | Hughie Travers'\n6:59 - 8:53 | Hughie Travers'\n9:00 - 9:30 | The Moving Bog\n9:30 - 9:40 | The Moving Bog\n```\n"
  + "Identified tunes:\n"
  + "- 5:12 - 6:59: Hughie Travers', Reel, G ([thesession](https://thesession.org/tunes/1518#setting1518))\n"
  + "- 6:59 - 8:53: Hughie Travers', Reel, A dor ([thesession](https://thesession.org/tunes/3996#setting3996))\n"
  + "- 9:00 - 9:30: The Moving Bog, Reel, G ([thesession](https://thesession.org/tunes/1012#setting40012))\n";

test("same name, different thesession tunes: two rows, matched by number", () => {
  const notes = [note("Hughie Travers' in G", { tuneId: "1518" })];
  const rows = E.buildRows(E.parseSections(TWINS), E.parseIdentified(TWINS), notes);
  assert.deepEqual(rows.map((r) => [r.name, r.tuneId, r.sections.length]),
    [["Hughie Travers'", "1518", 1], ["Hughie Travers'", "3996", 1], ["The Moving Bog", "1012", 2]]);
  const [g, a, bog] = rows;
  assert.deepEqual([g.action, g.existing, g.candidates[0].why], ["existing", "Hughie Travers' in G", "same tune on thesession"]);
  assert.equal(g.newName, "Hughie Travers'"); // "in G" is taken by the note it matches
  // The A dor one is never offered the G note, and gets the key in its suggested name.
  assert.deepEqual([a.action, a.candidates, a.newName, a.problem], ["create", [], "Hughie Travers' in A dor", ""]);
  assert.equal(E.aliasFor(a), "Hughie Travers'");
  assert.deepEqual([bog.action, bog.newName], ["create", "The Moving Bog"]);
  assert.equal(E.aliasFor(bog), "");
});

test("a note linked to a different tune is not offered, even by Tune Finder's link", () => {
  const text = "```loops\nfile: a.m4a\n0:00 - 1:00 | Primrose Lasses\n```\n"
    + "- 0:00 - 1:00: [[Primrose Lass]], Reel, G ([thesession](https://thesession.org/tunes/2#setting2))\n";
  const [row] = E.buildRows(E.parseSections(text), E.parseIdentified(text), [note("Primrose Lass", { tuneId: "789" })]);
  assert.deepEqual([row.action, row.candidates, row.newName], ["create", [], "Primrose Lasses in G"]);
});

test("a note with the same thesession number is offered whatever its name", () => {
  const text = "```loops\nfile: a.m4a\n0:00 - 1:00 | Boy in the Boat\n```\n"
    + "- 0:00 - 1:00: Boy in the Boat, Reel, D ([thesession](https://thesession.org/tunes/975#setting1))\n";
  const [row] = E.buildRows(E.parseSections(text), E.parseIdentified(text), [note("An tSeanbhean Bhocht", { tuneId: "975" })]);
  assert.deepEqual([row.action, row.existing], ["existing", "An tSeanbhean Bhocht"]);
});

test("name problems: bad characters, an existing note, the same name ticked twice", () => {
  const notes = [note("Primrose Lass")];
  const r1 = { newName: "X", action: "create" }, r2 = { newName: "x", action: "create" };
  assert.equal(E.nameProblem("", r1, [r1], notes), "has no name");
  assert.equal(E.nameProblem("A: B", r1, [r1], notes), "has characters a file name cannot hold");
  assert.equal(E.nameProblem("primrose lass", r1, [r1], notes), "is already a note");
  assert.equal(E.nameProblem("X", r1, [r1, r2], notes), "is ticked twice");
  assert.equal(E.nameProblem("X", r1, [r1], notes), "");
  const text = "```loops\nfile: a.m4a\n0:00 - 1:00 | Bad: Name\n```\n";
  assert.deepEqual(E.buildRows(E.parseSections(text), [], []).map((r) => r.action), ["none"]);
});

test("alias only when the new name adds to the section name", () => {
  assert.equal(E.aliasFor({ name: "Hughie Travers'", newName: "Hughie Travers' in A dor" }), "Hughie Travers'");
  assert.equal(E.aliasFor({ name: "Lad O'Bierne's", newName: "Lad O'Beirne's" }), "");
  assert.equal(E.aliasFor({ name: "X", newName: "X" }), "");
});

test("thesession numbers", () => {
  assert.equal(E.tuneIdOf("https://thesession.org/tunes/1518#setting1518"), "1518");
  assert.equal(E.tuneIdOf(null), "");
  assert.equal(E.tuneIdOf("https://example.com"), "");
});

test("file name problems", () => {
  for (const bad of ["A/B", "A: B", "Why?", 'Say "hi"', "A#1", "A^b", "[x]", "a|b", "a\\b", "a*b", "<a>", ".hidden"]) {
    assert.ok(E.fileNameProblem(bad), bad);
  }
  assert.equal(E.fileNameProblem("Lad O'Beirne's"), "");
  assert.equal(E.fileNameProblem("Ríl an Spidéil (No. 2)"), "");
});

test("renaming: only the name after |, only matching file, times and name", () => {
  const text = [
    "intro | Primrose Lasses",
    "```loops", "file: Sessions/X/01 Set 1.m4a", "select: 1",
    "0:00 - 1:32.5 | Primrose Lasses ?",
    "1:32.5 - 2:59 | Primrose Lasses",
    "```",
    "```loops", "file: [[Sessions/X/02 Set 2.m4a]]",
    "0:00 - 1:32.5 | Primrose Lasses",
    "```",
  ].join("\n");
  const renames = [{ file: "Sessions/X/01 Set 1.m4a", start: 0, end: 92.5, from: "Primrose Lasses", to: "Primrose Lass" },
    { file: "Sessions/X/02 Set 2.m4a", start: 0, end: 92.6, from: "primrose lasses", to: "Primrose Lass" }];
  const { text: out, count } = E.renameInLoops(text, renames);
  assert.equal(count, 2);
  assert.deepEqual(out.split("\n"), [
    "intro | Primrose Lasses",
    "```loops", "file: Sessions/X/01 Set 1.m4a", "select: 1",
    "0:00 - 1:32.5 | Primrose Lass",
    "1:32.5 - 2:59 | Primrose Lasses",
    "```",
    "```loops", "file: [[Sessions/X/02 Set 2.m4a]]",
    "0:00 - 1:32.5 | Primrose Lass",
    "```",
  ]);
  assert.equal(E.renameInLoops(text, []).text, text);
});

test("frontmatter of the tune template, without its Templater block", () => {
  const tpl = "---\ntags:\n  - tradtune\ntype:\nWaitinglist: true\n---\n<%*\nawait tp.file.move('x');\n-%>\n";
  assert.equal(E.frontmatterOf(tpl), "---\ntags:\n  - tradtune\ntype:\nWaitinglist: true\n---\n");
  assert.equal(E.frontmatterOf("no frontmatter"), null);
});
