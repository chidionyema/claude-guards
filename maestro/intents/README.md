# intents

One JSON file per decision: what Maestro sensed, which of the seven laws it applied,
what it chose, what it ran, and what came back. THE-ARCHITECT calls this the white box.

They are written at runtime to `$MAESTRO_INTENTS`, default `~/.maestro/intents/`, and
they are deliberately not committed. A deputy ticking every 60 seconds would otherwise
add a file to this repo a thousand times a day, and git is the wrong store for a stream.

The copy that matters is not the file anyway. `board.post_intent()` puts the laws applied,
the hypothesis and the command output onto the issue, so the board entry carries the proof
and the founder never has to open a terminal to read one.

    ls -t ~/.maestro/intents | head            # the last decisions
    python3 -m json.tool ~/.maestro/intents/<id>.json
