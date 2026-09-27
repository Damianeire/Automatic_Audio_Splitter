# trad-split

Splits a recording of a trad session (for example an iPhone Voice Memo) into the sets of tunes and the chat between them.

For each memo it can produce:

- Audio files: `01 Chat 1.m4a`, `02 Set 1.m4a`, `03 Chat 2.m4a` and so on, tagged with the album `yyyymmdd <memo name>` using the recording date. By default they are cut with stream copy, so it is fast and there is no quality loss. `--sets-only` skips the chat.
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

The model scores are cached next to the output (`<memo>.scores.npz`). Re-running with different tuning settings therefore takes seconds.

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

Each memo gets its own folder, named after the memo and placed next to it unless you give `-o`. The folder holds the audio files, the `.RPP`, the CSV, and the note and plot if you asked for them.

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
