"""Local enrollment (`nerfed enroll` / `nerfed bank`) and the pure-Python bank builder.
Run: python3 -m unittest tests.test_enrollment -v"""
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "plugin", "skills", "is-gpt-nerfed", "scripts")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "reference_subset.jsonl")
FAKE_CODEX = os.environ.get("NERFED_TEST_CODEX_BIN") or os.path.join(ROOT, "tests", "fake_codex.py")
TMP = tempfile.mkdtemp(prefix="nerfed-enroll-test-")
os.environ.setdefault("NERFED_HOME", os.path.join(TMP, "ledger"))
os.environ["NERFED_NO_UPDATE_CHECK"] = "1"
sys.path.insert(0, SCRIPTS)

loader = importlib.machinery.SourceFileLoader("nerfed_enroll_under_test", os.path.join(SCRIPTS, "nerfed"))
spec = importlib.util.spec_from_loader(loader.name, loader)
nerfed = importlib.util.module_from_spec(spec)
loader.exec_module(nerfed)
from modeltrace_build import builder, challenge_suite  # noqa: E402

ALL_REFERENCE_ROWS = nerfed.reference_rows()

def reference_subset(exclude=()):
    """Four reference models, every prompt: small enough to rebuild a bank in a couple of seconds."""
    keep = {"gpt-5.4", "gpt-5.5", "gpt-5.6-sol", "gpt-6-sol"} - set(exclude)
    return [r for r in ALL_REFERENCE_ROWS if r["model_id"] in keep]


