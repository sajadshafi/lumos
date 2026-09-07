"""Skill report parsing and contract validation.

Implements the reader side of `.claude/skills/shared/output-format.md`
(contract 1.0.0). Every skill emits the same six `#` sections in the same order;
this module is the only place that knowledge lives, so a contract bump touches
one file.

Validation is strict on purpose. A skill whose report drifts is a defect in the
skill, and the contract says to fix the SKILL.md rather than hand-patch the
report — that only works if drift is detected loudly instead of being silently
tolerated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Verdict

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Summary",
    "Findings",
    "Decisions",
    "Deliverables",
    "Risks",
    "Next Skill",
)

_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")

# `Next Skill` bodies seen in practice: "coding", "`coding`", "None — blocked",
# "None (nothing further)", "fixer — three findings above severity 2".
_NONE_TOKENS = {"none", "n/a", "na", "-", "stop", "end"}

_BLOCKED_MARKERS = ("blocked", "cannot continue", "needs input", "awaiting")
_ESCALATE_MARKERS = ("escalate", "escalation", "human decision", "manual review required")


@dataclass
class SkillReport:
    """A parsed six-section skill report."""

    raw: str
    sections: dict[str, str] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)

    @property
    def is_conformant(self) -> bool:
        return not self.violations

    @property
    def summary(self) -> str:
        return self.sections.get("Summary", "").strip()

    @property
    def next_skill_raw(self) -> str:
        return self.sections.get("Next Skill", "").strip()

    def bullets(self, section: str) -> list[str]:
        """Bullet items from a section, for the structured state record."""
        items: list[str] = []
        for line in self.sections.get(section, "").splitlines():
            match = _BULLET.match(line)
            if match:
                text = match.group(1).strip()
                if text:
                    items.append(text)
        return items

    @property
    def next_skill(self) -> str | None:
        """The recommended successor, or None when the chain ends here."""
        body = self.next_skill_raw
        if not body:
            return None
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if not first:
            return None
        # Strip list markers, then take the token before any separator/reason.
        first = _BULLET.sub(r"\1", first).strip()
        token = re.split(r"\s+[—–-]\s+|\s*[(:,]", first, maxsplit=1)[0]
        token = token.strip().strip("`*_.").strip()
        if not token or token.lower() in _NONE_TOKENS:
            return None
        # A skill identifier is kebab-case per the skills README naming rule.
        if not re.fullmatch(r"[a-z][a-z0-9-]*", token):
            return None
        return token


def parse(text: str) -> SkillReport:
    """Parse report text and record any contract violations found.

    Never raises: a malformed report is data the caller must decide about, and
    the retry policy needs the violations to quote back to the skill.
    """
    report = SkillReport(raw=text)

    if not text or not text.strip():
        report.violations.append("report is empty")
        return report

    matches = list(_HEADING.finditer(text))
    found_order: list[str] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        canonical = _canonical(title)
        if canonical:
            found_order.append(canonical)
            report.sections[canonical] = text[start:end].strip()

    missing = [s for s in REQUIRED_SECTIONS if s not in report.sections]
    if missing:
        report.violations.append("missing required section(s): " + ", ".join(f"# {m}" for m in missing))

    present_expected = [s for s in found_order if s in REQUIRED_SECTIONS]
    expected_sequence = [s for s in REQUIRED_SECTIONS if s in present_expected]
    if present_expected != expected_sequence:
        report.violations.append(
            "sections out of contract order: expected "
            + " -> ".join(expected_sequence)
            + " but found "
            + " -> ".join(present_expected)
        )

    if "Next Skill" in report.sections and not report.next_skill_raw:
        report.violations.append("# Next Skill is present but empty; it must name a skill or 'None' with a reason")

    if "Summary" in report.sections and not report.summary:
        report.violations.append("# Summary is empty")

    return report


def _canonical(title: str) -> str | None:
    """Map a heading to its contract name, tolerating case and punctuation."""
    normalised = re.sub(r"[^a-z ]", "", title.lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    for section in REQUIRED_SECTIONS:
        if normalised == section.lower():
            return section
    return None


def derive_verdict(report: SkillReport, remediation_skill: str | None = None) -> Verdict:
    """Reduce a report to the outcome the engine branches on.

    Precedence is deliberate: escalation beats blocking beats remediation. A
    report that says "escalate — reviewer and fixer disagree" must not be read as
    "loop again", which is exactly the failure the escalation rule exists to
    prevent.
    """
    if not report.is_conformant:
        return Verdict.FAILED

    body = report.next_skill_raw.lower()

    if any(marker in body for marker in _ESCALATE_MARKERS):
        return Verdict.ESCALATE

    next_skill = report.next_skill

    if next_skill is None:
        if any(marker in body for marker in _BLOCKED_MARKERS):
            return Verdict.BLOCKED
        return Verdict.SUCCESS

    if remediation_skill and next_skill == remediation_skill:
        return Verdict.CHANGES_REQUESTED

    return Verdict.SUCCESS
