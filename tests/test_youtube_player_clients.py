import unittest

from core import discovery


class TestYoutubePlayerClients(unittest.TestCase):
    def test_cli_arg_form(self):
        arg = discovery.youtube_player_client_arg()
        self.assertTrue(arg.startswith("youtube:player_client="))
        clients = arg.split("=", 1)[1].split(",")
        # Widening the client pool is the reliability fix: keep yt-dlp's maintained
        # "default" set plus the android_vr workaround that keeps packaged builds working.
        self.assertIn("default", clients)
        self.assertIn("android_vr", clients)

    def test_python_list_form(self):
        clients = discovery.youtube_player_client_list()
        self.assertIsInstance(clients, list)
        self.assertIn("default", clients)
        self.assertIn("android_vr", clients)

    def test_arg_and_list_are_consistent(self):
        arg_clients = discovery.youtube_player_client_arg().split("=", 1)[1].split(",")
        self.assertEqual(arg_clients, discovery.youtube_player_client_list())

    def test_fallback_pool_is_wider_and_superset(self):
        primary = set(discovery.YOUTUBE_PLAYER_CLIENTS)
        fallback = set(discovery.YOUTUBE_PLAYER_CLIENTS_FALLBACK)
        # The fallback is a strictly wider net used only after the primary fails.
        self.assertTrue(primary.issubset(fallback))
        self.assertGreater(len(fallback), len(primary))
        # Plain "android" now needs PO tokens; keep it out of the anonymous fallback.
        self.assertNotIn("android", discovery.YOUTUBE_PLAYER_CLIENTS_FALLBACK)

    def test_client_override_threads_through_arg_and_list(self):
        override = ("web", "ios")
        self.assertEqual(discovery.youtube_player_client_list(override), ["web", "ios"])
        self.assertEqual(
            discovery.youtube_player_client_arg(override),
            "youtube:player_client=web,ios",
        )
        # No-arg still returns the primary set.
        self.assertEqual(
            discovery.youtube_player_client_list(),
            list(discovery.YOUTUBE_PLAYER_CLIENTS),
        )


if __name__ == "__main__":
    unittest.main()
