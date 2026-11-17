// The Split window: pick recordings (or a Reaper project to re-cut), run
// trad-split on them with a live log, then open what it made.
import { App, Modal, Notice, Setting, TFile, TFolder, normalizePath } from "obsidian";
import { basename, relative } from "path";
import type TradSplitPlugin from "./main";
import { ProgressLog, isReaperProject, lastLines, sessionDirs, splitRuns } from "./progress";
import type { Run } from "./run";
import { runTradSplit } from "./run";
import { vaultPath } from "./settings";

/* eslint-disable @typescript-eslint/no-require-imports */
const electron = (): any => {
	try {
		return require("electron");
	} catch {
		return null;
	}
};

/** The real path of a picked or dropped file (Electron no longer sets File.path). */
function realPath(file: File): string | null {
	return electron()?.webUtils?.getPathForFile?.(file) || (file as any).path || null;
}

const PICK = "audio/*,.m4a,.mp3,.wav,.caf,.aac,.flac,.rpp,.RPP";

export class SplitModal extends Modal {
	private paths: string[];
	private force = false;
	private rescan = false;
	private run: Run | null = null;
	private running = false;
	private dirs: string[] = [];

	private listEl!: HTMLElement;
	private logEl!: HTMLElement;
	private partialEl!: HTMLElement;
	private resultEl!: HTMLElement;
	private startBtn!: HTMLButtonElement;
	private stopBtn!: HTMLButtonElement;

	constructor(app: App, private plugin: TradSplitPlugin, paths: string[]) {
		super(app);
		this.paths = [...new Set(paths)];
	}

	async onOpen(): Promise<void> {
		this.modalEl.addClass("trad-split-modal");
		this.titleEl.setText("Split a session recording");
		const { contentEl } = this;

		const drop = contentEl.createDiv({ cls: "trad-split-drop" });
		drop.createEl("p", { text: "Recordings to split, or a Reaper project (.RPP) to cut again from your edits. Drop files here or choose them." });
		this.listEl = drop.createEl("ul", { cls: "trad-split-files" });
		const picker = drop.createEl("input", { type: "file", attr: { multiple: "", accept: PICK } });
		picker.hide();
		picker.addEventListener("change", () => {
			this.add([...(picker.files ?? [])]);
			picker.value = "";
		});
		const bar = drop.createDiv({ cls: "trad-split-bar" });
		bar.createEl("button", { text: "Choose files…" }).addEventListener("click", () => picker.click());
		bar.createEl("button", { text: "Clear" }).addEventListener("click", () => {
			this.paths = [];
			this.renderList();
		});
		drop.addEventListener("dragover", (e) => {
			e.preventDefault();
			drop.addClass("is-dragover");
		});
		drop.addEventListener("dragleave", () => drop.removeClass("is-dragover"));
		drop.addEventListener("drop", (e) => {
			e.preventDefault();
			drop.removeClass("is-dragover");
			this.add([...(e.dataTransfer?.files ?? [])]);
		});
		this.renderList();

		const where = contentEl.createEl("p", { cls: "setting-item-description", text: "Reading trad-split's settings…" });
		this.plugin.options().then((o) => {
			const v = o.values;
			const out = v.output ? `Session folders go in ${v.output}` : "Session folders go next to each recording";
			const makes = [v.obsidian && "a note", v.audio && (v.sets_only ? "set files" : "set and chat files"),
				v.joined && "one mp3 of all the sets", v.reaper && "a Reaper project"].filter(Boolean).join(", ");
			where.setText(`${out}, with ${makes || "nothing (all outputs are off)"}. Change this in Settings > trad-split.`);
		}).catch((e) => where.setText(`Could not read trad-split's settings: ${e.message}`));

		new Setting(contentEl).setName("Replace an existing note and Reaper project")
			.setDesc("Off: a session split before keeps its note, with any names you typed.")
			.addToggle((t) => t.setValue(this.force).onChange((v) => (this.force = v)));
		new Setting(contentEl).setName("Analyse again").setDesc("Ignore the saved analysis of these recordings.")
			.addToggle((t) => t.setValue(this.rescan).onChange((v) => (this.rescan = v)));

		const log = contentEl.createDiv({ cls: "trad-split-log" });
		this.logEl = log.createDiv();
		this.partialEl = log.createDiv({ cls: "trad-split-partial" });
		this.resultEl = contentEl.createDiv({ cls: "trad-split-result" });

		const buttons = contentEl.createDiv({ cls: "trad-split-buttons" });
		this.stopBtn = buttons.createEl("button", { text: "Stop" });
		this.stopBtn.addEventListener("click", () => this.run?.stop());
		this.startBtn = buttons.createEl("button", { text: "Split", cls: "mod-cta" });
		this.startBtn.addEventListener("click", () => this.start());
		this.update();
	}

	onClose(): void {
		// A split keeps going if the window is closed; a notice says when it ends.
		if (this.running) new Notice("trad-split is still working. You'll get a notice when it's done.");
	}

