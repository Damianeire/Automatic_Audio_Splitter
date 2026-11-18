// Copy the built plugin into a vault: node scripts/install-plugin.mjs [vault]
// With no vault given, it uses the vault from trad-split's config file.
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

let vault = process.argv[2];
if (!vault) {
	const exe = join(homedir(), "Code/trad-split/.venv/bin/trad-split");
	try {
		vault = JSON.parse(execFileSync(exe, ["--show-options"], { encoding: "utf8" })).values.vault;
	} catch (e) {
		console.error(`Could not ask trad-split for the vault (${e.message}). Pass it: npm run install-vault -- <vault>`);
		process.exit(1);
	}
}
if (!vault || !existsSync(join(vault, ".obsidian"))) {
	console.error("Usage: node scripts/install-plugin.mjs <vault folder containing .obsidian>");
	process.exit(1);
}
const dest = join(vault, ".obsidian", "plugins", "trad-split");
mkdirSync(dest, { recursive: true });
for (const f of ["main.js", "manifest.json", "styles.css"]) copyFileSync(f, join(dest, f));
console.log(`Installed to ${dest}. In Obsidian, turn the plugin off and on (or reload) to pick it up.`);