class BuilderParityTests(unittest.TestCase):
    def test_pure_builder_matches_modeltrace_numpy_builder(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed (only needed for this parity check)")
        sys.path.insert(0, ROOT)
        from tests.modeltrace_numpy import bank_builder as upstream
        rows = builder.prepare_rows(reference_subset())
        ours = builder.build_bank(rows)
        theirs = upstream.build_bank([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
        for key in ("1", "2", "3"):
            self.assertAlmostEqual(ours["calibration"][key]["beta"], theirs["calibration"][key]["beta"], places=9)
            self.assertEqual(ours["calibration"][key]["cv_correct"], theirs["calibration"][key]["cv_correct"])
        for block in ("hellinger", "ordered_blocks"):
            a, b = ours["robust"][block], theirs["robust"][block]
            for field in ("feature_mean", "feature_scale", "centroids"):
                for x, y in zip(sum(map(list, a[field] if isinstance(a[field][0], list) else [a[field]]), []),
                                sum(map(list, b[field] if isinstance(b[field][0], list) else [b[field]]), [])):
                    self.assertAlmostEqual(x, y, places=10)
            # Singular vectors are defined up to sign: compare the projectors they span.
            pa, pb = a["nuisance_basis"], b["nuisance_basis"]
            self.assertEqual(len(pa), len(pb))
            for i in range(0, len(pa[0]), 11):
                for j in range(0, len(pa[0]), 13):
                    self.assertAlmostEqual(sum(v[i] * v[j] for v in pa), sum(v[i] * v[j] for v in pb), places=10)

    def test_jacobi_eigen_recovers_known_decomposition(self):
        values, vectors = builder._jacobi_eigen([[4.0, 1.0], [1.0, 3.0]])
        for k, lam in enumerate(values):
            v = [vectors[0][k], vectors[1][k]]
            self.assertAlmostEqual(4 * v[0] + v[1], lam * v[0], places=12)
            self.assertAlmostEqual(v[0] + 3 * v[1], lam * v[1], places=12)


class EnrollTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-", dir=TMP)
        self.patches = [mock.patch.object(nerfed, n, os.path.join(self.home, *p)) for n, p in (
            ("NERFED_HOME", ()), ("USER_BANK_PATH", ("unified_bank.json",)), ("ENROLLED_DIR", ("enrolled",)),
            ("CONFIG_PATH", ("config.json",)))]
        self.patches.append(mock.patch.object(nerfed, "reference_rows", reference_subset))
        self.patches.append(mock.patch.dict(os.environ, {"FAKE_CODEX_MODEL": "gpt-6-astra", "CODEX_BIN": ""}))
        for p in self.patches:
            p.start()
        nerfed._BANK = None
        nerfed.save_config({**nerfed.DEFAULT_CONFIG, "codex_bin": FAKE_CODEX})

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        nerfed._BANK = None

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                rc = nerfed.main(list(argv))
            except SystemExit as e:
                rc = e.code
        return rc, buf.getvalue()

    def test_enroll_collects_the_suite_and_the_bank_then_recognises_the_model(self):
        # The fake Codex answers with gpt-6-astra's reference texts, which the four-model reference set lacks.
        rc, out = self.run_cli("enroll", "gpt-6.1-sol", "--parallel", "12")
        self.assertEqual(rc, 0, out)
        enrolled = nerfed.enrolled_rows("gpt-6.1-sol")
        self.assertEqual(len(enrolled), len(challenge_suite.fingerprint_suite()))
        self.assertTrue(all(r["strict_valid"] and r["family_id"] == "gpt" for r in enrolled))
        bank = nerfed.load_bank()
        self.assertEqual(bank["local_enrollments"], ["gpt-6.1-sol"])
        self.assertIn("gpt-6.1-sol", [m["id"] for m in bank["models"]])
        with open(FIXTURE, encoding="utf-8") as f:
            astra = [json.loads(line) for line in f if json.loads(line)["model_id"] == "gpt-6-astra"]
        verdict = nerfed.core.analyze_global_outputs(
            [{"text": r["text"], "expected_count": r["requested_count"]} for r in astra], bank)
        self.assertEqual(verdict["prediction"], "gpt-6.1-sol")

        rc, out = self.run_cli("bank", "--json")
        self.assertEqual(json.loads(out)["enrolled_here"], ["gpt-6.1-sol"])
        rc, out = self.run_cli("bank", "forget", "gpt-6.1-sol")
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(nerfed.USER_BANK_PATH), "without enrollments the bundled bank is used again")
        self.assertNotIn("gpt-6.1-sol", nerfed.core.bank_model_ids(nerfed.load_bank()))

    def test_bank_flags_an_enrolled_model_indistinguishable_from_a_known_one(self):
        # An "enrollment" that is really gpt-5.5 answering (relabelled copies of its reference answers).
        os.makedirs(nerfed.ENROLLED_DIR)
        with open(os.path.join(nerfed.ENROLLED_DIR, "gpt-6.2-sol.jsonl"), "w", encoding="utf-8") as f:
            for r in reference_subset():
                if r["model_id"] == "gpt-5.5":
                    f.write(json.dumps({**r, "model_id": "gpt-6.2-sol", "source": "gpt-6.2-sol"}) + "\n")
        rc, _ = self.run_cli("bank", "rebuild")
        self.assertEqual(rc, 0)
        twins = dict(nerfed.enrollment_twins(nerfed.load_bank(), "gpt-6.2-sol"))
        self.assertGreaterEqual(twins.get("gpt-5.5", 0), 0.2, twins)
        rc, out = self.run_cli("bank")
        self.assertIn("hard to tell apart: gpt-6.2-sol ~ gpt-5.5", out)

    def test_enroll_keeps_partial_answers_and_resumes(self):
        suite = challenge_suite.fingerprint_suite()
        os.makedirs(nerfed.ENROLLED_DIR)
        first = {"challenge_id": suite[0]["challenge_id"], "model_id": "gpt-6.2-sol", "strict_valid": True, "text": "x"}
        with open(os.path.join(nerfed.ENROLLED_DIR, "gpt-6.2-sol.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(first) + "\n")
        with mock.patch.dict(os.environ, {"FAKE_CODEX_FAIL": "1"}):
            rc, out = self.run_cli("enroll", "gpt-6.2-sol", "--retries", "0", "--parallel", "12")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{len(suite) - 1} of {len(suite)}", out, "an earlier answer is kept, not re-requested")
        self.assertFalse(os.path.exists(nerfed.USER_BANK_PATH), "an incomplete set never reaches the bank")

    def test_rebuild_user_bank_preserves_and_deduplicates_aliases(self):
        # Reference rows carrying display_name & aliases should survive user-bank rebuilds,
        # while locally enrolling an aliased model strips the conflicting alias from its original carrier.
        aliased_ref = [
            ({**r, "display_name": "gpt-6-sol/alias", "aliases": ["gpt-6.9-alias", "gpt-6.9-keep"]}
             if r["model_id"] == "gpt-6-sol" else r)
            for r in reference_subset()
        ]
        os.makedirs(nerfed.ENROLLED_DIR)
        with open(os.path.join(nerfed.ENROLLED_DIR, "gpt-6.9-alias.jsonl"), "w", encoding="utf-8") as f:
            for r in reference_subset():
                if r["model_id"] == "gpt-5.5":
                    f.write(json.dumps({**r, "model_id": "gpt-6.9-alias", "source": "gpt-6.9-alias"}) + "\n")
        with mock.patch.object(nerfed, "reference_rows", return_value=aliased_ref):
            rc, _ = self.run_cli("bank", "rebuild")
        self.assertEqual(rc, 0)
        bank = nerfed.load_bank()
        aliases = nerfed.core.bank_model_aliases(bank)
        self.assertNotIn("gpt-6.9-alias", aliases)
        self.assertEqual(aliases.get("gpt-6.9-keep"), "gpt-6-sol")
        sol_entry = next(m for m in bank["models"] if m["id"] == "gpt-6-sol")
        self.assertEqual(sol_entry["display_name"], "gpt-6-sol/alias")


class BundledBankTests(unittest.TestCase):
    def test_bundled_bank_matches_provenance_and_covers_post_56_gpt(self):
        import hashlib
        bank_path = os.path.join(ROOT, "plugin", "assets", "modeltrace", "unified_bank.json")
        prov_path = os.path.join(ROOT, "plugin", "assets", "modeltrace", "provenance.json")
        with open(bank_path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        with open(prov_path, "r", encoding="utf-8") as f:
            prov = json.load(f)
        self.assertEqual(digest, prov["sha256"])
        bank = nerfed.core.load_bank(bank_path)
        ids = nerfed.core.bank_model_ids(bank)
        self.assertEqual(ids, prov["models"])
        for model_id in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-terra", "gpt-6.2-sol", "gpt-6.2-astra"):
            self.assertIn(model_id, ids)
        aliases = nerfed.core.bank_model_aliases(bank)
        self.assertEqual(aliases.get("gpt-6.1-sol"), "gpt-6-astra")
        with open(FIXTURE, encoding="utf-8") as f:
            astra = [json.loads(line) for line in f if json.loads(line)["model_id"] == "gpt-6-astra"]
        analysis = nerfed.core.analyze_global_outputs(
            [{"text": r["text"], "expected_count": r["requested_count"]} for r in astra], bank)
        verdict = nerfed.assess("gpt-6.1-sol", analysis, [])
        self.assertEqual(verdict["verdict"], "MATCH")
        self.assertTrue(verdict["matched_via_alias"])


if __name__ == "__main__":
    unittest.main()
