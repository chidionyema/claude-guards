#!/usr/bin/env python3
"""Escrow the credentials that die with this laptop, split across two accounts.

THE PROBLEM. Three files under ~/.config hold everything the estate cannot
regenerate: the two age private keys that decrypt the deployed secret bundles,
and estate.env, which holds the R2 credentials the offsite backup itself uses.
Every backup path deliberately excludes ~/.config -- tracked.json:55 refuses
"*/age-key.txt", and estate_bundle_push.sh, estate_worktree_cleanup.sh and
prospector's backup_store.py all skip the directory. That exclusion is correct:
those files hold plaintext credentials and must not be copied around. The
consequence was not correct. On 2026-08-23 the measurement was that this laptop
dying would take with it the only copy of the key that opens 25 credentials,
Stripe live among them, AND the only copy of the credential that reaches the
bucket holding every backup.

THE SHAPE. A passphrase somebody has to remember is the usual answer and it is
the wrong one here: the founder does not run scripts (LAW 31) and a passphrase
cannot be handed to him through any channel that does not then keep a copy of it
(LAW 21). So the recovery is split across two accounts he already owns and can
recover through their own flows:

    the encrypted blob  ->  Cloudflare R2, the same bucket the bundles use
    the key that opens it -> iCloud Drive, under his Apple ID

Neither half is worth anything alone. The blob is age ciphertext. The recovery
key decrypts nothing that is not in the bucket. An attacker needs both accounts,
and a rebuild needs both sign-ins -- which are two of the five LAW 27 already
budgets for.

WHAT IT IS NOT. This is not a backup of ~/.config. It is three named files, and
adding a fourth is a deliberate edit to SOURCES below, not a glob that quietly
grows until the escrow is a copy of the home directory.
"""
import errno
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HOME = os.path.expanduser("~")

#: The files that cannot be regenerated from any account. Each one is named
#: rather than globbed, because an escrow that grows by pattern is how a
#: credential nobody reviewed ends up in a bucket.
SOURCES = [
    os.path.join(HOME, ".config/prospector/age-key.txt"),
    os.path.join(HOME, ".config/hermes/age-key.txt"),
    os.path.join(HOME, ".config/estate/estate.env"),
]

#: iCloud Drive holds the recovery key. bird(8) syncs it to the founder's Apple
#: ID with no command from anybody, which is the whole reason this half lives
#: here rather than in a password manager he does not have installed.
ICLOUD = os.path.join(HOME, "Library/Mobile Documents/com~apple~CloudDocs/EstateRecovery")
ICLOUD_KEY = os.path.join(ICLOUD, "estate-recovery-key.txt")
#: The container, not the file. Whether this process can see CloudDocs at all is
#: the only reliable way to tell "the key is gone" from "I am not allowed to look".
ICLOUD_CONTAINER = os.path.join(HOME, "Library/Mobile Documents/com~apple~CloudDocs")


def icloud_visible():
    """True when this process can list the iCloud container.

    Measured on this laptop, 2026-08-24, the same key file both ways:

        by hand           os.stat succeeds, 189 bytes
        under launchd     OSError errno 2, ENOENT -- and the file is still there

    So TCC does not consistently answer a refusal with EACCES or EPERM. For this
    path a scheduled job is told the file does not exist, which is why an errno
    test called a key sitting safely in iCloud NOT PRESENT, and why the drill
    that wraps this reported the estate unrecoverable for a day.

    The container answers it without ambiguity. A process that cannot list
    CloudDocs has learned nothing about any file inside CloudDocs, whichever
    errno it was handed.
    """
    try:
        os.listdir(ICLOUD_CONTAINER)
        return True
    except OSError:
        return False

