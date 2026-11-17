// Export tunes: cut each named tune in a session note's loops blocks into its own
// file ("yyyymmdd Tune Name.mp3") and link it from the tune's own note, then name
// each set file after its tunes ("yyyymmdd Set 1 - Silver Spear, Kesh.m4a").
// Named tunes with no note of their own are listed first in a window: tick
// "Create note" to make a tune note for them, or "Use existing" to rename the
// section to a note that is already there, so the export links it.
// Ported from the Templater template trad_split/obsidian/Export tunes.md.
import { App, Modal, Notice, TFile, normalizePath } from "obsidian";
import { EXPORT } from "./export-logic.js";
import type TradSplitPlugin from "./main";
import { lastLines } from "./progress";

const L: any = EXPORT;
const TUNE_FOLDER = "Trad Tunes";
const TUNE_TEMPLATE = "Templates/Trad Template.md";
// Body of a new tune note: the standard sections, practice log last.
const SECTIONS = "## Recordings\n\n## Sheet Music\n\n## Practice Log\n";

type Row = any;
type Note = { name: string; path: string; aliases: string[]; tuneId: string; tune: boolean };

// The window. Resolves with "apply" | "plain" | "cancel", with each row's action
// ("create", "existing", "none" or "skip") and chosen existing note set on the row.
function choose(app: App, rows: Row[], notes: Note[]): Promise<string> {
	return new Promise((resolve) => {
		const modal = new Modal(app);
		let result = "cancel";
		modal.titleEl.setText(rows.some((r) => r.identified) ? "Tunes to name or link" : `${L.plural(rows.length, "tune")} with no note`);
		modal.modalEl.addClass("trad-split-export");
		const body = modal.contentEl;

		body.createEl("p", {
			cls: "trad-split-muted",
			text: "Tick Create note to make a tune note (change the name if you like; the section is renamed to match), or Use existing to rename the section to a note you already have. Tunes left unticked are exported without a link."
				+ (rows.some((r) => r.identified) ? " Sections still called Tune 2 and so on are shown with the name Tune Finder gave them: left unticked, the section just takes that name; tick Leave as Tune N to keep it as it is." : ""),
		});

		const bar = body.createDiv({ cls: "trad-split-bar" });
		const allBtn = bar.createEl("button", { text: "Select all" });
		const noneBtn = bar.createEl("button", { text: "Select none" });

		const list = body.createDiv({ cls: "trad-split-rows" });
		const status = body.createEl("p", { cls: "trad-split-muted" });
		const refreshers: (() => void)[] = [];
		// Names are checked against the vault and each other as you type.
		const recheck = () => rows.forEach((r) => { r.problem = L.nameProblem(r.newName, r, rows, notes); });
		const refresh = () => {
			recheck();
			refreshers.forEach((f) => f());
			const c = rows.filter((r) => r.action === "create").length;
			const e = rows.filter((r) => r.action === "existing").length;
			const n = rows.filter((r) => r.identified && r.action === "none").length;
			const parts: string[] = [];
			if (c) parts.push(`create ${L.plural(c, "note")}`);
			if (e) parts.push(`use ${L.plural(e, "existing note")}`);
			if (n) parts.push(`name ${L.plural(n, "tune")} without a note`);
			status.setText(parts.length ? `Will ${parts.join(" and ")}, then export.` : "Nothing to create; the export will run as before.");
			status.removeClass("trad-split-error");
		};

		for (const row of rows) {
			const item = list.createDiv({ cls: "trad-split-row" });
			const head = item.createDiv();
			if (row.identified) {
				const was = [...new Set(row.sections.map((s: any) => s.name))].join(", ");
				head.createSpan({ text: `${was} → `, cls: "trad-split-muted" });
			}
			head.createEl("strong", { text: row.name });
			const details = [row.type, row.key].filter(Boolean).join(", ");
			if (details || row.url) {
				const meta = head.createSpan({ cls: "trad-split-muted trad-split-meta" });
				if (details) meta.appendText(details);
				if (row.url) {
					if (details) meta.appendText(" · ");
					meta.createEl("a", { text: "thesession", href: row.url });
				}
			}
			if (row.sections.length > 1) {
				head.createSpan({
					text: ` (played ${row.sections.length} times${row.keysDiffer ? ", in " + row.keysDiffer.join(" and ") : ""})`,
					cls: row.keysDiffer ? "trad-split-warning" : "trad-split-muted",
				});
			}

			const controls = item.createDiv({ cls: "trad-split-controls" });
			const tick = (label: string) => {
				const lab = controls.createEl("label");
				const box = lab.createEl("input", { type: "checkbox" });
				lab.appendText(label);
				return { lab, box };
			};

			const create = tick("Create note as");
			const nameBox = controls.createEl("input", { type: "text", value: row.newName, cls: "trad-split-name" });
			const warn = controls.createSpan({ cls: "trad-split-warning" });
			nameBox.addEventListener("input", () => {
				row.newName = nameBox.value.trim();
				if (row.action !== "create" && !L.nameProblem(row.newName, row, rows, notes)) row.action = "create";
				refresh();
			});
			create.box.addEventListener("change", () => {
				row.action = create.box.checked ? "create" : row.action === "create" ? "none" : row.action;
				refresh();
			});

			let use: { lab: HTMLLabelElement; box: HTMLInputElement } | null = null;
			if (row.candidates.length) {
				use = tick("Use existing");
				if (row.candidates.length === 1) {
					use.lab.createEl("em", { text: `"${row.candidates[0].name}"` });
				} else {
					const pick = use.lab.createEl("select");
					row.candidates.forEach((c: any) => pick.createEl("option", { text: c.name, value: c.name }));
					pick.value = row.existing;
					pick.addEventListener("change", () => { row.existing = pick.value; row.action = "existing"; refresh(); });
				}
				use.lab.title = row.candidates.map((c: any) => `${c.name}: ${c.why}`).join("\n");
				const box = use.box;
				box.addEventListener("change", () => {
					row.action = box.checked ? "existing" : row.action === "existing" ? "none" : row.action;
					refresh();
				});
			}
			let skip: { lab: HTMLLabelElement; box: HTMLInputElement } | null = null;
			if (row.identified) {
				skip = tick("Leave as Tune N");
				const box = skip.box;
				box.addEventListener("change", () => {
					row.action = box.checked ? "skip" : "none";
					refresh();
				});
			}
			refreshers.push(() => {
				if (skip) skip.box.checked = row.action === "skip";
				create.box.checked = row.action === "create";
				warn.setText(row.action === "create" && row.problem ? `That name ${row.problem}.` : "");
				if (row.newName !== row.name && !L.nameProblem(row.newName, row, rows, notes)) {
					nameBox.title = `The section is renamed to match${L.aliasFor(row) ? `; "${row.name}" is kept as an alias` : ""}.`;
				}
				if (use) use.box.checked = row.action === "existing";
			});
		}

		allBtn.addEventListener("click", () => {
			rows.forEach((r) => { if (r.action !== "existing") r.action = "create"; });
			refresh();
		});
		noneBtn.addEventListener("click", () => {
			rows.forEach((r) => { r.action = "none"; });
			refresh();
		});

		const buttons = body.createDiv({ cls: "trad-split-buttons" });
		const done = (mode: string) => { result = mode; modal.close(); };
		buttons.createEl("button", { text: "Cancel" }).addEventListener("click", () => done("cancel"));
		buttons.createEl("button", { text: "Export without creating" }).addEventListener("click", () => done("plain"));
		const go = buttons.createEl("button", { text: "Create and export", cls: "mod-cta" });
		go.addEventListener("click", () => {
			recheck();
			const bad = rows.filter((r) => r.action === "create" && r.problem);
			if (bad.length) {
				status.setText(`Fix the name first: ${bad.map((r) => `"${r.newName}" ${r.problem}`).join("; ")}.`);
				status.addClass("trad-split-error");
				return;
			}
			done("apply");
		});

		refresh();
		modal.onClose = () => resolve(result);
		modal.open();
	});
}

