import unittest


class RequiredCheckProbe(unittest.TestCase):
    def test_fails_on_purpose(self):
        self.fail("Deliberate failure: proves a failing required check blocks merging")


if __name__ == "__main__":
    unittest.main()