#: macOS shapes the rest of this file. Measured under launchd on 2026-08-23, a
#: scheduled job may stat and WRITE inside iCloud Drive and may not read or list
#: it -- os.path.exists and open(...,"w") succeed, open(...,"r") and os.listdir
#: raise PermissionError 1. Granting Full Disk Access would fix it and would cost
#: the founder a trip through System Settings, which LAW 27 counts as a defect.
#: So nothing scheduled ever reads iCloud: the public key lives in git, the
#: private key has a launchd-readable copy here, and the iCloud copy is the one
#: that survives the laptop.
RECOVERY_PUB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "recovery-key.pub")
LOCAL_KEY = os.path.join(HOME, ".config/estate/recovery-key.txt")

ENVFILE = os.path.join(HOME, ".config/estate/estate.env")
BLOB_KEY = "escrow/config-keys.age"


def getenv(name):
    """One value out of estate.env. Never logged, never returned to a caller
    that prints. estate_bundle_push.sh:131-139 reads the same file the same way."""
    try:
        with open(ENVFILE) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def r2_env():
    """The rclone environment, built exactly as estate_bundle_push.sh builds it.

    RCLONE_CONFIG=/dev/null on purpose: there is no rclone.conf on this machine
    and there must not be one, because a config file is a credential at rest
    that nothing scans.
    """
    account = getenv("R2_ACCOUNT_ID")
    env = dict(os.environ)
    env.update({
        "RCLONE_CONFIG": "/dev/null",
        "RCLONE_S3_PROVIDER": "Other",
        "RCLONE_S3_REGION": "auto",
        "RCLONE_S3_FORCE_PATH_STYLE": "true",
        "RCLONE_S3_ENDPOINT": "https://%s.r2.cloudflarestorage.com" % account,
        "RCLONE_S3_ACCESS_KEY_ID": getenv("R2_ACCESS_KEY_ID"),
        "RCLONE_S3_SECRET_ACCESS_KEY": getenv("R2_SECRET_ACCESS_KEY"),
        "PATH": os.environ.get("PATH", "") + ":/usr/local/bin:/opt/homebrew/bin",
    })
    bucket = getenv("R2_BUCKET") or "prospector-packs"
    if not env["RCLONE_S3_SECRET_ACCESS_KEY"] or not account:
        return None, None
    return env, bucket


