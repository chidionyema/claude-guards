# What the key escrow does when it runs

Two jobs. One writes the copy every day at 05:10 and says nothing. The other
checks the copy every Monday and puts a line on the board. The output below is
from real runs on 2026-08-23, pasted as it came back.

## The daily job, run by the machine

The sealer runs under launchd, so this is what it did with nobody watching:

    $ launchctl print gui/501/ai.estate.key-escrow | grep -E 'runs|last exit code'
    	runs = 3
    	last exit code = 0

    $ tail -3 ~/.claude/logs/key-escrow.log
    recovery key: already in iCloud Drive
    sealed 3 files -> :s3:prospector-packs/escrow/config-keys.age (10440 bytes of ciphertext)

Three files went in: the prospector age key, the hermes age key, and
`estate.env`. What went to Cloudflare is 10,440 bytes of ciphertext and nothing
else. The line says how many bytes it wrote, on purpose, because a sealer that
silently wrote nothing would otherwise log exactly the same thing as one that
worked.

## The weekly check, run by the machine

The drills job fired under launchd and ran all five written drills. This is the
line that matters here:

    $ tail ~/.claude/logs/drills.log
      no-anthropic           PASS   rc=0    44.3s  VERDICT: the estate can still work without Anthropic.
      rebuild                FAIL   rc=1     3.6s  DRILL FAILED
      estate-bundle-restore  PASS   rc=0     0.1s  4 of the last 17 pushes cloned back standalone, newest push 4.3h ago
      offsite-backup-restore PASS   rc=0    13.8s  13/13 prefixes restored from prospector-backup.
      key-escrow-restore     PASS   rc=0     0.9s  DRILL PASSED

The escrow drill takes 0.9 seconds. It fetches the blob from Cloudflare, opens
it, and checks what came out against the real keys.

## The same check, run by an agent

An agent can read iCloud Drive where a scheduled job cannot, so a hand-run tests
the copy that actually has to survive:

    $ /usr/bin/python3 drills/check_key_escrow.py
    recovery key: using the iCloud copy
    iCloud copy: present, 189 bytes
    escrow restores: 3 files out of R2, opened with the recovery key, 2 of them proved against live ciphertext
    DRILL PASSED: a new machine with the founder's Apple ID and his Cloudflare account can recover both age keys.
    EXIT=0

"2 of them proved against live ciphertext" is the part that means something. The
drill does not stop at "the blob opened". It takes the two age keys that came out
of the escrow and uses them to decrypt secret bundles the escrow has never
touched: `prospector-main/deploy/secrets.env.age` and
`hermes-v2/deploy/secrets/claude-credentials.json.age`. If the restored key were
the wrong key, or an old key, that step fails. Nothing decrypted is ever printed.

## Proof it can fail

A check that cannot go red proves nothing. Both of these were run deliberately.

A file on the laptop that the escrow does not hold:

    escrow is stale: ~/notsealed-cb3znpch.txt is on this laptop and not in the escrow
    run key_escrow.py --seal to refresh it
    DRILL FAILED: the two age keys and the R2 credentials cannot be recovered without this laptop.

The wrong recovery key:

    age: error: no identity matched any of the recipients
    DRILL FAILED: the two age keys and the R2 credentials cannot be recovered without this laptop.

## What it looked like before

Nothing. The two age keys existed on one laptop, in one directory, and every
backup on the estate skipped that directory deliberately so it would never
capture a credential. The offsite bucket held encrypted copies of everything and
the only key to them was on the machine the backup exists to survive.
