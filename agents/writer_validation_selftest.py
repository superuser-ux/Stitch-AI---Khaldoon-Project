#!/usr/bin/env python3
"""Focused offline checks for writer output validation and served-route identity."""

from run_writers import (
    ProviderError,
    StageRunner,
    _resolved_execution_identity,
    arabic_content_violations,
)


class _Client:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def complete(self, _system, _user):
        if self.error:
            raise ProviderError(self.error)
        return self.result


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


check(
    "valid Palestinian Arabic passes",
    arabic_content_violations({
        "topic_angle": "هاد الخوف مش حماية، هو تعب مؤجل.",
        "hook_text": "خوفك مش عم يحميك",
        "rationale_ar": "زاوية واضحة ومرتبطة بالجرح.",
    }) == [],
)

leaks = arabic_content_violations({
    "topic_angle": "هاد الخوف بيcause تعب كبير",
    "hook_text": "خايف إني أ失败",
    "rationale_ar": "",
})
check("Latin leakage is rejected", "topic_angle:latin_word" in leaks)
check("foreign-script leakage is rejected", "hook_text:foreign_script" in leaks)

runner = StageRunner("topic", [
    ("groq:first", _Client(error="synthetic failure")),
    ("groq:served-model", _Client(result="{}")),
])
runner.complete("system", "user")
check(
    "served fallback identity is exact",
    _resolved_execution_identity(runner) == ("groq", "served-model"),
)

print("ALL WRITER VALIDATION CHECKS PASSED")
