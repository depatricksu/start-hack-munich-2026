"""22 Nov 11:15: `python3 -m core.share --get` failed on the other laptops with 'database disk image is malformed',
also after a second download, while the live DB and the file on GitHub were intact. The snapshot is now checked before
it is uploaded and before it replaces a local copy, and it replaces it as a new file.
Run: python -m unittest tests.test_share_snapshot -v"""
import os, shutil, sqlite3, tempfile, unittest
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from core import config, db, share  # noqa: E402


class Done:
    def __init__(self, code=0, err=""):
        self.returncode, self.stderr, self.stdout = code, err, ""


def good_copy(path):
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.execute("PRAGMA journal_mode=DELETE")
    src.close(); dst.close()


class Upload(unittest.TestCase):
    def setUp(self):
        db.event("share_snapshot_probe")                       # the live test DB exists and is in WAL mode, like the real one

    def test_each_snapshot_is_complete_and_in_its_own_folder(self):
        a, b = share.snapshot(), share.snapshot()
        try:
            self.assertNotEqual(os.path.dirname(a), os.path.dirname(b))
            for p in (a, b):
                self.assertTrue(share.healthy(p))
                self.assertFalse(os.path.exists(p + "-wal"))
                self.assertEqual(sqlite3.connect(p).execute("PRAGMA journal_mode").fetchone()[0], "delete")
        finally:
            shutil.rmtree(os.path.dirname(a), ignore_errors=True); shutil.rmtree(os.path.dirname(b), ignore_errors=True)

    def test_a_cut_off_file_is_not_healthy(self):
        p = share.snapshot()
        try:
            size = os.path.getsize(p)
            with open(p, "r+b") as f:
                f.truncate(max(4096, size // 2))
            self.assertFalse(share.healthy(p))
            self.assertFalse(share.healthy(p + ".missing"))
        finally:
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)

    def test_upload_sends_a_checked_file_and_cleans_up(self):
        seen = {}

        def gh(*args):
            if args[:2] == ("release", "upload"):
                seen["path"], seen["healthy"] = args[3], share.healthy(args[3])
            return Done()
        with mock.patch.object(share, "_gh", gh), mock.patch.object(share.shutil, "which", return_value="/usr/bin/gh"):
            size = share.upload()
        self.assertTrue(seen["healthy"])
        self.assertGreater(size, 0)
        self.assertEqual(os.path.basename(seen["path"]), "snapshot.db")
        self.assertFalse(os.path.exists(os.path.dirname(seen["path"])))               # the private folder is gone


class Download(unittest.TestCase):
    def setUp(self):
        db.event("share_snapshot_probe")
        self.dir = tempfile.mkdtemp()
        self.local = os.path.join(self.dir, "real", "snapshot.db")
        self.patch = mock.patch.object(share, "LOCAL", self.local)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def gh(self, results):
        """A fake gh: each download writes the next of `results` ('good', 'broken' or 'fail') into the asked folder."""
        def run(*args):
            if args[:2] != ("release", "download"):
                return Done()
            what, target = results.pop(0), os.path.join(args[args.index("-D") + 1], "snapshot.db")
            if what == "fail":
                return Done(1, "release not found")
            good_copy(target)
            if what == "broken":
                with open(target, "r+b") as f:
                    f.truncate(max(4096, os.path.getsize(target) // 2))
            return Done()
        return mock.patch.object(share, "_gh", run)

    def test_a_broken_download_is_tried_again_and_never_installed(self):
        with self.gh(["broken", "fail", "good"]):
            self.assertEqual(share.get(tries=4, wait_s=0), self.local)
        self.assertTrue(share.healthy(self.local))
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.local)) if n.startswith(".snapshot-get-")], [])

    def test_all_downloads_broken_keeps_the_old_copy(self):
        os.makedirs(os.path.dirname(self.local))
        good_copy(self.local)
        before = open(self.local, "rb").read()
        with self.gh(["broken", "broken"]), self.assertRaises(SystemExit) as stop:
            share.get(tries=2, wait_s=0)
        self.assertIn("Your old copy was not touched", str(stop.exception))
        self.assertEqual(open(self.local, "rb").read(), before)

    def test_the_new_copy_is_a_new_file_and_old_leftovers_go(self):
        """A program that still has the old copy open must not be able to write into the new one."""
        os.makedirs(os.path.dirname(self.local))
        good_copy(self.local)
        old_inode = os.stat(self.local).st_ino
        holder = sqlite3.connect(self.local)                    # the control room, still open on the old copy
        for ext in ("-wal", "-shm"):
            open(self.local + ext, "wb").write(b"old")
        with self.gh(["good"]):
            share.get(tries=1, wait_s=0)
        self.assertNotEqual(os.stat(self.local).st_ino, old_inode)
        self.assertFalse(os.path.exists(self.local + "-wal") or os.path.exists(self.local + "-shm"))
        self.assertTrue(share.healthy(self.local))
        holder.close()


if __name__ == "__main__":
    unittest.main()
