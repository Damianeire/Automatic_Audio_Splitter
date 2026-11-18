// Reading trad-split's output. No Obsidian APIs, so it is tested under node.

/**
 * Turns process output into log lines. Progress lines start with a carriage
 * return and replace each other, so they are held as the unfinished last line
 * until a newline commits them. Same as ProgressLog in trad_split/gui_options.py.
 */
export class ProgressLog {
	partial = "";

	/** Add output; return the lines it completed. this.partial is the line in progress. */
	feed(text: string): string[] {
		const done: string[] = [];
		for (const piece of text.split(/(\r|\n)/)) {
			if (piece === "\n") {
				done.push(this.partial);
				this.partial = "";
			} else if (piece === "\r") {
				this.partial = "";
			} else {
				this.partial += piece;
			}
		}
		return done;
	}
}

/** Session folders a run reported with its "  -> <dir>" lines. */
export function sessionDirs(output: string): string[] {
	return [...output.matchAll(/^ {2}-> (.+?)\s*$/gm)].map((m) => m[1]);
}

/** The last few non-empty lines, for an error notice. */
export function lastLines(text: string, n = 3): string {
	return text.split("\n").map((l) => l.trim()).filter(Boolean).slice(-n).join("\n");
}

/** What trad-split does with a file: re-cut a Reaper project, or split a recording. */
export function isReaperProject(path: string): boolean {
	return /\.rpp$/i.test(path);
}

/**
 * trad-split runs for these files: all recordings in one run (the model is
 * loaded once), then one run per Reaper project. force and rescan are passed
 * either way so the run does what the window shows, whatever the config says.
 */
export function splitRuns(paths: string[], opts: { force: boolean; rescan: boolean }): string[][] {
	const flags = [opts.force ? "--force" : "--no-force", opts.rescan ? "--rescan" : "--no-rescan"];
	const memos = paths.filter((p) => !isReaperProject(p));
	const runs = memos.length ? [[...memos, ...flags]] : [];
	for (const rpp of paths.filter(isReaperProject)) runs.push(["--from-reaper", rpp, ...flags]);
	return runs;
}
