"""Static regression checks for readable instance-table line wrapping."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PortalInstanceTableTests(unittest.TestCase):
    def test_instance_table_has_a_horizontal_scroll_boundary(self) -> None:
        html = (ROOT / "console" / "portal" / "index.html").read_text()

        self.assertIn('class="table-scroll instance-table-scroll"', html)
        self.assertIn('class="tbl instance-table" id="admin-instances"', html)

    def test_generated_cells_have_semantic_layout_classes(self) -> None:
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        for class_name in (
            "instance-domain",
            "instance-company",
            "instance-status",
            "instance-version",
            "instance-people",
            "instance-seen",
            "instance-actions",
        ):
            self.assertIn(class_name, javascript)

        self.assertIn("function instanceDomainHtml(value)", javascript)
        self.assertIn("var bestCut = 1", javascript)
        self.assertIn('"</span><br>"', javascript)

    def test_compact_values_do_not_break_in_the_middle(self) -> None:
        css = (ROOT / "console" / "portal" / "portal.css").read_text()

        self.assertIn(".table-scroll .instance-table { min-width: 1090px; }", css)
        self.assertIn(".instance-table .instance-region-cell { min-width: 155px; }", css)
        self.assertIn("width: 178px; min-width: 150px; max-width: 178px", css)
        self.assertIn(".instance-table .instance-domain-line { white-space: nowrap; }", css)
        self.assertIn("white-space: nowrap; word-break: keep-all", css)
        self.assertIn(".instance-table .instance-status .badge", css)


if __name__ == "__main__":
    unittest.main()
