"""Contract validation: the six-section report and the verdict derived from it."""

from __future__ import annotations

import unittest

from ai_loom.models import Verdict
from ai_loom.report import derive_verdict, parse
from support import report  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_conformant_report_parses_all_sections(self):
        parsed = parse(report())
        self.assertTrue(parsed.is_conformant, parsed.violations)
        self.assertEqual(parsed.summary, "Did the work.")
        self.assertEqual(parsed.bullets("Deliverables"), ["a file"])
        self.assertEqual(parsed.bullets("Decisions"), ["chose A over B"])

    def test_missing_section_is_a_violation(self):
        text = report().replace("# Risks\n\n- low: nothing notable\n\n", "")
        parsed = parse(text)
        self.assertFalse(parsed.is_conformant)
        self.assertIn("# Risks", parsed.violations[0])

    def test_out_of_order_sections_are_a_violation(self):
        text = (
            "# Summary\n\ns\n\n# Decisions\n\n- d\n\n# Findings\n\n- f\n\n"
            "# Deliverables\n\n- x\n\n# Risks\n\n- r\n\n# Next Skill\n\nNone\n"
        )
        parsed = parse(text)
        self.assertFalse(parsed.is_conformant)
        self.assertTrue(any("out of contract order" in v for v in parsed.violations))

    def test_empty_report_is_a_violation_not_a_crash(self):
        parsed = parse("")
        self.assertFalse(parsed.is_conformant)
        self.assertEqual(parsed.violations, ["report is empty"])

    def test_headings_tolerate_case_and_punctuation(self):
        text = report().replace("# Next Skill", "# next skill:")
        self.assertTrue(parse(text).is_conformant)

    def test_subsections_do_not_break_parsing(self):
        text = report(deliverables="## Plan\n\n- step one\n- step two")
        parsed = parse(text)
        self.assertTrue(parsed.is_conformant, parsed.violations)
        self.assertEqual(parsed.bullets("Deliverables"), ["step one", "step two"])


class NextSkillTests(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(parse(report(next_skill="coding")).next_skill, "coding")

    def test_name_with_em_dash_reason(self):
        parsed = parse(report(next_skill="fixer — three findings above severity 2"))
        self.assertEqual(parsed.next_skill, "fixer")

    def test_backticked_name(self):
        self.assertEqual(
            parse(report(next_skill="`post-feature-implementation`")).next_skill, "post-feature-implementation"
        )

    def test_bulleted_name(self):
        self.assertEqual(parse(report(next_skill="- reviewer")).next_skill, "reviewer")

    def test_none_variants_resolve_to_none(self):
        for body in ("None", "none", "None — chain complete", "N/A", "None (nothing further)"):
            with self.subTest(body=body):
                self.assertIsNone(parse(report(next_skill=body)).next_skill)

    def test_prose_that_names_no_skill_resolves_to_none(self):
        self.assertIsNone(parse(report(next_skill="Whatever the team decides")).next_skill)


class VerdictTests(unittest.TestCase):
    def test_terminal_report_is_success(self):
        self.assertIs(derive_verdict(parse(report(next_skill="None — done"))), Verdict.SUCCESS)

    def test_routing_onward_is_success(self):
        self.assertIs(derive_verdict(parse(report(next_skill="testing")), "fixer"), Verdict.SUCCESS)

    def test_routing_to_remediation_skill_is_changes_requested(self):
        verdict = derive_verdict(parse(report(next_skill="fixer — 2 findings")), "fixer")
        self.assertIs(verdict, Verdict.CHANGES_REQUESTED)

    def test_routing_to_fixer_without_remediation_configured_is_success(self):
        # The engine, not the parser, decides what to do with an unmodelled edge.
        self.assertIs(derive_verdict(parse(report(next_skill="fixer")), None), Verdict.SUCCESS)

    def test_blocked_report(self):
        verdict = derive_verdict(parse(report(next_skill="None — blocked, need the API contract")))
        self.assertIs(verdict, Verdict.BLOCKED)

    def test_escalation_beats_remediation(self):
        # The precedence that stops a contested point looping a third time.
        verdict = derive_verdict(parse(report(next_skill="fixer — escalate, we disagree")), "fixer")
        self.assertIs(verdict, Verdict.ESCALATE)

    def test_non_conformant_report_is_failed(self):
        self.assertIs(derive_verdict(parse("garbage")), Verdict.FAILED)


if __name__ == "__main__":
    unittest.main()
