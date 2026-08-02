import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FtsLsUiTests(unittest.TestCase):
    def test_fts_profile_reuses_monitor_navigation_and_export_toolbar(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("Station History", template)
        self.assertIn('class="nav-link" data-tab="overview"', template)
        self.assertIn('class="nav-link" data-tab="statistics"', template)
        self.assertIn(
            'class="tab-panel profile-fts-only" data-tab="overview"',
            template,
        )
        self.assertIn(
            'class="tab-panel profile-fts-only" data-tab="statistics"',
            template,
        )
        self.assertGreaterEqual(
            template.count(
                '<button type="button" class="export-csv-button">'
                "Export selected CSV</button>"
            ),
            4,
        )
        self.assertNotIn("Export 24 h CSV", template)

    def test_fts_settings_use_section_save_and_cancel_controls(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        for form_id in (
            "fts-laser-settings-form",
            "fts-system-settings-form",
            "fts-port-settings-form",
        ):
            self.assertIn(f'id="{form_id}"', template)
        self.assertEqual(template.count('class="fts-save-settings"'), 3)
        self.assertEqual(template.count('class="fts-cancel-settings"'), 3)


if __name__ == "__main__":
    unittest.main()
