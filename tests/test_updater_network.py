# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import unittest

# This test hits GitHub APIs. Run only when explicitly enabled.
RUN_NETWORK = os.environ.get("BLINDRSS_RUN_NETWORK_TESTS", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


@unittest.skipUnless(RUN_NETWORK, "Network tests disabled (set BLINDRSS_RUN_NETWORK_TESTS=1)")
class UpdaterNetworkTests(unittest.TestCase):
    def test_check_for_updates_hits_network(self):
        from core import updater

        result = updater.check_for_updates()
        if result.status == "error":
            self.skipTest(result.message or "Updater network check failed")

        self.assertIn(result.status, ("update_available", "up_to_date"))


if __name__ == "__main__":
    unittest.main()
