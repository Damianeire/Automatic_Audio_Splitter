<%*
// Detect tune changes in each audio file embedded in this note and add a
// loops block under it for the audio-loop-player plugin. Embeds that
// already have a loops block are left alone.
// Needs the Templater user function "add_loops" (see trad-split README).
await app.commands.executeCommandById("editor:save-file");
const out = await tp.user.add_loops({ note: tp.file.path() });
new Notice(out.trim() || "Add loops finished", 15000);
-%>
