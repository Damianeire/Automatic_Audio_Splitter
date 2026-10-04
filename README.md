# trad-split

Splits a recording of a trad session (for example an iPhone Voice Memo) into the sets of tunes and the chat between them.

For each memo it can produce:

- Audio files: `01 Chat 1.m4a`, `02 Set 1.m4a`, `03 Chat 2.m4a` and so on, tagged with the album `yyyymmdd <memo name>`. By default they are cut with stream copy, so it is fast and there is no quality loss. `--sets-only` skips the chat.
- A Reaper project, `<memo>.RPP`. It has the memo on one track and a coloured region for each segment, so you can check the boundaries, drag them, rename regions, and cut again from your edits.
- A regions CSV in the same format as Reaper's Region/Marker Manager.
- An Obsidian note with YAML frontmatter, one section per set with an embedded player, and `tunes::` / `notes::` Dataview fields for you to fill in.
- A plot of the detection scores, for tuning.

## How it works

1. ffmpeg decodes the memo to 32 kHz mono.
2. [PANNs](https://github.com/qiuqiangkong/panns_inference) (Cnn14_DecisionLevelMax) is a neural network trained on Google's AudioSet. It scores every 10 ms against 527 sound classes. These are pooled to half-second frames and split into two groups:
   - music: Music, Folk music, Traditional music, fiddle, banjo, mandolin, guitar, flute, whistle, accordion, bagpipes, harmonica, piano, drum, singing
   - chat: speech, conversation, laughter, chatter, crowd, hubbub, clapping, cheering

   The per-frame score is `log(music) - log(chat)`.
3. A two-state Viterbi pass smooths the scores. Changing state has a cost, so someone talking over a tune, or a quiet bar, does not split a set.
4. Any set under 40 s is folded into the chat around it, which catches tuning up and noodling. Any chat under 4 s is folded into the sets around it.
5. Each set starts 1.5 s early and runs 3.5 s past the last note, so the first notes and the applause are kept.

The model scores are cached in `~/Library/Caches/trad-split/`, keyed on the memo file. Re-running with different tuning settings or a different output folder therefore takes seconds. If you move, rename or edit the memo, it is analysed again.

### Tune changes within sets

Sets are not split at tune changes, but the changes are marked:

- **Chapters** are embedded in each set file, so Music, QuickTime, VLC and most players can skip from tune to tune.
- **The Obsidian note** gets a `loops` block under each set for the audio-loop-player plugin. Times are relative to the set file:

  ````
  ```loops
  file: Sessions/20251122 The Clock Tavern 22/02 Set 1.m4a
  0:00 - 2:20 | Tune 1
  2:18 - 4:34.3 | Tune 2 ?
  ```
  ````

- **Reaper markers** are placed inside each set region, named `Tune 2`, `Tune 3` and so on.

How it works: a tune is played round two or three times, so after its first round the music keeps matching what was heard a minute earlier. A new tune breaks that pattern. This means it works even when two tunes share a key and rhythm. It can miss a change if a tune is played only once. A name ending in `?` marks a weak detection. Weak ones are kept rather than dropped: in real sessions most turn out to be real changes, often into a tune played loosely, so check them by ear and delete any that aren't (`--tune-sensitivity 0.6` leaves out the weakest).

Correcting in Reaper: move, delete or add markers, and rename them with the tune names. A marker at the very start of a set names the first tune. Then re-cut with `--from-reaper`, and the names carry through to the chapters and the note.

Changes are found a second or two early. That makes a good lead-in for the next tune, but would clip the end of the one before, so each tune's section runs 2 s past the change into the next (Tune 1 above ends at 2:20, Tune 2 starts at 2:18). Exported tunes get the same 2 s, including from blocks written before this was added. Set `tune_tail` in the config file to change it; `0` ends each tune exactly at the change.

Settings: `--min-tune` (default 60 s) and `--tune-sensitivity` (default 1; higher finds more). Use `--no-tunes` to turn detection off. With `--plot`, detected changes show as dashed lines.

### Adding loops to any note

The loops blocks don't have to come from a session split. `--add-loops` works on any note: every embedded audio file (`![[Ballina reels.m4a]]`) that has no `loops` block under it is treated as one set, its tune changes are detected, and a block is inserted on the line below the embed:

````
![[Ballina reels.m4a]]
```loops
file: Sound Files/Ballina reels.m4a
0:00 - 2:20 | Tune 1
2:18 - 4:34.3 | Tune 2 ?
```
````

Embeds that already have a `loops` block are left alone, so you can add a new recording to a note and run it again without losing the names you typed. `--redo-loops` replaces existing blocks too, names and all. `--min-tune` and `--tune-sensitivity` apply as usual, and the analysis is cached, so a redo with a different sensitivity takes a second.

```sh
trad-split --add-loops "path/to/Practice.md"
```

From Obsidian it is the "Add loops" command, which `--setup-obsidian` installs alongside Export tunes (see below). It saves the note first, then writes the blocks; Obsidian picks up the change. Detection takes a few seconds per set file the first time.

### Exporting named tunes

Once the tune names and boundaries in a session note's `loops` blocks are right, one command cuts each named tune into its own file. The set files are left as they are. Each tune file:

- is named `yyyymmdd Tune Name.mp3`, for example `20251122 The Silver Spear.mp3`. The date comes from the note's `date:`;
- goes into your sound files folder. That is the `tunes_folder` setting if you set one; otherwise Obsidian's attachment folder (Settings > Files and links); otherwise `Sound Files`;
- gets a link in the vault note with the same name as the tune (e.g. `The Silver Spear.md`), added under a `## Recordings` heading as `- ![[20251122 The Silver Spear.mp3]] from [[20251122 The Clock Tavern 22]]`. The heading is created if the note doesn't have one. You can also run it from a tune's own note: run from `The Castle.md` on a recording with three tunes, The Castle's recording goes under that note's own `## Recordings` (as `- ![[20251122 The Castle.mp3]]`, with no "from"), and the other two go to their notes as usual, linked back to The Castle.

Sections still called `Tune 2` and so on are skipped until you name them, unless you use `--all`. A trailing `?` is dropped from names. If the same tune comes up twice in one session, the second file gets ` (2)`. Files that already exist are left alone, so running it again is safe; use `--force` to replace them. From Terminal, tunes with no note of their own are listed in the summary, and no note is created for them. From Obsidian, the Export tunes template lists those tunes in a window first: tick Create note to make `Trad Tunes/<Tune Name>.md` from your `Templates/Trad Template.md` (with type, key and the thesession link from Tune Finder's Identified tunes list), or Use existing to rename the section to a near-matching note you already have (for example Primrose Lasses to Primrose Lass). Notes are matched on the thesession tune number first (Tune Finder's link against each note's `session:`), so two different tunes with the same name, like the two Hughie Travers', are kept apart; the new note's name can be edited, and when another tune has the same name the key is suggested in it ("Hughie Travers' in A dor") with the plain name kept as an alias. The export then links the recording into those notes. Export without creating runs the export as before; Cancel does nothing.

Set files that are already mp3 are copied without re-encoding. m4a set files are converted to mp3 (LAME VBR, about 190 kbps, a second or two per tune). Set `tune_format = "m4a"` to keep them as m4a.

From Terminal:

```sh
trad-split --export-tunes "path/to/20251122 The Clock Tavern 22.md"
```

From Obsidian, with Templater (install it from Community plugins first). Quit Obsidian, then run:

```sh
trad-split --setup-obsidian
```

This uses the `vault` from your config file, or pass `--vault`. It does the following:
- copies the Export tunes and Add loops templates into Templater's templates folder;
- turns on Templater's user system command functions;
- adds `export_tunes` and `add_loops` functions that run this install of trad-split;
- raises the command timeout to 120 s;
- registers both templates so they can have hotkeys.

It backs up Templater's settings first. It refuses to run while Obsidian is open, because Templater would write its old settings back over the changes. Running it again is safe.

To give them hotkeys, reopen Obsidian and go to Settings > Hotkeys, search for "Export tunes" and "Add loops" and assign keys. If you set up Export tunes before Add loops existed, run `--setup-obsidian` again to add it.

If you'd rather set it up by hand:
1. Copy `trad_split/obsidian/Export tunes.md` and `trad_split/obsidian/Add loops.md` into your Templater templates folder.
2. In Settings > Templater, turn on User system command functions and set Timeout to 120 seconds.
3. Add a function named `export_tunes` with the command `"$HOME/Code/trad-split/.venv/bin/trad-split" --export-tunes "$note"`, and one named `add_loops` with `"$HOME/Code/trad-split/.venv/bin/trad-split" --add-loops "$note"`.

To use it, open a session note and press your hotkey, or run "Templater: Insert Export tunes" from the command palette. Nothing is inserted into the note. A notice shows the result, for example `Exported 5 tunes; linked 3; no tune note for: The Mason's Apron.`

## Setup (Mac)

```sh
brew install ffmpeg python@3.12
git clone https://github.com/damianeire/automatic_audio_splitter.git ~/Code/trad-split
cd ~/Code/trad-split
python3.12 -m venv .venv
.venv/bin/pip install -e .
ln -s ~/Code/trad-split/.venv/bin/trad-split "$(brew --prefix)/bin/trad-split"   # puts it on your PATH
```

The first run downloads the model, about 320 MB, into `~/panns_data/`. If you use the python.org installer instead of Homebrew's Python and the download fails with a certificate error, run `Install Certificates.command` from `/Applications/Python 3.x/`.

## Use

```sh
trad-split "~/Desktop/Ballina Friday.m4a"          # one memo
trad-split ~/Desktop/Sessions/                      # every memo in a folder
trad-split memo.m4a --plot                          # also save the score plot
trad-split memo.m4a -o ~/Music/Sessions             # choose where session folders go
```

Each memo gets its own session folder, placed next to the memo unless you give `-o`. The folder is named with the recording date followed by the memo name, for example `20251122 The Clock Tavern 22`, so sessions sort in date order. Names that already start with a date are left alone. The project, CSV, note and plot inside the folder use the same name, and so does the album tag. The folder holds the audio files, the `.RPP`, the CSV, and the note and plot if you asked for them.

### Checking and correcting in Reaper

1. Open `<memo>.RPP`. Sets are green regions and chat is grey.
2. Drag region edges to fix boundaries. Rename a region to rename its file: `Set 3 - Silver Spear, Mason's Apron` becomes `05 Set 3 - Silver Spear, Mason's Apron.m4a`. A region whose name starts with `Chat` is treated as chat, and every other region as a set. You can delete regions you do not want exported.
3. Save, then cut again from your edits:

   ```sh
   trad-split --from-reaper "~/Desktop/Ballina Friday/Ballina Friday.RPP" --obsidian
   ```

   The memo location is read from the project. Files from the previous cut are removed first, so renamed regions do not leave stale copies behind.

A normal run never overwrites an existing `.RPP` or note. Pass `--force` to replace them. `--from-csv regions.csv memo.m4a` does the same job from a CSV, for example one exported from Reaper's Region/Marker Manager.

You can also render regions directly from Reaper (File > Render > Bounds: Project regions, file name `$region`). Going back through `trad-split` is better, though, because it tags the files and keeps the Obsidian note in step with them.

## Obsidian

Point the output at a folder inside your vault and tell `trad-split` where the vault root is. Links in the note are then vault-relative, so there is no clash when every session has a `Set 1`:

```toml
# ~/.config/trad-split/config.toml
output = "~/Obsidian/Trad Tunes/Sessions"
vault = "~/Obsidian/Trad Tunes"
obsidian = true
```

The note frontmatter includes `date`, `time`, `source`, `duration`, `set_count`, `music_minutes`, an empty `location` and `players`, and `tags: [session]`. Each set section has `tunes::` and `notes::` inline fields that you can query with Dataview.

## Config file

Every command-line option can have a default in `~/.config/trad-split/config.toml`. See [`config.example.toml`](config.example.toml). Command-line flags override the file, and every on/off option has a `--no-` form.

Once you trust the detection, a typical everyday setup is:

```toml
output = "~/Obsidian/Trad Tunes/Sessions"
vault = "~/Obsidian/Trad Tunes"
obsidian = true
sets_only = true
reaper = false
```

## Tuning

Run with `--plot` and look at `<memo>.png`. The top panel shows the music and chat probabilities, and the bottom panel shows the log-odds, with detected sets shaded green.

| Symptom | Try |
|---|---|
| Sets cut short or split in two by chat over the tune | `--bias 0.5` to `1`, or a higher `--switch-penalty` (e.g. 20) |
| Chat kept as part of a set | `--bias -0.5` to `-1` |
| Short breaks between sets missed | a lower `--min-chat` or `--switch-penalty` |
| Tuning up or a few bars of noodling shows up as a set | a higher `--min-set` (e.g. 60) |
| First notes clipped | a higher `--pad-start` (e.g. 3) |
| Applause or last notes cut off | a higher `--pad-end` (e.g. 5) |

Scores are cached, so each retry is quick. Add `--rescan` to rerun the model.

## Finder Quick Action

This lets you right-click a memo in Finder and choose Quick Actions > Split Trad Session. Right-clicking a saved `.RPP` runs the same action, and it re-cuts from your Reaper edits. You can select several memos at once.

You get a notification when it starts and another when it finishes. The finished one gives the set count, and the session folder then opens. If something goes wrong, the log opens instead. The log lives at `~/Library/Logs/trad-split.log`. The outputs come from your config file, so set that up first (see below).

One-off setup in Automator:

1. Open Automator and choose New Document > Quick Action.
2. At the top, set "Workflow receives current" to files or folders, in Finder.
3. Search the actions list for Run Shell Script and drag it into the workflow.
4. Set Shell to `/bin/bash` and Pass input to as arguments. Replace the script text with:

   ```sh
   "$HOME/Code/trad-split/scripts/finder-quick-action.sh" "$@"
   ```

5. Save it as `Split Trad Session`.

The first time you run it, macOS may ask whether Finder can access your Documents folder. Allow it.

If the action does not appear in the menu, go to System Settings > General > Login Items & Extensions > Finder, and tick Split Trad Session there. On older macOS versions this is under Privacy & Security > Extensions.

To add a keyboard shortcut, go to System Settings > Keyboard > Keyboard Shortcuts > Services > Files and Folders and pick one for Split Trad Session.

While it is running, a small gear shows in the menu bar. Click it to stop.

## Automation

The same script works from Keyboard Maestro or Alfred, and it takes any number of files:

```sh
"$HOME/Code/trad-split/scripts/finder-quick-action.sh" "$KMVAR_File"
```

The command also works on its own, from Keyboard Maestro (Execute Shell Script), from an Alfred File Action, or from a Folder Action on the folder where you drop memos:

```sh
/opt/homebrew/bin/trad-split "$KMVAR_File" --obsidian
```

You can AirDrop memos from the phone, or use Share > Save to Files. Voice Memos synced to the Mac through iCloud live in `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/`. To read that folder, the Terminal (or Keyboard Maestro) needs Full Disk Access in System Settings > Privacy & Security.

## Notes

- Inference runs on the CPU. On Apple Silicon, expect roughly a few minutes per hour of audio. `--device mps` is available but untested.
- Stream-copied cuts land on AAC frame boundaries, which are about 20 ms apart. Use `--reencode` if you need sample-accurate cuts.
- If Reaper shows the memo as offline (for example after moving it), right-click the item, choose Item properties, and point it at the file again. The regions are unaffected.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

`segment.py` holds all the decision logic and is plain numpy, so it can be tested without the model.
