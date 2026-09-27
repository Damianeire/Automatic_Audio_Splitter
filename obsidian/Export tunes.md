<%*
// Cut each named tune in this session note's loops blocks into its own file
// ("yyyymmdd Tune Name.mp3") and link it from the tune's own note.
// Needs the Templater user function "export_tunes" (see trad-split README).
const out = await tp.user.export_tunes({ note: tp.file.path() });
new Notice(out.trim() || "Export finished", 15000);
-%>
