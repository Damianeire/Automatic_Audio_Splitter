// trad-split for Obsidian: split session recordings, add tune loops and export
// named tunes by running the trad-split installed on this Mac.
import { MarkdownView, Notice, Plugin, TFile, type TAbstractFile } from "obsidian";
import { join } from "path";
import { exportTunes } from "./export-tunes";
import { lastLines } from "./progress";
import { findTradSplit, runTradSplit, type RunResult } from "./run";
import {
	DEFAULT_SETTINGS, TradSplitSettingTab, parseOptions, vaultPath,
	type OptionsSchema, type PluginSettings,
} from "./settings";
import { SplitModal } from "./split-modal";

const AUDIO = new Set(["m4a", "mp3", "wav", "aac", "caf", "flac", "ogg", "opus", "aiff", "aif", "mp4", "webm"]);

export default class TradSplitPlugin extends Plugin {
	settings: PluginSettings = { ...DEFAULT_SETTINGS };

	async onload(): Promise<void> {
		await this.loadSettings();
		this.addSettingTab(new TradSplitSettingTab(this.app, this));

		this.addRibbonIcon("scissors", "Split a session recording", () => this.openSplit());
		this.addCommand({ id: "split-recording", name: "Split a session recording", callback: () => this.openSplit() });
		this.addCommand({
			id: "add-loops",
			name: "Add loops to this note",
			checkCallback: (checking) => this.onNote(checking, (f) => this.addLoops(f)),
		});
		this.addCommand({
			id: "export-tunes",
			name: "Export tunes from this note",
			checkCallback: (checking) => this.onNote(checking, (f) => exportTunes(this, f)),
		});

		this.registerEvent(this.app.workspace.on("file-menu", (menu, file: TAbstractFile) => {
			if (!(file instanceof TFile)) return;
			if (AUDIO.has(file.extension.toLowerCase()) || file.extension.toLowerCase() === "rpp") {
				menu.addItem((i) => i.setTitle("Split with trad-split").setIcon("scissors")
					.onClick(() => this.openSplit([this.absolute(file)])));
			} else if (file.extension === "md") {
				menu.addItem((i) => i.setTitle("Add loops").setIcon("repeat").onClick(() => this.addLoops(file)));
				menu.addItem((i) => i.setTitle("Export tunes").setIcon("music").onClick(() => exportTunes(this, file)));
			}
		}));
	}

	async loadSettings(): Promise<void> {
		this.settings = { ...DEFAULT_SETTINGS, ...(await this.loadData()) };
	}

	async saveSettings(): Promise<void> {
		await this.saveData(this.settings);
	}

	/** The trad-split program, or null with a notice saying how to fix it. */
	exe(quiet = true): string | null {
		const found = findTradSplit(this.settings.tradSplitPath);
		if (!found && !quiet) new Notice("trad-split not found. Set its path in Settings > trad-split.", 10000);
		return found;
	}

	absolute(file: TFile): string {
		return join(vaultPath(this.app) ?? "", file.path);
	}

	/** Run trad-split to the end. Throws if it can't be found. */
	async run(args: string[], onOutput?: (text: string) => void): Promise<RunResult> {
		const exe = this.exe(false);
		if (!exe) throw new Error("trad-split not found");
		return runTradSplit(exe, args, onOutput).done;
	}

	async options(): Promise<OptionsSchema> {
		const r = await this.run(["--show-options"]);
		return parseOptions(r.stdout, r.stderr, r.code);
	}

	async saveOptions(values: Record<string, unknown>): Promise<OptionsSchema> {
		const r = await this.run(["--save-options", JSON.stringify(values)]);
		return parseOptions(r.stdout, r.stderr, r.code);
	}

	/** Save any open editor of this note, so trad-split reads what is on screen. */
	async saveNote(file: TFile): Promise<void> {
		for (const leaf of this.app.workspace.getLeavesOfType("markdown")) {
			const view = leaf.view;
			if (view instanceof MarkdownView && view.file?.path === file.path) await view.save();
		}
	}

	openSplit(paths: string[] = []): void {
		if (this.exe(false)) new SplitModal(this.app, this, paths).open();
	}

	async addLoops(file: TFile): Promise<void> {
		if (!this.exe(false)) return;
		await this.saveNote(file);
		const working = new Notice(`Adding loops to ${file.basename}…`, 0);
		try {
			const r = await this.run(["--add-loops", this.absolute(file)]);
			new Notice(r.code === 0 ? r.stdout.trim() || "Add loops finished" : `Add loops failed:\n${lastLines(r.stderr)}`, 15000);
		} catch (e) {
			new Notice(`Add loops failed: ${(e as Error).message}`, 10000);
		} finally {
			working.hide();
		}
	}

	private onNote(checking: boolean, act: (f: TFile) => unknown): boolean {
		const file = this.app.workspace.getActiveFile();
		if (!file || file.extension !== "md") return false;
		if (!checking) act(file);
		return true;
	}
}