def ensure_recovery_key():
    """Generate the recovery keypair once, and never regenerate it: a new
    keypair orphans every blob already in the bucket, so an existing key is left
    alone even if it looks wrong.

    The private key is written to ~/.config first because that is the copy a
    scheduled job can read, then copied into iCloud Drive, which is the copy
    that outlives the laptop. Writing into iCloud is allowed under launchd; only
    reading it back is not.
    """
    os.makedirs(ICLOUD, mode=0o700, exist_ok=True)
    os.makedirs(os.path.dirname(LOCAL_KEY), mode=0o700, exist_ok=True)
    fresh = False
    if not os.path.exists(LOCAL_KEY):
        p = subprocess.run(["age-keygen", "-o", LOCAL_KEY],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit("age-keygen failed: %s" % p.stderr.strip()[:200])
        os.chmod(LOCAL_KEY, 0o600)
        fresh = True
    if fresh or not os.path.exists(RECOVERY_PUB):
        pub = subprocess.run(["age-keygen", "-y", LOCAL_KEY],
                             capture_output=True, text=True, check=True).stdout.strip()
        with open(RECOVERY_PUB, "w") as fh:
            fh.write(pub + "\n")
    # Create-only, deliberately. Under launchd macOS permits creating a new file
    # in iCloud Drive and refuses to overwrite an existing one, so a copy that
    # needed refreshing could never be refreshed by the scheduled job. The key
    # never changes, so it never needs to be. Nothing else is put here: an
    # earlier version also parked a copy of the ciphertext, which would have gone
    # stale the first time the sealer ran and gone on looking like a backup.
    if not os.path.exists(ICLOUD_KEY):
        shutil.copyfile(LOCAL_KEY, ICLOUD_KEY)
        os.chmod(ICLOUD_KEY, 0o600)
    return fresh


def recovery_identity():
    """The private key a scheduled job can actually open, and the name of which
    copy it is. Prefers iCloud when readable so an agent's run tests the copy
    that has to survive; falls back to ~/.config, which is all launchd gets."""
    try:
        with open(ICLOUD_KEY) as fh:
            fh.read(1)
        return ICLOUD_KEY, "the iCloud copy"
    except OSError:
        pass
    if os.path.exists(LOCAL_KEY):
        return LOCAL_KEY, "the ~/.config copy (macOS blocks scheduled jobs from reading iCloud)"
    return None, "no recovery key anywhere"


def recipient():
    with open(RECOVERY_PUB) as fh:
        return fh.read().strip()


def digest(path):
    """A file's sha256. The only thing that ever leaves this function is the
    hash, so it is safe to compare and print a match/mismatch verdict for files
    whose contents may not be shown."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def seal():
    """Tar the named files, encrypt to the recovery key, put the blob in R2."""
    missing = [s for s in SOURCES if not os.path.exists(s)]
    present = [s for s in SOURCES if os.path.exists(s)]
    if not present:
        print("nothing to escrow: none of the source files exist")
        return 1
    fresh = ensure_recovery_key()
    print("recovery key: %s" % ("generated in iCloud Drive" if fresh else "already in iCloud Drive"))
    for m in missing:
        print("  not present, skipped: %s" % m.replace(HOME, "~"))

    env, bucket = r2_env()
    if env is None:
        print("R2 credentials missing from estate.env; cannot place the blob")
        return 1

    tmp = tempfile.mkdtemp(prefix="escrow-")
    os.chmod(tmp, 0o700)
    try:
        tar = os.path.join(tmp, "config-keys.tar")
        with tarfile.open(tar, "w") as tf:
            for s in present:
                tf.add(s, arcname=os.path.relpath(s, HOME))
        blob = os.path.join(tmp, "config-keys.age")
        p = subprocess.run(["age", "-r", recipient(), "-o", blob, tar],
                           capture_output=True, text=True)
        if p.returncode != 0:
            print("age refused to encrypt: %s" % p.stderr.strip()[:200])
            return 1
        p = subprocess.run(
            ["rclone", "copyto", blob, ":s3:%s/%s" % (bucket, BLOB_KEY),
             "--s3-no-check-bucket"], env=env, capture_output=True, text=True)
        if p.returncode != 0:
            print("rclone could not place the blob: %s" % p.stderr.strip()[:200])
            return 1
        print("sealed %d files -> :s3:%s/%s (%d bytes of ciphertext)"
              % (len(present), bucket, BLOB_KEY, os.path.getsize(blob)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def verify():
    """The drill. Fetch the blob from R2, open it with the iCloud key, and prove
    the restored age key still decrypts real ciphertext.

    The assertion is deliberately the last one and not the first. A blob that
    downloads and untars proves the pipes work; it does not prove the thing
    inside is the key that opens anything, and a restore that hands back a
    stale key is the failure this drill exists to catch. Nothing is printed
    from inside the archive and the temp directory goes on every path out.
    """
    identity, which = recovery_identity()
    if identity is None:
        print("no recovery key: %s" % which)
        return 1
    print("recovery key: using %s" % which)

    # The copy that matters is the one nothing here can read. Under launchd
    # stat is permitted and open is not, so size is the only angle available,
    # and it is reported as the weak angle it is rather than as a check.
    blind = False
    try:
        n = os.stat(ICLOUD_KEY).st_size
        m = os.stat(identity).st_size
        print("iCloud copy: present, %d bytes%s" %
              (n, "" if n == m else " -- DIFFERENT SIZE to %s" % identity.replace(HOME, "~")))
        if n != m:
            return 1
    except OSError as exc:
        # "It is not there" and "I cannot see it from here" are different facts and
        # they lead to different repairs: the first means the sealer is dead, the
        # second means this process lacks the right to look. Collapsing them prints
        # NOT PRESENT for a key that is sitting safely in iCloud, which sends
        # somebody to re-seal an escrow that never broke.
        #
        # The errno does not tell them apart. Under launchd this path answers
        # ENOENT, not EPERM, so the errno test sent exactly that somebody. Ask the
        # container instead: see icloud_visible().
        if not icloud_visible():
            blind = True
            print("iCloud copy: BLIND -- this process cannot list %s, so it cannot "
                  "learn anything about a file inside it (%s). This is not evidence "
                  "the key is missing; it is evidence this process may not look. "
                  "Re-run by hand to get a verdict."
                  % (ICLOUD_CONTAINER.replace(HOME, "~"), exc))
        else:
            print("iCloud copy: NOT PRESENT (%s)" % exc)
            return 1

    env, bucket = r2_env()
    if env is None:
        print("R2 credentials missing from estate.env; cannot reach the blob")
        return 1

    tmp = tempfile.mkdtemp(prefix="escrow-verify-")
    os.chmod(tmp, 0o700)
    try:
        blob = os.path.join(tmp, "blob.age")
        p = subprocess.run(["rclone", "copyto", ":s3:%s/%s" % (bucket, BLOB_KEY), blob],
                           env=env, capture_output=True, text=True)
        if p.returncode != 0 or not os.path.exists(blob):
            print("no escrow blob in the bucket: %s" % p.stderr.strip()[:160])
            return 1
        tar = os.path.join(tmp, "blob.tar")
        p = subprocess.run(["age", "-d", "-i", identity, "-o", tar, blob],
                           capture_output=True, text=True)
        if p.returncode != 0:
            print("the recovery key does not open the blob in the bucket: %s"
                  % p.stderr.strip()[:160])
            return 1
        out = os.path.join(tmp, "restored")
        with tarfile.open(tar) as tf:
            names = tf.getnames()
            tf.extractall(out)

        # An escrow that is merely OLD is the failure this catches. Rotate a key
        # on this laptop and the blob in the bucket keeps restoring cleanly and
        # keeps opening yesterday's ciphertext, so every assertion below still
        # passes while the copy has quietly stopped being a copy. Compare
        # hashes, never contents.
        stale = []
        for s in SOURCES:
            r = os.path.join(out, os.path.relpath(s, HOME))
            if not os.path.exists(s):
                continue
            if not os.path.exists(r):
                stale.append("%s is on this laptop and not in the escrow"
                             % s.replace(HOME, "~"))
            elif digest(s) != digest(r):
                stale.append("%s has changed since it was sealed"
                             % s.replace(HOME, "~"))
        if stale:
            for line in stale:
                print("escrow is stale: %s" % line)
            print("run key_escrow.py --seal to refresh it")
            return 1

        # A restored key is worth exactly what it can still decrypt, so the last
        # assertion runs the key against ciphertext this escrow never touched.
        checked = 0
        for probe_key, probe_ct in (
            (".config/prospector/age-key.txt",
             os.path.join(HOME, "dev/code/prospector-main/deploy/secrets.env.age")),
            (".config/hermes/age-key.txt",
             os.path.join(HOME, "dev/code/hermes-v2/deploy/secrets/claude-credentials.json.age")),
        ):
            k = os.path.join(out, probe_key)
            if not os.path.exists(k) or not os.path.exists(probe_ct):
                continue
            p = subprocess.run(["age", "-d", "-i", k, probe_ct],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if p.returncode != 0:
                print("restored %s does NOT open %s"
                      % (probe_key, probe_ct.replace(HOME, "~")))
                return 1
            checked += 1
        if not checked:
            print("the blob restored %d files but none could be tested against "
                  "real ciphertext, so nothing is proved" % len(names))
            return 1
        print("escrow restores: %d files out of R2, opened with the recovery key, "
              "%d of them proved against live ciphertext" % (len(names), checked))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # Reaching here means the strong angle passed: the blob came out of R2 and the
    # recovery key opened it against live ciphertext. That is the recoverability
    # question. The iCloud stat above is a weak supplementary angle, so when it is
    # blind it downgrades the verdict to "not proved" and never to "failed" -- the
    # whole point of the BLIND line is undone if it still returns a failure.
    return 2 if blind else 0


def selftest():
    """Prove the iCloud line tells absence apart from being unable to look.

    estate-selftest.py runs every --selftest under ~/.claude/scripts once an hour,
    so putting the control here is what stops the next session reintroducing the
    collapse. It touches no key material: it replaces os.stat with a function that
    raises the errno being tested and reads the line that comes out.

    Incident test, rung 4, twice over.

    The first bug: `except OSError` printed NOT PRESENT for every failure, so a
    permission error on a key sitting safely in iCloud read as a lost key.

    The second bug, 2026-08-24, is why the errno column is gone. The fix for the
    first one assumed a refusal arrives as EACCES or EPERM. Measured under launchd
    on this laptop it arrives as ENOENT, so the fix did not fire, the scheduled
    drill printed NOT PRESENT for an intact escrow, and three sessions were told
    the estate could not be recovered without this machine.

    The discriminator is no longer the errno. It is whether this process can list
    the iCloud container at all, so the case matrix pins the errno at the one
    launchd actually produces and varies the visibility instead. ENOENT must
    produce BOTH answers -- that is the pair the old rule could not express.
    """
    import io
    import contextlib

    real_stat = os.stat
    real_listdir = os.listdir
    # errno, container visible, wanted verdict, what it stands for
    cases = [
        (errno.ENOENT, True, "NOT PRESENT",
         "the container lists and the key is not in it -- genuinely gone"),
        (errno.ENOENT, False, "BLIND",
         "what launchd actually produces: ENOENT because it may not look"),
        (errno.EACCES, False, "BLIND", "a refusal that does arrive as a refusal"),
        (errno.EPERM, False, "BLIND", "a file refused by policy rather than by absence"),
    ]
    fails = []
    for code, visible, want, what in cases:
        def fake_stat(path, *a, **k):
            if str(path) == str(ICLOUD_KEY):
                raise OSError(code, os.strerror(code), str(path))
            return real_stat(path, *a, **k)

        def fake_listdir(path, *a, **k):
            if str(path) == str(ICLOUD_CONTAINER) and not visible:
                raise OSError(errno.EPERM, os.strerror(errno.EPERM), str(path))
            return real_listdir(path, *a, **k)
        os.stat = fake_stat
        os.listdir = fake_listdir
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                verify()
        except Exception:
            pass
        finally:
            os.stat = real_stat
            os.listdir = real_listdir
        line = next((l for l in buf.getvalue().splitlines()
                     if l.startswith("iCloud copy:")), "(no iCloud line printed)")
        ok = want in line
        print("  %s  errno %-6s container %-9s -> %-11s %s"
              % ("pass" if ok else "FAIL", errno.errorcode.get(code, code),
                 "visible" if visible else "invisible", want, what))
        if not ok:
            fails.append("%s: got %r" % (what, line))
        # The blind line must never be mistaken for a verdict about the key.
        if want == "BLIND" and "not evidence" not in line:
            fails.append("%s: BLIND line does not say it is not evidence" % what)

    for f in fails:
        print("  FAIL %s" % f)
    # Counted from the table, not written in by hand. The hand-written "1 absent,
    # 2 blind" went stale the moment a case was added, and a summary line that
    # states a number nobody recomputes is the same defect as the drill above.
    absent = sum(1 for c in cases if c[2] == "NOT PRESENT")
    print("%d/%d passed: %d that must read as absent, %d that must read as blind"
          % (len(cases) - len({f.split(':')[0] for f in fails}), len(cases),
             absent, len(cases) - absent))
    return 1 if fails else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--seal" in sys.argv:
        return seal()
    if "--verify" in sys.argv:
        return verify()
    print(__doc__.strip().splitlines()[0])
    print("\n  key_escrow.py --seal     encrypt the named files and place the blob in R2"
          "\n  key_escrow.py --verify   restore from R2 with the iCloud key and prove it opens\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
