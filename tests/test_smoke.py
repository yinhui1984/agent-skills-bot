import unittest

from agent_skills_bot import __version__


class TestSmoke(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
