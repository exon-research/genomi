"""Contract test: no Genomi operation may leak a raw exception.

`call_operation` is the single entry point used by MCP and the background-job
worker. The worker catches OperationError and writes a clean structured
failure envelope; anything else becomes "background_job_exception" with no
actionable code, which is what agents see when something goes wrong.

This test exercises EVERY registered operation through `call_operation` with
both empty params and a bag of non-existent path inputs. The contract:

- Either returns a dict (success or structured "needs_*" envelope), OR
- Raises OperationError (structured, with a code and message).

Anything else — ValueError, FileNotFoundError, NameError, AttributeError,
KeyError, sqlite3.Error, ... — is a regression. The audit that produced this
test fixed ten such regressions across the v3 / v4 sequential codex run
(clinvar.scan_candidates FileNotFoundError,
phenotype.retrieve_disease_drug_targets NameError caused by a missing import,
sequence.classify_kozak AttributeError caused by a stale function name, and
seven phenotype/grounding handlers raising ValueError on missing required
inputs).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from genomi.operations import OPERATIONS, OperationError, call_operation
from genomi.runtime import context as runtime_context

# A grab-bag of common path-like parameters. Operations that take any of
# these will see a path that does not exist on disk — their contract is that
# they must convert FileNotFoundError into a structured OperationError.
PATH_BAG = {
    "vcf": "/tmp/genomi-contract-missing.vcf",
    "source": "/tmp/genomi-contract-missing.vcf",
    "db": "/tmp/genomi-contract-missing.db",
    "shared_db": "/tmp/genomi-contract-missing.db",
    "active_genome_index_path": "/tmp/genomi-contract-missing.active-genome-index.sqlite",
    "matches": "/tmp/genomi-contract-missing.jsonl",
    "output": "/tmp/genomi-contract-missing-out.json",
    "report_json": "/tmp/genomi-contract-missing.report.json",
    "report_html": "/tmp/genomi-contract-missing.report.html",
    "outside_call_file": "/tmp/genomi-contract-missing.tsv",
    "reference_fasta": "/tmp/genomi-contract-missing.fa",
    "genotype_reference_fasta": "/tmp/genomi-contract-missing.fa",
    "claims": "/tmp/genomi-contract-missing.claims.json",
    "fasta": "/tmp/genomi-contract-missing.fa",
}

# Public-source operations should exercise error-envelope conversion without
# spending the contract suite's runtime budget on live internet timeouts.
EXTERNAL_URL_BAG = {
    "clinpgx_api_url": "http://127.0.0.1:9",
    "pgxdb_api_url": "http://127.0.0.1:9",
    "fda_biomarkers_url": "http://127.0.0.1:9/fda-biomarkers",
    "fda_associations_url": "http://127.0.0.1:9/fda-associations",
}

# A grab-bag of common required scalars so operations that need them get past
# their input validation and exercise the path-handling code.
SCALAR_BAG = {
    "gene": "BRCA1",
    "rsid": "rs429358",
    "chrom": "17",
    "pos": 43044295,
    "ref": "A",
    "alt": "G",
    "drug": "clopidogrel",
    "phenotype": "lactose intolerance",
    "condition": "breast cancer",
    "sequence": "ATGCCCGGGAAATAG",
    "genes": ["BRCA1"],
    "pathway_name": "Glycolysis",
    "cell_type_name": "hepatocyte",
    "entity_name": "BRCA1",
}

BAD_INPUT_BAG = {**PATH_BAG, **EXTERNAL_URL_BAG, **SCALAR_BAG}


class OperationErrorContractTests(unittest.TestCase):
    """Every registered operation must return a dict or raise OperationError."""

    def setUp(self) -> None:
        # Point GENOMI_HOME at a tmp dir so the contract test never reads or
        # writes the developer's real ~/.genomi state.
        self._home_tmp = tempfile.TemporaryDirectory(prefix="genomi-contract-")
        self.addCleanup(self._home_tmp.cleanup)
        self._saved_env: dict[str, str | None] = {}
        env_overrides = {
            "GENOMI_HOME": self._home_tmp.name,
            "GENOMI_CONTEXT": "",
            "GENOMI_SESSION_ID": "",
            "GENOMI_CONTEXT_POLICY": "explicit",
        }
        for key, value in env_overrides.items():
            self._saved_env[key] = os.environ.get(key)
            os.environ[key] = value
        self.addCleanup(self._restore_env)
        self._git_repo = mock.patch(
            "genomi.operations.registry.handlers_admin._runtime_git_repo",
            return_value=None,
        )
        self._git_repo.start()
        self.addCleanup(self._git_repo.stop)
        self._install_libraries = mock.patch(
            "genomi.operations.registry.handlers_admin._install_libraries_step",
            return_value={"status": "completed", "stub": True},
        )
        self._install_libraries.start()
        self.addCleanup(self._install_libraries.stop)

    def _restore_env(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _check_contract(self, op_name: str, params: dict) -> None:
        """Run one call and assert nothing escapes other than OperationError."""
        runtime_context.clear_active_genome_index(forget_active_genome_indexes=True)
        runtime_context.clear_default_user()
        try:
            result = call_operation(op_name, params)
        except OperationError:
            # Structured failure is the contract — accept.
            return
        except Exception as exc:
            self.fail(
                f"{op_name} leaked {type(exc).__name__}: {exc}. "
                f"Every operation must return a dict or raise OperationError. "
                f"Wrap the failing call in operations.py so the result is a "
                f"structured 'needs_*' / 'invalid_params' envelope."
            )
        else:
            self.assertIsInstance(
                result, dict,
                msg=f"{op_name} returned {type(result).__name__}, expected dict",
            )

    def test_operation_contract_empty_params(self) -> None:
        """Every operation must handle empty params without leaking a raw exception."""
        for op in OPERATIONS:
            with self.subTest(op=op.name):
                self._check_contract(op.name, {})

    def test_operation_contract_bad_input_bag(self) -> None:
        """Every operation must handle a bag of non-existent paths + plausible
        scalars without leaking a raw exception. This catches handlers that
        pass user paths to underlying library code that raises FileNotFoundError,
        sqlite3.Error, or similar without conversion."""
        for op in OPERATIONS:
            with self.subTest(op=op.name):
                self._check_contract(op.name, dict(BAD_INPUT_BAG))

    def test_call_operation_invalid_params_type(self) -> None:
        """Non-dict params must surface as a structured error."""
        with self.assertRaises(OperationError) as excinfo:
            call_operation("genomi.list_resources", "not a dict")  # type: ignore[arg-type]
        self.assertEqual(excinfo.exception.code, "invalid_params")

    def test_call_operation_unknown_operation_name(self) -> None:
        """An unknown operation name must raise a structured error, not KeyError."""
        with self.assertRaises(OperationError):
            call_operation("does.not.exist", {})


if __name__ == "__main__":
    unittest.main()
