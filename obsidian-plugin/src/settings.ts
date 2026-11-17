// Settings tab: where trad-split is, and trad-split's own defaults, which live in
// its config file so the window app, the Finder action and Terminal share them.
import { App, FileSystemAdapter, Notice, PluginSettingTab, Setting } from "obsidian";
import type TradSplitPlugin from "./main";
import { lastLines } from "./progress";

export interface PluginSettings {
	tradSplitPath: string;
}

export const DEFAULT_SETTINGS: PluginSettings = { tradSplitPath: "" };

type Value = string | number | boolean | null;

export interface OptionsSchema {
	config: string;
	bools: { key: string; label: string; tip: string; per_run: boolean }[];
	numbers: { key: string; label: string; min: number; max: number; step: number; decimals: number }[];
	folders: { key: string; label: string }[];
	choices: Record<string, string[]>;
	values: Record<string, Value>;
}

// Shown in the Split window rather than saved.
const OUTPUT_ORDER = ["obsidian", "audio", "sets_only", "tunes", "joined", "apple_music", "reaper", "plot", "reencode"];

export function vaultPath(app: App): string | null {
	const adapter = app.vault.adapter;
	return adapter instanceof FileSystemAdapter ? adapter.getBasePath() : null;
}

export class TradSplitSettingTab extends PluginSettingTab {
	constructor(app: App, private plugin: TradSplitPlugin) {
		super(app, plugin);
	}

	async display(): Promise<void> {
		const { containerEl } = this;
		containerEl.empty();

		const found = this.plugin.exe();
		new Setting(containerEl)
			.setName("trad-split program")
			.setDesc(found ? `Using ${found}` : "Not found. Give the full path to trad-split.")
			.addText((t) => t
				.setPlaceholder("~/Code/trad-split/.venv/bin/trad-split")
				.setValue(this.plugin.settings.tradSplitPath)
				.onChange(async (v) => {
					this.plugin.settings.tradSplitPath = v.trim();
					await this.plugin.saveSettings();
				}))
			.addButton((b) => b.setButtonText("Check").onClick(() => this.display()));
		if (!found) return;

		let schema: OptionsSchema;
		try {
			schema = await this.plugin.options();
		} catch (e) {
			containerEl.createEl("p", { text: `Could not read trad-split's settings: ${(e as Error).message}`, cls: "trad-split-error" });
			return;
		}

		containerEl.createEl("p", {
			text: `These are trad-split's defaults, saved in ${schema.config}. The trad-split window and Terminal use them too.`,
			cls: "setting-item-description",
		});
		const values = schema.values;
		const save = async (key: string, value: Value) => {
			try {
				const next = await this.plugin.saveOptions({ [key]: value });
				Object.assign(values, next.values);
			} catch (e) {
				new Notice(`Not saved: ${(e as Error).message}`, 10000);
				this.display();
			}
		};

		new Setting(containerEl).setName("Where things go").setHeading();
		const here = vaultPath(this.app);
		for (const f of schema.folders) {
			const s = new Setting(containerEl).setName(f.label);
			if (f.key === "output") s.setDesc("Each recording gets a session folder in here. Empty: next to the recording.");
			if (f.key === "vault" && here && values.vault !== here) {
				s.setDesc(values.vault ? "This is not the vault you have open." : "Not set, so links in new notes may not work.");
				s.addButton((b) => b.setButtonText("Use this vault").onClick(async () => {
					await save("vault", here);
					this.display();
				}));
			}
			s.addText((t) => {
				t.setValue(String(values[f.key] ?? "")).inputEl.addClass("trad-split-path");
				t.inputEl.addEventListener("change", () => save(f.key, t.getValue().trim() || null));
			});
		}

		new Setting(containerEl).setName("What a split makes").setHeading();
		const bools = new Map(schema.bools.map((b) => [b.key, b]));
		const order = [...OUTPUT_ORDER.filter((k) => bools.has(k)), ...[...bools.keys()].filter((k) => !OUTPUT_ORDER.includes(k))];
		for (const key of order) {
			const b = bools.get(key)!;
			if (b.per_run) continue;
			new Setting(containerEl)
				.setName(b.label)
				.setDesc(key === "obsidian" ? "A session note with a player and tune loops for each set." : b.tip)
				.addToggle((t) => t.setValue(Boolean(values[key])).onChange((v) => save(key, v)));
		}

		new Setting(containerEl).setName("Exported tunes").setHeading();
		new Setting(containerEl)
			.setName("Tune file format")
			.addDropdown((d) => {
				for (const c of schema.choices.tune_format ?? []) d.addOption(c, c);
				d.setValue(String(values.tune_format)).onChange((v) => save("tune_format", v));
			});

		new Setting(containerEl).setName("Detection").setHeading()
			.setDesc("How sets and tunes are found. The defaults suit most sessions.");
		for (const n of schema.numbers) {
			new Setting(containerEl)
				.setName(n.label)
				.setDesc(`${n.min} to ${n.max}`)
				.addText((t) => {
					t.inputEl.type = "number";
					t.inputEl.min = String(n.min);
					t.inputEl.max = String(n.max);
					t.inputEl.step = String(n.step);
					t.setValue(String(values[n.key]));
					t.inputEl.addEventListener("change", () => {
						const v = Number(t.getValue());
						if (t.getValue().trim() === "" || Number.isNaN(v) || v < n.min || v > n.max) {
							new Notice(`${n.label} must be between ${n.min} and ${n.max}.`);
							t.setValue(String(values[n.key]));
							return;
						}
						save(n.key, v);
					});
				});
		}
	}
}

/** Parse trad-split's JSON output, or explain why not. */
export function parseOptions(stdout: string, stderr: string, code: number | null): OptionsSchema {
	if (code !== 0) throw new Error(lastLines(stderr) || `trad-split exited with ${code}`);
	try {
		return JSON.parse(stdout) as OptionsSchema;
	} catch {
		throw new Error("trad-split did not print its options. Is it up to date (it needs --show-options)?");
	}
}
