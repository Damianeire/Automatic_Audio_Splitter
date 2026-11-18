import { test } from "node:test";
import assert from "node:assert/strict";
import { ProgressLog, lastLines, sessionDirs, splitRuns } from "../src/progress.ts";

test("carriage-return progress replaces itself until a newline", () => {
	const log = new ProgressLog();
	assert.deepEqual(log.feed("memo.m4a\n  scoring 10%"), ["memo.m4a"]);
	assert.equal(log.partial, "  scoring 10%");
	assert.deepEqual(log.feed("\r  scoring 50%\r  scoring 100%\n  -> /x"), ["  scoring 100%"]);
	assert.equal(log.partial, "  -> /x");
});

test("session folders come from the '  -> ' lines", () => {
	const out = "a.m4a\n  -> /Vault/Sessions/20261114 A\nb.m4a\n  -> /Vault/Sessions/20261115 B \n    -> not this\n";
	assert.deepEqual(sessionDirs(out), ["/Vault/Sessions/20261114 A", "/Vault/Sessions/20261115 B"]);
});

test("recordings share one run, each Reaper project gets its own", () => {
	assert.deepEqual(splitRuns(["/a.m4a", "/p/S.RPP", "/b.mp3"], { force: true, rescan: false }), [
		["/a.m4a", "/b.mp3", "--force", "--no-rescan"],
		["--from-reaper", "/p/S.RPP", "--force", "--no-rescan"],
	]);
	assert.deepEqual(splitRuns([], { force: false, rescan: false }), []);
});

test("last lines skip blanks", () => {
	assert.equal(lastLines("a\n\nb\n c \n\n", 2), "b\nc");
});
