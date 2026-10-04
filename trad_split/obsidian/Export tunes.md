<%*
// Cut each named tune in this session note's loops blocks into its own file
// ("yyyymmdd Tune Name.mp3") and link it from the tune's own note.
// Named tunes with no note of their own are listed first in a window: tick
// "Create note" to make a tune note for them, or "Use existing note" to rename
// the section to a note that is already there, so the export links it.
// Needs the Templater user function "export_tunes" (see trad-split README).

// ======================= pure logic (no Obsidian APIs) =======================
// Kept free of app/tp so it can be tested under node. The matching rules copy
// trad_split/export.py, so "has a note" here agrees with what the export does.
const EXPORT = (() => {
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
  function buildRows(sections, identified, notes, self = "") {
    const byKey = new Map();
    for (const n of notes) if (!byKey.has(nameKey(n.name))) byKey.set(nameKey(n.name), n);
    const rows = [];
    for (const sec of sections) {
      if (!sec.name || isPlaceholder(sec.name) || byKey.has(nameKey(sec.name))) continue;
      if (self && nameKey(sec.name) === nameKey(self)) continue;
      const found = findIdentified(sec, identified);
      const id = found ? tuneIdOf(found.url) : "";
      let row = rows.find((r) => nameKey(r.name) === nameKey(sec.name) && (!id || !r.tuneId || r.tuneId === id));
      if (!row) {
        row = { name: sec.name, sections: [], found: [], type: "", key: "", url: "", tuneId: "", candidates: [] };
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

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  return { parseTime, cleanName, isPlaceholder, nameKey, parseSections, parseListLine, parseIdentified,
    findIdentified, looseKey, looseMatch, fileNameProblem, tuneIdOf, nameProblem, buildRows, aliasFor, renameInLoops, frontmatterOf, plural };
})();
// ===================== end pure logic =====================

const { Notice, Modal, Platform, normalizePath } = tp.obsidian;
const TUNE_FOLDER = "Trad Tunes";
const TUNE_TEMPLATE = "Templates/Trad Template.md";
// Body of a new tune note: the standard sections, practice log last.
const SECTIONS = "## Recordings\n\n## Sheet Music\n\n## Practice Log\n";
const L = EXPORT;

// The window. Resolves with { mode: "apply" | "plain" | "cancel" }, and each row's
// action ("create", "existing" or "none") and chosen existing note set on the row.
const choose = (rows, notes) => new Promise((resolve) => {
  const modal = new Modal(app);
  let result = { mode: "cancel" };
  modal.titleEl.setText(`${L.plural(rows.length, "tune")} with no note`);
  modal.modalEl.style.width = "min(720px, 94vw)";
  const body = modal.contentEl;

  body.createEl("p", { text: "Tick Create note to make a tune note (change the name if you like; the section is renamed to match), or Use existing to rename the section to a note you already have. Tunes left unticked are exported without a link." })
    .style.cssText = "margin-top:0;color:var(--text-muted);";

  const bar = body.createDiv();
  bar.style.cssText = "display:flex;gap:8px;margin-bottom:8px;";
  const allBtn = bar.createEl("button", { text: "Select all" });
  const noneBtn = bar.createEl("button", { text: "Select none" });

  const list = body.createDiv();
  list.style.cssText = "max-height:55vh;overflow-y:auto;border-top:1px solid var(--background-modifier-border);";
  const status = body.createEl("p");
  status.style.cssText = "color:var(--text-muted);margin:8px 0;";
  const refreshers = [];
  const refresh = () => {
    recheck();
    refreshers.forEach((f) => f());
    const c = rows.filter((r) => r.action === "create").length;
    const e = rows.filter((r) => r.action === "existing").length;
    const parts = [];
    if (c) parts.push(`create ${L.plural(c, "note")}`);
    if (e) parts.push(`use ${L.plural(e, "existing note")}`);
    status.setText(parts.length ? `Will ${parts.join(" and ")}, then export.` : "Nothing to create; the export will run as before.");
    status.style.color = "var(--text-muted)";
  };
  // Names are checked against the vault and each other as you type.
  const recheck = () => rows.forEach((r) => { r.problem = L.nameProblem(r.newName, r, rows, notes); });

  rows.forEach((row) => {
    const item = list.createDiv();
    item.style.cssText = "padding:8px 2px;border-bottom:1px solid var(--background-modifier-border);";
    const head = item.createDiv();
    head.createEl("strong", { text: row.name });
    const details = [row.type, row.key].filter(Boolean).join(", ");
    if (details || row.url) {
      const meta = head.createSpan();
      meta.style.cssText = "color:var(--text-muted);margin-left:8px;";
      if (details) meta.appendText(details);
      if (row.url) {
        if (details) meta.appendText(" · ");
        meta.createEl("a", { text: "thesession", href: row.url });
      }
    }
    if (row.sections.length > 1) {
      const note = head.createSpan({ text: ` (played ${row.sections.length} times${row.keysDiffer ? ", in " + row.keysDiffer.join(" and ") : ""})` });
      note.style.color = row.keysDiffer ? "var(--text-warning)" : "var(--text-muted)";
    }

    const controls = item.createDiv();
    controls.style.cssText = "display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:4px;";
    const tick = (label) => {
      const lab = controls.createEl("label");
      lab.style.cssText = "display:flex;align-items:center;gap:6px;";
      const box = lab.createEl("input", { type: "checkbox" });
      lab.appendText(label);
      return { lab, box };
    };

    const create = tick("Create note as");
    const nameBox = controls.createEl("input", { type: "text", value: row.newName });
    nameBox.style.cssText = "width:min(280px,60vw);";
    const warn = controls.createSpan();
    warn.style.color = "var(--text-warning)";
    nameBox.addEventListener("input", () => {
      row.newName = nameBox.value.trim();
      if (row.action !== "create" && !L.nameProblem(row.newName, row, rows, notes)) row.action = "create";
      refresh();
    });
    create.box.addEventListener("change", () => {
      row.action = create.box.checked ? "create" : row.action === "create" ? "none" : row.action;
      refresh();
    });

    let use = null;
    if (row.candidates.length) {
      use = tick("Use existing");
      let pick;
      if (row.candidates.length === 1) {
        pick = use.lab.createEl("em", { text: `"${row.candidates[0].name}"` });
      } else {
        pick = use.lab.createEl("select");
        row.candidates.forEach((c) => pick.createEl("option", { text: c.name, value: c.name }));
        pick.value = row.existing;
        pick.addEventListener("change", () => { row.existing = pick.value; row.action = "existing"; refresh(); });
      }
      use.lab.title = row.candidates.map((c) => `${c.name}: ${c.why}`).join("\n");
      use.box.addEventListener("change", () => {
        row.action = use.box.checked ? "existing" : row.action === "existing" ? "none" : row.action;
        refresh();
      });
    }
    refreshers.push(() => {
      create.box.checked = row.action === "create";
      warn.setText(row.action === "create" && row.problem ? `That name ${row.problem}.` : "");
      if (row.newName !== row.name && !L.nameProblem(row.newName, row, rows, notes)) {
        nameBox.title = `The section is renamed to match${L.aliasFor(row) ? `; "${row.name}" is kept as an alias` : ""}.`;
      }
      if (use) use.box.checked = row.action === "existing";
    });
  });

  allBtn.addEventListener("click", () => {
    rows.forEach((r) => { if (r.action !== "existing") r.action = "create"; });
    refresh();
  });
  noneBtn.addEventListener("click", () => {
    rows.forEach((r) => { r.action = "none"; });
    refresh();
  });

  const buttons = body.createDiv();
  buttons.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:4px;";
  const done = (mode) => { result = { mode }; modal.close(); };
  buttons.createEl("button", { text: "Cancel" }).addEventListener("click", () => done("cancel"));
  buttons.createEl("button", { text: "Export without creating" }).addEventListener("click", () => done("plain"));
  const go = buttons.createEl("button", { text: "Create and export", cls: "mod-cta" });
  go.addEventListener("click", () => {
    recheck();
    const bad = rows.filter((r) => r.action === "create" && r.problem);
    if (bad.length) {
      status.setText(`Fix the name first: ${bad.map((r) => `"${r.newName}" ${r.problem}`).join("; ")}.`);
      status.style.color = "var(--text-error)";
      return;
    }
    done("apply");
  });

  refresh();
  modal.onClose = () => resolve(result);
  modal.open();
});

// Is there now a note with this name anywhere in the vault (other than the session)?
const noteExists = (name, session) => app.vault.getMarkdownFiles()
  .some((f) => f.path !== session.path && L.nameKey(f.basename) === L.nameKey(name));

try {
  if (!Platform.isDesktopApp) throw new Error("Export tunes needs Obsidian on a computer");
  await app.commands.executeCommandById("editor:save-file");
  const session = tp.config.target_file;
  const text = await app.vault.read(session);
  const notes = app.vault.getMarkdownFiles().filter((f) => f.path !== session.path).map((f) => {
    const fm = app.metadataCache.getFileCache(f)?.frontmatter || {};
    const aliases = [].concat(fm.aliases || fm.alias || []).filter((a) => typeof a === "string");
    const tags = [].concat(fm.tags || []).map((t) => String(t).replace(/^#/, ""));
    return { name: f.basename, path: f.path, aliases, tuneId: L.tuneIdOf(fm.session),
      tune: f.path.startsWith(TUNE_FOLDER + "/") || tags.includes("tradtune") };
  });
  const rows = L.buildRows(L.parseSections(text), L.parseIdentified(text), notes, session.basename);

  const done = [];
  const problems = [];
  if (rows.length) {
    const { mode } = await choose(rows, notes);
    if (mode === "cancel") { new Notice("Export cancelled. Nothing was changed."); return; }

    if (mode === "apply") {
      // Create note: the Trad Template's frontmatter, then type, key, session and alias.
      const renames = [];
      const sectionsTo = (row, to) => row.sections.forEach((sec) =>
        renames.push({ file: sec.file, start: sec.start, end: sec.end, from: row.name, to }));
      const toCreate = rows.filter((r) => r.action === "create");
      if (toCreate.length) {
        const tpl = app.vault.getAbstractFileByPath(TUNE_TEMPLATE);
        const skeleton = tpl && L.frontmatterOf(await app.vault.read(tpl));
        if (!skeleton) throw new Error(`Could not read the frontmatter of ${TUNE_TEMPLATE}`);
        if (!app.vault.getAbstractFileByPath(TUNE_FOLDER)) await app.vault.createFolder(TUNE_FOLDER);
        let made = 0;
        for (const row of toCreate) {
          if (noteExists(row.newName, session)) { problems.push(`${row.newName} already has a note, left alone`); continue; }
          let file;
          try {
            file = await app.vault.create(normalizePath(`${TUNE_FOLDER}/${row.newName}.md`), skeleton + SECTIONS);
          } catch (e) {
            problems.push(`could not create ${row.newName}: ${e.message}`);
            continue;
          }
          const alias = L.aliasFor(row);
          if (row.type || row.key || row.url || alias) {
            await app.fileManager.processFrontMatter(file, (fm) => {
              if (row.type) fm.type = row.type;
              if (row.key) fm.key = row.key;
              if (row.url) fm.session = row.url;
              if (alias) fm.aliases = [alias];
            });
          }
          if (row.newName !== row.name) sectionsTo(row, row.newName);
          made++;
        }
        if (made) done.push(`Created ${L.plural(made, "note")}`);
      }

      // Use existing, and new notes under another name: rename those sections, in the
      // session note and in any other note's loops block for the same audio, so the
      // player's blocks still agree.
      rows.filter((r) => r.action === "existing" && r.existing).forEach((r) => sectionsTo(r, r.existing));
      if (renames.length) {
        let n = 0;
        await app.vault.process(session, (t) => { const r = L.renameInLoops(t, renames); n = r.count; return r.text; });
        done.push(`renamed ${L.plural(n, "section")}`);
        const also = [];
        for (const f of app.vault.getMarkdownFiles()) {
          if (f.path === session.path) continue;
          const t = await app.vault.cachedRead(f);
          if (!t.includes("```loops") || !L.renameInLoops(t, renames).count) continue;
          await app.vault.process(f, (t2) => L.renameInLoops(t2, renames).text);
          also.push(f.basename);
        }
        if (also.length) done.push(`also renamed in ${also.join(", ")}`);
      }
    }
  }

  const out = (await tp.user.export_tunes({ note: tp.file.path() })).trim() || "Export finished";
  const head = [...done, ...problems].join("; ");
  new Notice(head ? `${head[0].toUpperCase()}${head.slice(1)}.\n${out}` : out, 15000);
} catch (e) {
  console.error("Export tunes", e);
  new Notice(`Export tunes failed: ${e.message}`, 10000);
}
-%>