// Rename the set files this note's loops blocks play to "20251122 Set 1 - Silver
// Spear, Kesh", then point every link and loops `file:` line in the vault that
// referred to them at the new name. Obsidian does not count `file:` lines as
// links, so this does both itself instead of relying on its own link updating.
async function renameSetFiles(app: App, session: TFile): Promise<{ renamed: string[]; problems: string[] }> {
	const linkDest = (value: string, from: string) => app.metadataCache.getFirstLinkpathDest(L.unwrap(value), from);
	const text = await app.vault.read(session);
	const plan = L.planSetRenames(text, (value: string) => {
		const f = linkDest(value, session.path);
		return f && { path: f.path, folder: f.parent && f.parent.path !== "/" ? f.parent.path : "", stem: f.basename, ext: f.extension };
	});
	const renamed: string[] = [];
	const problems: string[] = [];
	for (const { from, to } of plan) {
		const file = app.vault.getAbstractFileByPath(from);
		if (!(file instanceof TFile)) continue;
		const newName = to.split("/").pop();
		if (app.vault.getAbstractFileByPath(to)) {
			problems.push(`${newName} already exists, so ${file.name} kept its name`);
			continue;
		}
		// Which notes point at this file, and with what text, worked out before it moves.
		const oldName = L.nameKey(file.name);
		const notes: { f: TFile; values: Set<string> }[] = [];
		for (const f of app.vault.getMarkdownFiles()) {
			const t = await app.vault.cachedRead(f);
			if (!L.nameKey(t).includes(oldName)) continue;
			const values = new Set<string>(L.linkValues(t).filter((v: string) => linkDest(v, f.path)?.path === from));
			if (values.size) notes.push({ f, values });
		}
		try {
			await app.vault.rename(file, to);
		} catch (e) {
			problems.push(`could not rename ${file.name}: ${(e as Error).message}`);
			continue;
		}
		const moves = new Map([[from, to]]);
		for (const { f, values } of notes) {
			await app.vault.process(f, (t) => L.retargetLinks(t, (v: string) => (values.has(v) ? from : null), moves).text);
		}
		renamed.push(newName);
	}
	return { renamed, problems };
}

