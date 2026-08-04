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

    def test_extract_homepage_image_candidates_from_html(self):
        html = """
        <html><head>
        <meta property="og:image" content="https://example.com/cover.jpg" />
        <meta name="twitter:image" content="/images/social.png" />
        </head><body>
        <img src="//cdn.example.com/logo.png" />
        <img srcset="/img/hero.png 1x, /img/hero@2x.png 2x" />
        </body></html>
        """

        candidates = update_news._extract_homepage_image_candidates("https://journal.example.com", html)

        self.assertIn("https://example.com/cover.jpg", candidates)
        self.assertIn("https://journal.example.com/images/social.png", candidates)
        self.assertIn("https://cdn.example.com/logo.png", candidates)
        self.assertIn("https://journal.example.com/img/hero.png", candidates)

    def test_news_cover_wrapper_accepts_html_date_format(self):
        content = "<strong>2026-07</strong> Accepted for a <b>Journal paper</b> in <a href='https://example.com/paper'><em>Example Journal</em></a>"

        wrapped = update_news.add_covers_to_existing(content, dry_run=True)

        self.assertIn("<strong>2026-07</strong>", wrapped)
        self.assertIn("https://example.com/paper", wrapped)


if __name__ == "__main__":
    unittest.main()
