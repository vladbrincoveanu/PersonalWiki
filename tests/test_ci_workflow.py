from pathlib import Path
import re
import unittest


class CIWorkflowTest(unittest.TestCase):
    def test_workflow_has_one_global_environment_block(self):
        workflow = Path(__file__).parents[1].joinpath(
            ".github", "workflows", "ci.yml"
        ).read_text()

        self.assertEqual(1, len(re.findall(r"^env:$", workflow, re.MULTILINE)))
        for variable in ("VAULT_PATH", "INDEX_PATH"):
            self.assertRegex(
                workflow,
                re.compile(rf"^  {variable}:", re.MULTILINE),
            )


if __name__ == "__main__":
    unittest.main()