export async function exportTunes(plugin: TradSplitPlugin, session: TFile): Promise<void> {
	const app = plugin.app;
	if (!plugin.exe(false)) return;
	// Is there now a note with this name anywhere in the vault (other than the session)?
	const noteExists = (name: string) => app.vault.getMarkdownFiles()
		.some((f) => f.path !== session.path && L.nameKey(f.basename) === L.nameKey(name));
	let working: Notice | null = null;
	try {
		await plugin.saveNote(session);
		const text = await app.vault.read(session);
		const notes: Note[] = app.vault.getMarkdownFiles().filter((f) => f.path !== session.path).map((f) => {
			const fm = app.metadataCache.getFileCache(f)?.frontmatter || {};
			const aliases = [].concat(fm.aliases || fm.alias || []).filter((a) => typeof a === "string");
			const tags = [].concat(fm.tags || []).map((t) => String(t).replace(/^#/, ""));
			return { name: f.basename, path: f.path, aliases, tuneId: L.tuneIdOf(fm.session),
				tune: f.path.startsWith(TUNE_FOLDER + "/") || tags.includes("tradtune") };
		});
		const rows: Row[] = L.buildRows(L.parseSections(text), L.parseIdentified(text), notes, session.basename);

		const done: string[] = [];
		const problems: string[] = [];
		if (rows.length) {
			const mode = await choose(app, rows, notes);
			if (mode === "cancel") {
				new Notice("Export cancelled. Nothing was changed.");
				return;
			}

			if (mode === "apply") {
				// Create note: the Trad Template's frontmatter, then type, key, session and alias.
				const renames: any[] = [];
				// Each section is renamed from its own name (Tune 2 for one Tune Finder named).
				const sectionsTo = (row: Row, to: string) => row.sections.forEach((sec: any) => {
					if (sec.name !== to) renames.push({ file: sec.file, start: sec.start, end: sec.end, from: sec.name, to });
				});
				const toCreate = rows.filter((r) => r.action === "create");
				if (toCreate.length) {
					const tpl = app.vault.getAbstractFileByPath(TUNE_TEMPLATE);
					const skeleton = tpl instanceof TFile && L.frontmatterOf(await app.vault.read(tpl));
					if (!skeleton) throw new Error(`Could not read the frontmatter of ${TUNE_TEMPLATE}`);
					if (!app.vault.getAbstractFileByPath(TUNE_FOLDER)) await app.vault.createFolder(TUNE_FOLDER);
					let made = 0;
					for (const row of toCreate) {
						if (noteExists(row.newName)) {
							problems.push(`${row.newName} already had a note, so that one is used`);
							sectionsTo(row, row.newName);
							continue;
						}
						let file: TFile;
						try {
							file = await app.vault.create(normalizePath(`${TUNE_FOLDER}/${row.newName}.md`), skeleton + SECTIONS);
						} catch (e) {
							problems.push(`could not create ${row.newName}: ${(e as Error).message}`);
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
						sectionsTo(row, row.newName);
						made++;
					}
					if (made) done.push(`Created ${L.plural(made, "note")}`);
				}

				// Use existing, and new notes under another name: rename those sections, in the
				// session note and in any other note's loops block for the same audio, so the
				// player's blocks still agree.
				rows.filter((r) => r.action === "existing" && r.existing).forEach((r) => sectionsTo(r, r.existing));
				// Tune Finder's name accepted without a note: rename only.
				rows.filter((r) => r.identified && r.action === "none" && r.newName).forEach((r) => sectionsTo(r, r.newName));
				if (renames.length) {
					let n = 0;
					await app.vault.process(session, (t) => { const r = L.renameInLoops(t, renames); n = r.count; return r.text; });
					done.push(`renamed ${L.plural(n, "section")}`);
					const also: string[] = [];
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

		working = new Notice(`Exporting tunes from ${session.basename}…`, 0);
		const r = await plugin.run(["--export-tunes", plugin.absolute(session)]);
		if (r.code !== 0) throw new Error(lastLines(r.stderr) || `trad-split exited with ${r.code}`);
		const out = r.stdout.trim() || "Export finished";
		const sets = await renameSetFiles(app, session);
		if (sets.renamed.length) done.push(`renamed ${L.plural(sets.renamed.length, "set file")}`);
		problems.push(...sets.problems);
		const head = [...done, ...problems].join("; ");
		new Notice(head ? `${head[0].toUpperCase()}${head.slice(1)}.\n${out}` : out, 15000);
	} catch (e) {
		console.error("Export tunes", e);
		new Notice(`Export tunes failed: ${(e as Error).message}`, 10000);
	} finally {
		working?.hide();
	}
}
