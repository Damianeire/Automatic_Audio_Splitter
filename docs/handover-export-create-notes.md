# Handover: Export tunes creates missing tune notes, with a tick per tune

Prepared 4 October 2026 for a Claude Code session. Plan only; nothing below is built yet.

## 1. Goal

When Damian runs Export tunes on a session note, some named tunes have no tune note in the vault. Today they are only listed in the closing notice ("no tune note for: ..."), and he creates each note by hand. Instead, before exporting, show a window listing those tunes, each with a tick box, and create a proper tune note for every ticked one. Then export as now, so the new notes get their recording linked under `## Recordings`.

## 2. Where things are

| What | Path |
|---|---|
| trad-split repo (Python) | `~/Code/trad-split` (GitHub `damianeire/automatic_audio_splitter`) |
| Export logic | `trad_split/export.py` (`export_tunes`, `_tune_notes`, `_key`, `parse_note`) |
| Template, source copy | `trad_split/obsidian/Export tunes.md` |
| Template, installed copy | `<vault>/Templates/Export tunes.md` (identical today; `trad-split --setup-obsidian` copies the repo one over it) |
| Vault | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Trad Tunes Vault` (iCloud, no git; read its `CLAUDE.md` first) |
| Tune note template | `<vault>/Templates/Trad Template.md` |
| Example of a Templater modal | `<vault>/Templates/Fetch Session Dots.md` (uses `tp.obsidian.Modal`, resolves a Promise in `onClose`) |
| Wiki pages to update | `<vault>/Wiki/Guide/Session Recordings.md`, `<vault>/Wiki/Reference/Templater Setup.md` |

The template today is four lines: it calls `tp.user.export_tunes({ note: tp.file.path() })` (a Templater user system command that runs `trad-split --export-tunes "$note"`) and shows the output in a Notice.

## 3. Recommended approach: all new work in the template, none in Python

The window has to live in Obsidian, and Obsidian is also the safest thing to create notes with (`app.vault.create`, `app.fileManager.processFrontMatter`, no iCloud race with a separate process). The Python export already links recordings into any note that exists by the time it runs. So:

1. The template reads the session note, works out which named tunes have no note, shows the window.
2. It creates the ticked notes, and applies any "use existing note" choices (section 6).
3. It then calls `tp.user.export_tunes` exactly as now. The export finds the new notes and links the recordings.

No change to `export.py` is needed. Only consider one if a Python change is clearly simpler for something below; if so, keep it covered by `tests/test_export.py`.

## 4. Matching rules the template must copy exactly

So the template's "has a note" decision agrees with what the export will do:

- Sections come from every ```` ```loops ```` block in the session note. Line format: `start - end | name`, regex in `export.py` (`_LINE`). `file:` lines are not needed here.
- Name: section name with a trailing ` ?` removed and trimmed (`re.sub(r"\s*\?$", "", name)`).
- `Tune 1`, `Tune 2` (regex `^Tune \d+$`) are unnamed and skipped.
- A tune "has a note" if any Markdown file in the vault, outside `.obsidian`, `.trash`, `.git`, has a file name (stem) equal to the name after Unicode NFC normalisation and case folding (`_key`). In JS: `name.normalize("NFC").toLowerCase()` against every `app.vault.getMarkdownFiles()` basename. The session note itself does not count.
- The same tune can appear twice in one session; list it once.

## 5. Information to show for each tune

Tune Finder writes an `Identified tunes:` list under each `loops` block. Line formats seen in the vault:

```
- 0:00 - 2:19.5 (Tune 1): [[Shaskeen Reel]], Reel, G ([thesession](https://thesession.org/tunes/615#setting58147))
- 2:07.5 - 4:56: Carolan's Concerto, Reel, D ([thesession](https://thesession.org/tunes/788#setting13923))
```

Match a list line to a section by its start and end time (same strings, or numerically within 0.25 s). From it take: the identified name (a `[[link]]` means Tune Finder found an existing note), type, key and thesession URL. Names can contain commas, so parse type and key from the right. Type and key are already in the vault's forms ("Slip Jig", "A min", "E dor"). A section may have no list line (Tune Finder not run); then type, key and URL are empty.

## 6. The window

One row per tune without a note:

- the section name, with type, key and a thesession link when known;
- a choice of what to do, as a tick box plus, where relevant, a second option:
  - Create note (tick box, the feature Damian asked for);
  - Use existing note "X" instead, when a likely existing note is found (below). Choosing it renames that section in the session note's `loops` block to X's file name, so the export links the recording to X. Only the name after `|` changes; times stay as they are;
  - neither: the tune is exported but not linked, as today.
- Buttons: Create and export, Export without creating, Cancel (Cancel exports nothing).
- Select all / none is handy for a session of 20+ new tunes.

Likely existing note, in this order:

