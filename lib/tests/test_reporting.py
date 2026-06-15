import unittest

from openrelik_worker_common.reporting import (
    MarkdownDocument,
    MarkdownDocumentSection,
    MarkdownTable,
    Priority,
    Report,
)


class TestMarkdownDocument(unittest.TestCase):
    def test_markdown_document_init(self):
        document = MarkdownDocument("Test Document")
        self.assertEqual(document.title, "Test Document")
        self.assertEqual(document.sections, [])

    def test_markdown_document_add(self):
        report = Report("Test Report")
        report.summary = "Test Summary"
        report.priority = Priority.LOW

        document = MarkdownDocument("Test Title")
        # document.title = "Test Title"
        section = document.add_section()
        section.add_header("Test Header", level=2)
        section.add_bullet("Test Bullet", level=1)
        section.add_code("Test Code")
        section.add_code_block("Test Code Block")
        section.add_blockquote("Test Blockquote")
        section.add_paragraph(document.fmt.bold("Test Paragraph"))
        section.add_horizontal_rule()
        table = MarkdownTable(["column1", "column2"])
        table.add_row(["row1", "row2"])
        section.add_table(table)

        with self.assertRaises(ValueError):
            table.add_row(["row1", "row2", "rowthatshouldnotbehere"])

        with self.assertRaises(ValueError):
            section.fmt.heading(text="Test Header", level=999)

        markdown = document.to_markdown()
        self.assertIsInstance(section, MarkdownDocumentSection)
        self.assertIn("# Test Title", markdown)
        self.assertIn("## Test Header", markdown)
        self.assertIn("## Test Header", markdown)
        self.assertIn("* Test Bullet", markdown)
        self.assertIn("`Test Code`", markdown)
        self.assertIn("```\nTest Code Block\n```", markdown)
        self.assertIn("> Test Blockquote", markdown)
        self.assertIn("**Test Paragraph**", markdown)
        self.assertIn("---", markdown)
        self.assertIn("|column1|column2|", markdown)

        json = report.to_json()
        self.assertEqual(
            json,
            '{"title": "Test Report", "summary": "Test Summary", "content": "# Test Report\\n", "priority": 10}',
        )

    def test_markdown_document_to_markdown(self):
        document = MarkdownDocument("Test Document")
        markdown = document.to_markdown()
        self.assertIn("# Test Document", markdown)

    def test_markdown_report_to_markdown(self):
        document = Report("Test Report")
        markdown = document.to_markdown()
        self.assertIn("# Test Report", markdown)

    def test_markdown_report_without_title(self):
        document = Report()
        markdown = document.to_markdown()
        self.assertIn("", markdown)


class TestMarkdownDocumentSection(unittest.TestCase):
    def test_markdown_document_section_init(self):
        section = MarkdownDocumentSection()
        self.assertEqual(section.content, [])


if __name__ == "__main__":
    unittest.main()