	private add(files: File[]): void {
		const missing: string[] = [];
		for (const f of files) {
			const p = realPath(f);
			if (p) this.paths.push(p);
			else missing.push(f.name);
		}
		if (missing.length) new Notice(`Could not find where ${missing.join(", ")} is on disk.`);
		this.paths = [...new Set(this.paths)];
		this.renderList();
	}

	private renderList(): void {
		this.listEl.empty();
		if (!this.paths.length) this.listEl.createEl("li", { text: "No files yet", cls: "trad-split-empty" });
		for (const p of this.paths) {
			const li = this.listEl.createEl("li");
			li.createSpan({ text: basename(p) });
			li.createSpan({ text: isReaperProject(p) ? "  cut again from Reaper" : "", cls: "trad-split-muted" });
			li.title = p;
			const x = li.createEl("button", { text: "×", cls: "clickable-icon", attr: { "aria-label": "Remove" } });
			x.addEventListener("click", () => {
				this.paths = this.paths.filter((q) => q !== p);
				this.renderList();
			});
		}
		this.update();
	}

	private update(): void {
		if (!this.startBtn) return;
		this.startBtn.disabled = this.running || !this.paths.length;
		this.startBtn.setText(this.running ? "Working…" : "Split");
		this.stopBtn.toggle(this.running);
	}

	private line(text: string, cls?: string): void {
		this.logEl.createDiv({ text, cls });
		this.logEl.parentElement!.scrollTop = this.logEl.parentElement!.scrollHeight;
	}

	private async start(): Promise<void> {
		const exe = this.plugin.exe(false);
		if (!exe || this.running) return;
		this.running = true;
		this.dirs = [];
		this.logEl.empty();
		this.resultEl.empty();
		this.update();

		let failed = "";
		let stopped = false;
		for (const args of splitRuns(this.paths, { force: this.force, rescan: this.rescan })) {
			const progress = new ProgressLog();
			this.run = runTradSplit(exe, args, (text) => {
				for (const l of progress.feed(text)) this.line(l);
				this.partialEl.setText(progress.partial);
			});
			const r = await this.run.done;
			if (progress.partial) this.line(progress.partial);
			this.partialEl.setText("");
			this.dirs.push(...sessionDirs(r.stderr + r.stdout));
			if (r.stopped) {
				stopped = true;
				this.line("Stopped.", "trad-split-error");
				break;
			}
			if (r.code !== 0) {
				failed = lastLines(r.stderr) || `trad-split exited with ${r.code}`;
				this.line(`Failed (exit code ${r.code}).`, "trad-split-error");
				break;
			}
		}
		this.run = null;
		this.running = false;
		this.update();
		this.showResult();

		const what = this.dirs.length === 1 ? "1 session" : `${this.dirs.length} sessions`;
		if (failed) new Notice(`trad-split failed:\n${failed}`, 15000);
		else if (!stopped) {
			const n = new Notice(`trad-split finished: ${what}.${this.inVault(this.dirs[0] ?? "") ? " Click to open the note." : ""}`, 15000);
			n.noticeEl.addEventListener("click", () => this.openNote(this.dirs[0] ?? ""));
		}
	}

	/** dir relative to this vault, or null when it is outside it. */
	private inVault(dir: string): string | null {
		const root = vaultPath(this.app);
		if (!root || !dir) return null;
		const rel = relative(root, dir);
		return rel.startsWith("..") ? null : normalizePath(rel);
	}

	/** The session note trad-split wrote in dir, once Obsidian has noticed it. */
	private noteFor(dir: string): TFile | null {
		const rel = this.inVault(dir);
		const folder = rel ? this.app.vault.getAbstractFileByPath(rel) : null;
		if (!(folder instanceof TFolder)) return null;
		const notes = folder.children.filter((f): f is TFile => f instanceof TFile && f.extension === "md");
		return notes.find((f) => f.basename === basename(dir)) ?? notes[0] ?? null;
	}

	private openNote(dir: string): boolean {
		const note = this.noteFor(dir);
		if (note) this.app.workspace.getLeaf(true).openFile(note);
		else new Notice("Obsidian hasn't picked up the new note yet. Try again in a moment.");
		return Boolean(note);
	}

	private showResult(): void {
		this.resultEl.empty();
		for (const dir of this.dirs) {
			const row = this.resultEl.createDiv({ cls: "trad-split-bar" });
			row.createSpan({ text: basename(dir) });
			if (this.inVault(dir)) {
				row.createEl("button", { text: "Open note", cls: "mod-cta" }).addEventListener("click", () => {
					if (this.openNote(dir)) this.close();
				});
			}
			row.createEl("button", { text: "Show in Finder" }).addEventListener("click", () => electron()?.shell?.openPath(dir));
		}
		if (this.dirs.length && !this.dirs.some((d) => this.inVault(d))) {
			this.resultEl.createEl("p", {
				cls: "setting-item-description",
				text: "The session folders are outside this vault, so Obsidian can't open their notes. Set where they go in Settings > trad-split.",
			});
		}
	}
}
