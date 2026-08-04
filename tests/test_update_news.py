import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import update_news


class UpdateNewsParserTests(unittest.TestCase):
    def test_parse_journal_entries_with_current_publications_format(self):
        content = """
        **(J35)** Yin, W., Deuser, F., Jiang, J., Liu, Z., Luo, X., Zheng, Z., Werner, M., <strong>Li, H.</strong>, Xue, Y., 2026. [*SAGINGeo: A Space-Aerial-Ground Integrated Framework for VGI Geolocalization in Multi-Disaster Scenarios.* IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing.](https://example.com/paper)
        """

        entries = update_news.parse_journal_entries(content)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["number"], 35)
        self.assertEqual(entries[0]["title"], "SAGINGeo: A Space-Aerial-Ground Integrated Framework for VGI Geolocalization in Multi-Disaster Scenarios")
        self.assertEqual(entries[0]["venue_raw"], "IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing")
        self.assertEqual(entries[0]["url"], "https://example.com/paper")


if __name__ == "__main__":
    unittest.main()
