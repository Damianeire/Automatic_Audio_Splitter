// Export tunes' pure logic (no Obsidian APIs), tested under node in
// tests/export_template.test.mjs. The matching rules copy trad_split/export.py,
// so "has a note" here agrees with what the export does.
export const EXPORT = (() => {
  const TIME = String.raw`\d+:\d{1,2}(?:\.\d+)?`;
  const LOOP_LINE = new RegExp(String.raw`^\s*(${TIME})\s*(?:-\s*(${TIME})\s*)?\|\s*(.+?)\s*$`);
  const LIST_LINE = new RegExp(String.raw`^\s*-\s*(${TIME})\s*-\s*(${TIME})(?:\s*\(([^)]*)\))?:\s*(.+?)\s*$`);
  const BLOCK = /^```loops[ \t]*\n([\s\S]*?)^```/gm;
  const PLACEHOLDER = /^Tune \d+$/;
  const DANCES = new Set(["reel", "jig", "slip jig", "single jig", "double jig", "polka", "slide", "hornpipe",
    "barndance", "waltz", "march", "mazurka", "set dance", "single reel", "slow air", "strathspey", "three-two"]);
  const TYPE_WORDS = ["slip jig", "set dance", "single reel", "slow air", "reel", "jig", "polka", "slide",
    "hornpipe", "barndance", "barn dance", "waltz", "march", "mazurka", "strathspey"];
  const KEY = /^[A-G][b#]?(?:\s?(?:maj|min|dor|mix|lyd|phr|loc|m|major|minor|dorian|mixolydian|lydian|phrygian|locrian))?$/i;
  // Characters a file name cannot hold, or that break [[links]].
  const BAD_CHARS = /[\\/:*?"<>|#^[\]]/;

  // "1:02.5" -> 62.5
  function parseTime(s) {
    if (s == null) return null;
    const [m, sec] = String(s).split(":");
    return Number(m) * 60 + Number(sec);
  }

  // Name as the export reads it: trailing " ?" dropped, trimmed.
  const cleanName = (name) => String(name).replace(/\s*\?$/, "").trim();
  const isPlaceholder = (name) => PLACEHOLDER.test(name);
  // How Obsidian (and the export) compares names: accents by meaning, case ignored.
  const nameKey = (name) => String(name).normalize("NFC").toLowerCase();
  const pathKey = (p) => nameKey(String(p).trim().replace(/^\[\[|\]\]$/g, "").split("|")[0]);

  // Every "start - end | name" line in every loops block, with its block's file:.
  function parseSections(text) {
    const out = [];
    for (const m of text.matchAll(BLOCK)) {
      let file = null;
      for (const line of m[1].split("\n")) {
        if (line.trim().toLowerCase().startsWith("file:")) {
          file = line.split(":").slice(1).join(":").trim();
          continue;
        }
        const l = LOOP_LINE.exec(line);
        if (l && file !== null) {
          out.push({ file, startText: l[1], endText: l[2] || null,
            start: parseTime(l[1]), end: parseTime(l[2]), name: cleanName(l[3]) });
        }
      }
    }
    return out;
  }

  // One Tune Finder "Identified tunes:" line, or null.
  // "- 0:00 - 2:19.5 (Tune 1): [[Shaskeen Reel]], Reel, G ([thesession](https://...))"
  function parseListLine(line) {
    const m = LIST_LINE.exec(line);
    if (!m) return null;
    let rest = m[4];
    let url = "";
    const u = /\s*\(\[thesession\]\((https?:\/\/[^)\s]+)\)\)\s*$/.exec(rest);
    if (u) { url = u[1]; rest = rest.slice(0, u.index); }
    // Names can contain commas, so take key and type from the right.
    const parts = rest.split(",").map((s) => s.trim());
    let key = "", type = "";
    if (parts.length > 1 && KEY.test(parts[parts.length - 1])) key = parts.pop();
    if (parts.length > 1 && DANCES.has(parts[parts.length - 1].toLowerCase())) type = parts.pop();
    const shown = parts.join(", ");
    const link = /^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]$/.exec(shown);
    return { startText: m[1], endText: m[2], start: parseTime(m[1]), end: parseTime(m[2]),
      label: m[3] || "", name: link ? link[1].trim() : shown, link: link ? link[1].trim() : "", type, key, url };
  }

  const parseIdentified = (text) => text.split("\n").map(parseListLine).filter(Boolean);

  const sameTime = (aText, a, bText, b) =>
    (aText != null && aText === bText) || (a != null && b != null && Math.abs(a - b) <= 0.25);

  // The list line for a section: same start and end, as strings or within 0.25 s.
  function findIdentified(section, list) {
    return list.find((l) => sameTime(section.startText, section.start, l.startText, l.start)
      && (section.end == null || sameTime(section.endText, section.end, l.endText, l.end))) || null;
  }

  // A forgiving form of a name for spotting near misses, plus any "in <key>" on the end.
  // "The Primrose Lasses" -> primrose lass; "Hughie Travers' in G" -> hughie traver, tonic g
  function looseKey(name) {
    let s = String(name).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/['’‘`]/g, "");
    let tonic = null;
    const k = /\s+in\s+([a-g])(?:\s*(?:b|#|flat|sharp))?(?:\s*(?:maj|major|min|minor|m|dor|dorian|mix|mixolydian|lyd|lydian|phr|loc))?\s*$/.exec(s);
    if (k) { tonic = k[1]; s = s.slice(0, k.index); }
    s = s.replace(/[^a-z0-9]+/g, " ").trim().replace(/^the\s+/, "").replace(/\s+the$/, "");
    for (let again = true; again;) {
      again = false;
      for (const w of TYPE_WORDS) {
        if (s.endsWith(" " + w)) { s = s.slice(0, -w.length - 1).trim(); again = true; }
      }
    }
    const stem = (w) => (w.endsWith("sses") ? w.slice(0, -2) : w.length > 3 && /[^s]s$/.test(w) ? w.slice(0, -1) : w);
    return { base: s.split(" ").map(stem).join(" "), tonic };
  }

  function looseMatch(a, b) {
    const A = looseKey(a), B = looseKey(b);
    return A.base !== "" && A.base === B.base && (!A.tonic || !B.tonic || A.tonic === B.tonic);
  }

  // Why a section name cannot be a file name as it stands, or "".
  function fileNameProblem(name) {
    if (BAD_CHARS.test(name)) return "has characters a file name cannot hold";
    if (name.startsWith(".")) return "starts with a full stop";
    return "";
  }

  // thesession's number for a tune, from a thesession link. Two tunes with the same
  // name (Hughie Travers' in G and in A dor) only differ here.
  const tuneIdOf = (url) => (/thesession\.org\/tunes\/(\d+)/.exec(String(url || "")) || [])[1] || "";

  // Why a new note cannot be called `name`, or "". rows: the other rows in the window.
  function nameProblem(name, row, rows, notes) {
    if (!name) return "has no name";
    const bad = fileNameProblem(name);
    if (bad) return `${bad}`;
    if (notes.some((n) => nameKey(n.name) === nameKey(name))) return "is already a note";
    if (rows.some((r) => r !== row && r.action === "create" && nameKey(r.newName) === nameKey(name))) return "is ticked twice";
    return "";
  }

  // One row per named tune that has no note. notes: [{ name, path, aliases, tune, tuneId }],
  // every Markdown file in the vault except the session note itself. `tune` marks
  // tune notes, the only ones offered by the loose match; `tuneId` comes from `session:`.
  // Sections with the same name share a row unless thesession says they are different tunes.
  // self: the name of the note the export runs from. Run from a tune's own note
  // (The Castle), that tune already has its note: the one you are in.
  //
  // A section still called Tune 2 gets a row only if Tune Finder identified it: the row
  // is named after Tune Finder's name (its [[link]] if it found a note) and marked
  // `identified`, and its sections keep their own name (Tune 2) until renamed.
  function buildRows(sections, identified, notes, self = "") {
    const byKey = new Map();
    for (const n of notes) if (!byKey.has(nameKey(n.name))) byKey.set(nameKey(n.name), n);
    const rows = [];
    for (const sec of sections) {
      if (!sec.name) continue;
      const found = findIdentified(sec, identified);
      let name = sec.name;
      const fromFinder = isPlaceholder(sec.name);
      if (fromFinder) {
        name = found ? cleanName(found.link ? found.link.split("/").pop() : found.name) : "";
        if (!name || isPlaceholder(name)) continue;
      } else {
        if (byKey.has(nameKey(name))) continue;
        if (self && nameKey(name) === nameKey(self)) continue;
      }
      const id = found ? tuneIdOf(found.url) : "";
      let row = rows.find((r) => nameKey(r.name) === nameKey(name) && r.identified === fromFinder
        && (!id || !r.tuneId || r.tuneId === id));
      if (!row) {
        row = { name, identified: fromFinder, sections: [], found: [], type: "", key: "", url: "", tuneId: "",
          candidates: [] };
        rows.push(row);
      }
      row.sections.push(sec);
      if (found) {
        row.found.push(found);
        if (!row.url || (id && !row.tuneId)) Object.assign(row, { type: found.type, key: found.key, url: found.url, tuneId: id });
      }
    }
    for (const row of rows) {
      const add = (note, why) => {
        if (!row.candidates.some((c) => c.path === note.path)) row.candidates.push({ name: note.name, path: note.path, why });
      };
      // A note linked to a different thesession tune is never offered, however close the name.
      const sameTune = (n) => !row.tuneId || !n.tuneId || n.tuneId === row.tuneId;
      if (row.identified) {
        const named = byKey.get(nameKey(row.name));
        if (named && sameTune(named)) add(named, "Tune Finder named it");
        if (self && nameKey(row.name) === nameKey(self)) add({ name: self, path: "" }, "the note you ran this from");
      }
      if (row.tuneId) notes.filter((n) => n.tuneId === row.tuneId).forEach((n) => add(n, "same tune on thesession"));
      for (const f of row.found) {
        const target = f.link && byKey.get(nameKey(f.link.split("/").pop()));
        if (target && sameTune(target)) add(target, "Tune Finder linked it");
      }
      const nameLike = (n) => looseMatch(row.name, n.name)
        || (n.aliases || []).some((a) => nameKey(a) === nameKey(row.name) || looseMatch(row.name, a));
      const loose = notes.filter((n) => n.tune && sameTune(n) && nameLike(n));
      // Where several match, the one in the identified key first.
      const tonic = (row.key.match(/^[A-G]/i) || [""])[0].toLowerCase();
      loose.sort((a, b) => (looseKey(b.name).tonic === tonic) - (looseKey(a.name).tonic === tonic));
      for (const n of loose) add(n, "similar name");
      const keys = [...new Set(row.found.map((f) => f.key).filter(Boolean))];
      row.keysDiffer = keys.length > 1 ? keys : null;
      // Another tune by the same name, here or in the vault: suggest the key in the new name.
      const twin = rows.some((r) => r !== row && nameKey(r.name) === nameKey(row.name))
        || notes.some((n) => n.tune && n.tuneId && row.tuneId && n.tuneId !== row.tuneId && nameLike(n));
      const keyed = `${row.name} in ${row.key}`;
      row.newName = twin && row.key && !looseKey(row.name).tonic && !byKey.has(nameKey(keyed)) ? keyed : row.name;
    }
    for (const row of rows) {
      row.existing = row.candidates.length ? row.candidates[0].name : "";
      row.action = row.candidates.length ? "existing" : "none";
      if (!row.candidates.length && !nameProblem(row.newName, row, rows, notes)) row.action = "create";
      row.problem = nameProblem(row.newName, row, rows, notes);
    }
    return rows;
  }

  // Keep the section's own name as an alias when the new note's name only adds to it
  // ("Hughie Travers'" on "Hughie Travers' in A dor"), not when it corrects a typo.
  const aliasFor = (row) => (nameKey(row.newName) !== nameKey(row.name)
    && looseKey(row.newName).base === looseKey(row.name).base ? row.name : "");

  // Rename sections in every loops block. renames: [{ file, start, end, from, to }];
  // a line is renamed when its block's file, its times and its name all match.
  // Only the name after "|" changes. Returns { text, count }.
  function renameInLoops(text, renames) {
    let count = 0;
    const out = text.replace(BLOCK, (block) => {
      let file = null;
      return block.split("\n").map((line) => {
        if (line.trim().toLowerCase().startsWith("file:")) { file = line.split(":").slice(1).join(":").trim(); return line; }
        const l = LOOP_LINE.exec(line);
        if (!l || file === null) return line;
        const start = parseTime(l[1]), end = parseTime(l[2]);
        const r = renames.find((r) => pathKey(r.file) === pathKey(file) && nameKey(r.from) === nameKey(cleanName(l[3]))
          && Math.abs(r.start - start) <= 0.25 && ((r.end == null && end == null) || (r.end != null && end != null && Math.abs(r.end - end) <= 0.25)));
        if (!r) return line;
        count++;
        return line.slice(0, line.lastIndexOf("|") + 1) + " " + r.to;
      }).join("\n");
    });
    return { text: out, count };
  }

  // The frontmatter of the tune note template, "---" lines included.
  function frontmatterOf(text) {
    const m = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/.exec(text);
    return m ? m[0].replace(/\r?\n?$/, "\n") : null;
  }

  // ---- Naming set files after their tunes ----
  // Set files trad-split writes: "02 Set 1", "05 Set 3 - Silver Spear" (a Reaper
  // region name), or one already renamed here, "20251122 Set 1 - Kesh, Castle".
  // Any other audio file (a tune note's own recording) is never renamed.
  const SET_FILE = /^(?:(\d{8})|\d{2,3}) (Set \d+)(?: - .*)?$/;
  // Obsidian refuses these in file names, and # ^ [ ] break links.
  const NOT_IN_FILE_NAMES = /[\\/:*?"<>|#^[\]]/g;
  const MAX_SET_NAME = 80;

  function setFileParts(stem) {
    const m = SET_FILE.exec(String(stem).normalize("NFC"));
    return m ? { date: m[1] || "", set: m[2] } : null;
  }

  // yyyymmdd from a note's frontmatter `date:`, as the export reads it.
  function noteDate(text) {
    const fm = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
    const d = fm && /^date:\s*['"]?(\d{4})-(\d{2})-(\d{2})/m.exec(fm[1]);
    return d ? d[1] + d[2] + d[3] : "";
  }

  // "The Silver Spear ?" -> "Silver Spear"; "Tune 2" -> "Unnamed".
  function shortTune(name) {
    const n = cleanName(name);
    if (isPlaceholder(n)) return "Unnamed";
    return n.replace(/^the\s+/i, "").replace(NOT_IN_FILE_NAMES, "").replace(/\s+/g, " ").trim() || "Unnamed";
  }

  // "20251122 Set 1 - Silver Spear, Kesh, Lucy Farr's". When that is over max
  // characters, the last tunes become a count: "... Nightcap +2". At least one
  // tune is always kept. null when no tune in the set is named yet.
  function setFileName(date, set, names, max = MAX_SET_NAME) {
    const tunes = names.map(shortTune);
    if (!tunes.some((t) => t !== "Unnamed")) return null;
    const head = `${date} ${set} - `;
    for (let k = tunes.length; k >= 1; k--) {
      const name = head + tunes.slice(0, k).join(", ") + (k < tunes.length ? ` +${tunes.length - k}` : "");
      if (name.length <= max || k === 1) return name;
    }
  }

  // The set files a note's loops blocks point at, and the name each should have.
  // resolve(fileValue) -> { path, folder, stem, ext } or null (file not found).
  // Returns [{ from, to }] vault paths, only for files whose name changes.
  function planSetRenames(text, resolve) {
    const byPath = new Map();
    for (const sec of parseSections(text)) {
      const f = resolve(sec.file);
      if (!f) continue;
      if (!byPath.has(f.path)) byPath.set(f.path, { f, secs: [] });
      const entry = byPath.get(f.path);
      // The same file in two blocks: keep the first block's sections.
      if (!entry.secs.some((s) => Math.abs(s.start - sec.start) <= 0.25)) entry.secs.push(sec);
    }
    const date = noteDate(text);
    const out = [];
    for (const { f, secs } of byPath.values()) {
      const parts = setFileParts(f.stem);
      if (!parts) continue;
      const day = date || parts.date || (/^(\d{8})\b/.exec(f.folder.split("/").pop() || "") || [])[1] || "";
      if (!day) continue;
      secs.sort((a, b) => a.start - b.start);
      const name = setFileName(day, parts.set, secs.map((s) => s.name));
      if (!name) continue;
      const to = (f.folder ? f.folder + "/" : "") + name + (f.ext ? "." + f.ext : "");
      if (nameKey(to) !== nameKey(f.path)) out.push({ from: f.path, to });
    }
    return out;
  }

  // Every file a note refers to: loops `file:` lines and [[links]], as written.
  const WIKILINK = /(!?)\[\[([^\]|#\n]+?)(\\?)((?:[|#][^\]\n]*)?)\]\]/g;
  const unwrap = (v) => String(v).trim().replace(/^\[\[|\]\]$/g, "").split("|")[0].trim();
  function linkValues(text) {
    const values = new Set();
    for (const m of text.matchAll(BLOCK)) {
      for (const line of m[1].split("\n")) {
        if (line.trim().toLowerCase().startsWith("file:")) values.add(unwrap(line.split(":").slice(1).join(":")));
      }
    }
    for (const m of text.matchAll(WIKILINK)) values.add(m[2].trim());
    return [...values];
  }

  // Point links and loops `file:` lines at renamed files. pointsAt(value) gives
  // the vault path a value referred to before the renames; moves maps those
  // paths to new ones. Links keep their alias, heading and "!"; table links keep
  // their "\|". Returns { text, count }.
  function retargetLinks(text, pointsAt, moves) {
    let count = 0;
    const target = (value) => {
      const from = pointsAt(unwrap(value));
      return from && moves.has(from) ? moves.get(from) : null;
    };
    let out = text.replace(BLOCK, (block) => block.split("\n").map((line) => {
      if (!line.trim().toLowerCase().startsWith("file:")) return line;
      const to = target(line.split(":").slice(1).join(":"));
      if (!to) return line;
      count++;
      return line.slice(0, line.toLowerCase().indexOf("file:")) + "file: " + to;
    }).join("\n"));
    out = out.replace(WIKILINK, (all, bang, value, bs, rest) => {
      const to = target(value);
      if (!to) return all;
      count++;
      return `${bang}[[${to}${bs}${rest}]]`;
    });
    return { text: out, count };
  }

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  return { parseTime, cleanName, isPlaceholder, nameKey, parseSections, parseListLine, parseIdentified,
    findIdentified, looseKey, looseMatch, fileNameProblem, tuneIdOf, nameProblem, buildRows, aliasFor, renameInLoops, frontmatterOf,
    setFileParts, noteDate, shortTune, setFileName, planSetRenames, unwrap, linkValues, retargetLinks, plural };
})();
