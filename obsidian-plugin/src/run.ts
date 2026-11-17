// Running the installed trad-split.
import { spawn } from "child_process";
import { existsSync } from "fs";
import { homedir } from "os";
import { delimiter, join } from "path";

// Where Homebrew puts ffmpeg; Obsidian started from the Dock does not have it on PATH.
const EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin"];

/** The trad-split program: the one set in settings, else the usual places. */
export function findTradSplit(configured: string): string | null {
	const candidates = [
		configured.trim().replace(/^~(?=\/)/, homedir()),
		join(homedir(), "Code/trad-split/.venv/bin/trad-split"),
		"/opt/homebrew/bin/trad-split",
		"/usr/local/bin/trad-split",
	].filter(Boolean);
	return candidates.find((p) => existsSync(p)) ?? null;
}

export interface RunResult {
	code: number | null;
	stdout: string;
	stderr: string;
	stopped: boolean;
}

export interface Run {
	done: Promise<RunResult>;
	stop(): void;
}

/** Start trad-split with args. onOutput gets stdout and stderr as they arrive. */
export function runTradSplit(exe: string, args: string[], onOutput?: (text: string) => void): Run {
	const path = [...EXTRA_PATH, ...(process.env.PATH ?? "").split(delimiter)].filter(
		(p, i, all) => p && all.indexOf(p) === i,
	);
	const child = spawn(exe, args, {
		env: { ...process.env, PATH: path.join(delimiter), PYTHONUNBUFFERED: "1" },
	});
	let stdout = "";
	let stderr = "";
	let stopped = false;
	child.stdout.setEncoding("utf8");
	child.stderr.setEncoding("utf8");
	child.stdout.on("data", (t: string) => { stdout += t; onOutput?.(t); });
	child.stderr.on("data", (t: string) => { stderr += t; onOutput?.(t); });
	const done = new Promise<RunResult>((resolve) => {
		child.on("error", (e) => {
			stderr += `\n${e.message}\n`;
			resolve({ code: null, stdout, stderr, stopped });
		});
		child.on("close", (code) => resolve({ code, stdout, stderr, stopped }));
	});
	return {
		done,
		stop() {
			if (child.exitCode === null) {
				stopped = true;
				child.kill("SIGTERM");
			}
		},
	};
}
