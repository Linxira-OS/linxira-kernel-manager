from __future__ import annotations

import unittest

from linxira_kernel_manager.collector import parse_dkms_status, parse_grub_config, parse_grub_environment

from helpers import GRUB_CONFIG


class ParserTests(unittest.TestCase):
    def test_grub_parser_filters_custom_kernel(self) -> None:
        entries, default = parse_grub_config(GRUB_CONFIG)
        self.assertEqual([item["id"] for item in entries], ["linux-main", "linux-lts-main"])
        self.assertEqual(default, {"kind": "saved", "value": None})

    def test_grub_environment_saved_and_next(self) -> None:
        state = parse_grub_environment("saved_entry=linux-main\nnext_entry=advanced>linux-lts-main\nother=x\n")
        self.assertEqual(state["savedEntry"], "linux-main")
        self.assertEqual(state["nextEntry"], "advanced>linux-lts-main")

    def test_malformed_dkms_is_not_accepted(self) -> None:
        records, malformed = parse_dkms_status("broken\nnvidia/1, release, x86_64: installed\n", {"release"})
        self.assertEqual(malformed, 1)
        self.assertEqual(records[0]["module"], "nvidia")


if __name__ == "__main__":
    unittest.main()
