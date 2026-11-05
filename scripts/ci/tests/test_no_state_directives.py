import json
import re
import unittest
from pathlib import Path


class StateDirectiveTests(unittest.TestCase):
    def test_configuration_has_no_declarative_state_directives(self):
        root = Path(__file__).resolve().parents[3]
        violations = []
        for path in root.rglob("*.tf"):
            if ".terraform" not in path.parts:
                for match in re.finditer(
                    r"^\s*(?:import|moved)\s*\{", path.read_text(), re.MULTILINE
                ):
                    violations.append(
                        str(path.relative_to(root)) + ":" + match.group().strip()
                    )
        for path in root.rglob("*.tf.json"):
            if ".terraform" not in path.parts:
                data = json.loads(path.read_text())
                violations.extend(
                    str(path.relative_to(root)) + ":" + key
                    for key in ("import", "moved")
                    if key in data
                )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
