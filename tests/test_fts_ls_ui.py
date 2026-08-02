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

    def test_live_view_builds_module_inventory_from_device_data(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn('id="fts-modules"', template)
        self.assertNotIn("UL + 7 modular ports", template)
        self.assertIn("const inventory = [", script)
        self.assertIn("...(status.ports || []).map", script)
        self.assertIn("syncFtsModuleTargets(inventory)", script)
        self.assertIn("data-fts-module-target", script)

    def test_fts_settings_and_service_diagnostics_are_flat_section_panels(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('class="data-panel fts-settings-panel"', template)
        self.assertIn('class="fts-settings-list"', template)
        self.assertNotIn('class="fts-settings-grid"', template)
        self.assertIn('class="data-panel service-diagnostics-panel"', template)
        self.assertIn('class="service-diagnostics-list"', template)
        self.assertNotIn('class="service-diagnostics-grid"', template)

    def test_front_panel_uses_manual_connector_names_and_normalized_units(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn("FTS-LS front panel", template)
        self.assertNotIn("Optical module rack", template)
        self.assertIn("function displayMeasurement", script)
        self.assertIn("connector === 'BN_A' ? 'BNA'", script)
        self.assertIn("displayMeasurement(firstValue(module, ['jitter']), '%')", script)
        self.assertIn("displayMeasurement(firstValue(module, ['optical_power_display', 'optical_power']), 'dBm')", script)

    def test_dirty_state_is_based_on_a_loaded_value_baseline(self):
        script = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn("const ftsInputBaselines = new Map()", script)
        self.assertIn("input.value === ftsInputBaselines.get(input.id)", script)


if __name__ == "__main__":
    unittest.main()