1. Tune Finder's list line for that section links a note (`[[Primrose Lass]]`) whose name differs from the section name.
2. A loose name match: compare after removing accents, apostrophes and punctuation, a leading "The", a trailing "s", and trailing type words (Reel, Jig, Polka, and so on). Check note `aliases` too.

Defaults: if a likely existing note was found, preselect Use existing and leave Create unticked; otherwise tick Create. Damian can override any row.

This matters. A dry run on 4 October across the 7 session notes found 27 named tunes without a note, and several are near misses that would become duplicates if created blindly:

| Section name | Existing note |
|---|---|
| Primrose Lasses | Primrose Lass |
| Hugh Travers' in G | Hughie Travers' in G |
| Hughie Travers' (twice, in 20261003 The Clock Tavern 19) | Hughie Travers' in G |
| Hughie Travers' in A dor | none (genuinely new, or a second note for the A setting) |

The rest of that session's list (The Moving Bog, Good Morning to Your Nightcap, The Trip to Herve's, The Duke of Leinster, The Ladies Pantalettes, I Wish I Never Saw You, The Enchanted Lady, The Holy Land, Charlie Lennon's, Joe Tom's, The Tap Room, Ríl an Spidéil, The Twelve Pins, The Road to Cashel, The Eel in the Sink, The Glen of Aherlow, Rakish Paddy, Castletown Connors, The Rookery, The Noisy Curlew) plus Lad O'Beirne's (20261003 Seamus Hawkshaw Meats) should be checked against the loose match before assuming they are new.

## 7. The note that gets created

- Path: `Trad Tunes/<section name>.md`. Same name as the section, so the export's exact match finds it.
- Contents: the Trad Template's frontmatter (copy its text exactly, it is the canonical skeleton), then set `type`, `key` (only when known) and `session:` (the thesession URL, only when known) with `app.fileManager.processFrontMatter`. Never rebuild YAML by joining strings.
- `learnt` empty, `Waitinglist: true`, `shortlist: false`, `Set:` empty: the template defaults, unchanged.
- No body is needed; the export adds `## Recordings` with the recording and a link to the session. Do not add practice dates.
- If the name contains characters a file name cannot hold (`\ / : * ? " < > |`, or `# ^ [ ]` which break links), do not offer Create for that row; say "rename the section first". A changed file name would no longer match the section, so the export would not link it.
- If a file with that name appears between the check and the create, skip it rather than overwrite.

## 8. Other rules

- Desktop only, like the export (it shells out to trad-split). Keep the existing Notice with the export summary, and prefix it with "Created N notes" when any were created.
- Save the session note before reading it (`app.commands.executeCommandById("editor:save-file")`), as Add loops does.
- Plain Irish/UK English in all UI text. No em dashes.
- Keep the pure logic (section parsing, list-line parsing, name keys, loose matching, defaults) in plain functions at the top of the template, with no Obsidian calls, so they can be unit tested under node by extracting them, as `Scripts/set-generator.js` does.

## 9. Testing

1. Unit tests for the pure functions: section parsing, ` ?` stripping, `Tune N` skipping, NFC and case matching (include "Ríl an Spidéil" stored decomposed), list-line parsing with commas in names, time matching, loose matching on the four near misses above, de-duplication.
2. A node dry run against the real session notes in the vault, printing each session's rows with their default choice. Expect the table in section 6.
3. Live in Obsidian, on a copy of a session note (duplicate `20261003 Seamus Hawkshaw Meats.md` under a new name in its own folder), with Damian: window shows Lad O'Beirne's only; ticking it creates `Trad Tunes/Lad O'Beirne's.md` with type Reel, key G and the session URL; the export links the recording under `## Recordings`; running again offers nothing and creates nothing.
4. Use existing: on a copy of `20261003 The Clock Tavern 19.md`, confirm "Hughie Travers'" offers Hughie Travers' in G, the section is renamed in the copy, and the recording lands on that note.
5. Cancel: no files created, nothing exported, session note unchanged.

## 10. Finishing

- Update both copies of the template; they must stay identical. Commit in the trad-split repo (template, any tests, README section "Exporting named tunes" which currently says no note is created). Do not push; Damian pushes.
- Update the wiki pages listed in section 2 and add a line to `Wiki/Reference/Known Issues.md` under a new "Fixed" date. Bump `updated:` on each page.
- Back up any vault file before changing it.

## 11. Gotchas from earlier sessions

- Use `git --no-optional-locks` for read-only git commands; otherwise an empty `.git/index.lock` is left behind and blocks Damian's next commit.
- Do not edit `.obsidian/plugins/templater-obsidian/data.json` while Obsidian is open; Templater writes its in-memory copy back over it. Nothing in this plan needs that file.
- Templater's template folder must stay `Templates` with no leading slash.
- Several `loops` blocks can point at the same audio file (the session note and tune notes). If a section is renamed in the session note for "Use existing", the tune notes' blocks for that file will then differ by one name, and the Audio Loop Player will say so. Either rename it in those blocks too, or list them in the summary for Damian.
