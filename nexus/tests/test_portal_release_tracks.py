"""Static regression checks for the visibly separated Nexus release tracks."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PortalReleaseTrackTests(unittest.TestCase):
    def test_release_target_is_two_visible_radio_cards(self) -> None:
        html = (ROOT / "console" / "portal" / "index.html").read_text()

        self.assertIn('class="release-target-options"', html)
        self.assertIn('type="radio" name="target" value="node"', html)
        self.assertIn('type="radio" name="target" value="nexus"', html)
        self.assertIn("GuDuu OS 节点镜像", html)
        self.assertIn("Nexus 后台公告", html)
        self.assertNotIn('<select name="target"', html)

    def test_each_release_target_has_its_own_change_listener(self) -> None:
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn("$all('#form-release input[name=\"target\"]')", javascript)
        self.assertNotIn("elements.target.addEventListener", javascript)

    def test_selected_tracks_have_distinct_visual_states(self) -> None:
        css = (ROOT / "console" / "portal" / "portal.css").read_text()

        self.assertIn(".release-target-node:has(input:checked)", css)
        self.assertIn(".release-target-nexus:has(input:checked)", css)


if __name__ == "__main__":
    unittest.main()
