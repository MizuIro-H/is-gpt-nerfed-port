"""Port of macOS BackendLocalization.swift: translate complete strings emitted by `nerfed`.

Only app-owned templates are translated; model names, efforts, IDs, user session titles and
unknown external text pass through unchanged. Strings come from the upstream zh-Hans Backend.strings.
"""
from __future__ import annotations

import re
from typing import Callable

_P = {k: re.compile(v) for k, v in {
    "session-title": r"^Session (\d+)$",
    "quote-mismatch-downgrade-a": r"^🎉 Congrats! You've been nerfed! You asked for (\S+); the fingerprint says (\S+) \((\d+%), (\d+)/(\d+) answers\)\. Enjoy the discount you didn't ask for\.$",
    "quote-mismatch-downgrade-b": r"^Great news: your (\S+) session is answering like (\S+) \((\d+%)\)\. Nobody told you, but somebody saved money\. Congrats!$",
    "quote-mismatch-upgrade": r"^Congrats! You've been secretly upgraded: you asked for (\S+), the fingerprint says (\S+) \((\d+%)\)\. Don't tell anyone\.$",
    "quote-mismatch-lateral": r"^Congrats! You've been… re-routed\. You asked for (\S+), the fingerprint says (\S+) \((\d+%)\)\. Same tier, different brain\.$",
    "quote-downgraded-hard": r"^🎉 Congrats! You've been nerfed! Codex's own records say so: (.+?)\. No notice, no refund, no shame\.$",
    "quote-upgraded": r"^🎉 Congrats, and this time we mean it: you've been upgraded\. Codex's own records say so: (.+?)\. Enjoy it while it lasts\.$",
    "quote-match-a": r"^All clear: the fingerprint says (\S+) \((\d+%)\), which is what you asked for\. The model you're paying for actually showed up\. Cherish it\.$",
    "quote-match-b": r"^No downgrade detected: (\S+) at (\d+%)\. Suspiciously honest\. I'll keep watching\.$",
    "quote-suspicious": r"^Hmm\. The fingerprint leans (\S+) \((\d+%)\) over your (\S+) \((\d+%)\), but not confidently enough to call it\. I asked again and it is still murky\. Watching\.$",
    "quote-unlisted": r"^(\S+) isn't in the fingerprint bank yet, so I can only tell you who it looks like: (\S+) \((\d+%)\)\. Not a verdict\.$",
    "quote-invalid": r"^Couldn't get a usable sample: (.+)\. No verdict, no congratulations\.$",
    "quote-settings-downgrade": r"^Heads up: (.+?)\. If that wasn't you clicking, congrats — you've been downgraded!$",
    "quote-nudge": r"^Probe due \((.+?)\)\. Say  (.+?)  in this session, or  (.+?)  to keep it out of your context\.$",
    "probe-due-turns": r"^(\d+) turns since the last probe$",
    "probe-due-minutes": r"^(\d+) min elapsed$",
    "quote-unknown-model": r"^No expected model recorded for this session; the fingerprint says (\S+) \((\d+%)\)\.$",
    "evidence-raw-hidden-model": r"^hidden/internal model (\S+) ran a turn$",
    "evidence-raw-applied-model": r"^thread settings switched model (\S+) → (\S+) \((upgrade|downgrade|lateral)\)$",
    "evidence-raw-silent-model": r"^model (\S+) → (\S+) with no settings change \((upgrade|downgrade|lateral)\)$",
    "evidence-raw-applied-effort": r"^thread settings switched reasoning effort (\S+) → (\S+)$",
    "evidence-raw-silent-effort": r"^reasoning effort (\S+) → (\S+) with no settings change$",
    "evidence-raw-tier": r"^service tier (\S+) → (\S+)$",
    "evidence-raw-context": r"^model context window (\S+) → (\S+)$",
    "evidence-compact-upgraded-settings": r"^Upgraded: (\S+) → (\S+) · via settings$",
    "evidence-compact-upgraded": r"^Upgraded: (\S+) → (\S+)$",
    "evidence-compact-silent-model": r"^Silent model change: (\S+) → (\S+)$",
    "evidence-compact-limit-model": r"^Codex switched model (\S+) → (\S+) at the usage limit \((\d+%)\)$",
    "evidence-compact-settings-model": r"^Settings: model (\S+) → (\S+) · was that you\?$",
    "evidence-compact-silent-effort": r"^Silent effort change: (\S+) → (\S+)$",
    "evidence-compact-limit-effort": r"^Codex switched effort (\S+) → (\S+) at the usage limit \((\d+%)\)$",
    "evidence-compact-settings-effort": r"^Settings: effort (\S+) → (\S+) · was that you\?$",
    "evidence-compact-hidden": r"^Hidden model ran: (\S+)$",
    "evidence-compact-context": r"^Context window (\S+) → (\S+)$",
    "evidence-compact-tier": r"^Tier (\S+) → (\S+)$",
    "report-last-probe": r"^Last probe · (.+)$",
    "report-earlier": r"^Earlier · (.+)$",
    "report-last-attempt": r"^Last attempt · (.+)$",
    "report-fingerprint": r"^Fingerprint · (.*)$",
    "report-evidence": r"^Evidence · (.+)$",
    "report-count": r"^(\d+) of (\d+) answers$",
    "report-rounds": r"^(\d+) rounds$",
    "report-retried-count": r"^retried (\d+)×$",
    "report-seconds": r"^(\d+(?:\.\d+)?) s$",
    "report-client": r"^as (.+)$",
    "report-probe-id": r"^probe (\S+)$",
    "report-declared": r"^(\S+) (\d+%), declared (\d+%)$",
    "report-prediction": r"^(\S+) (\d+%)$",
    "report-account-unknown": r"^(.+), account unknown$",
    "report-account-other": r"^(.+), another account$",
    "error-appserver-transport": r"^codex app-server transport closed: (.+)$",
    "error-appserver-exit": r"^codex app-server exited during (.+)$",
    "error-codex-timeout": r"^codex (\S+) timed out after (\d+)s$",
    "error-codex-method": r"^codex ([^:]+): (.+)$",
    "error-thread-field": r"^thread metadata lacks (\S+)$",
    "error-fork-model": r"^fork settings differ from the thread \((\S+) vs (\S+)\)$",
    "error-probe-tool": r"^probe attempted a tool \(([^()]*)\); no sample accepted$",
    "error-probe-turn-status": r"^probe turn ended with status (\S+)$",
    "error-probe-inference": r"^probe inference failed: (.+)$",
    "error-probe-request": r"^probe requested (.+); refused, no sample accepted$",
    "error-answer-count": r"^answer (\d+): only (\d+) valid integers$",
    "error-unexpected": r"^unexpected error: (.+)$",
    "error-cannot-start-python": r"^cannot start python3: (.+)$",
    "error-dgc-exit": r"^dgc exited with (.+)$",
    "update-failed": r"^failed: (.+)$",
    "update-http": r"^HTTP (\d{3})$",
    "update-version-not-newer": r"^(\S+) is not newer than (\S+)$",
    "update-download": r"^download: (.+)$",
    "update-checksum": r"^checksum: (.+)$",
    "update-extract": r"^extract: (.+)$",
    "update-archive-version": r"^the archive is version (\S+), the release says (\S+)$",
}.items()}

_EXACT = {
    "account hidden": "backend.account.hidden",
    "no usable sample": "backend.no-usable-sample",
    "no usable answer": "backend.no-usable-answer",
    "waiting for the current turn to finish": "backend.waiting-turn",
    "Probing, ephemeral forks in flight…": "backend.probing-forks",
    "No probe yet": "backend.report.no-probe",
    "Earlier": "backend.report.earlier",
    "Last probe": "backend.report.last-probe",
    "Last attempt": "backend.report.last-attempt",
    "Fingerprint": "backend.report.fingerprint",
    "Evidence": "backend.report.evidence",
    "reverted": "backend.report.reverted",
    "Failed": "backend.verdict.failed",
    "Downgraded": "backend.verdict.downgraded",
    "Downgrade": "backend.verdict.downgrade",
    "Upgrade": "backend.verdict.upgrade",
    "Rerouted": "backend.verdict.rerouted",
    "Suspicious": "backend.verdict.suspicious",
    "Match": "backend.verdict.match",
    "Unlisted": "backend.verdict.unlisted",
    "Invalid": "backend.verdict.invalid",
    "Unverified": "backend.verdict.unverified",
    "no release archive found": "backend.update.no-archive",
}

_DEMO_TITLES = {
    "Refactor payment webhooks": "backend.title.demo.payment-webhooks",
    "Investigate flaky CI on main": "backend.title.demo.flaky-ci",
    "Add OAuth device flow": "backend.title.demo.oauth-device-flow",
    "Rewrite the docs site": "backend.title.demo.docs-site",
    "Migrate to Postgres 17": "backend.title.demo.postgres",
    "Write release notes v2.3": "backend.title.demo.release-notes",
}

_ERRORS = {
    "thread is busy": "backend.error.thread-busy",
    "session has no finished turn yet": "backend.error.no-finished-turn",
    "session has no finished turn yet; wait for the current turn to finish": "backend.error.wait-finished-turn",
    "codex returned metadata for a different thread": "backend.error.wrong-thread",
    "session has no persisted history to fork (ephemeral or not saved yet)": "backend.error.no-persisted-history",
    "fork reasoning effort differs from the thread": "backend.error.fork-effort-differs",
    "codex did not create an ephemeral fork of the target thread": "backend.error.fork-not-ephemeral",
    "probe did not return a final text answer": "backend.error.no-final-answer",
}


class BackendL10n:
    def __init__(self, table: dict[str, str]) -> None:
        self.table = table

    # -- helpers

    def f(self, key: str, *args: str) -> str:
        out = self.table.get(key, key)
        for i, a in enumerate(args, 1):
            out = out.replace(f"%{i}$@", a)
        for a in args:
            out = out.replace("%@", a, 1)
        return out

    @staticmethod
    def m(name: str, text: str) -> list[str] | None:
        hit = _P[name].fullmatch(text)
        return list(hit.groups()) if hit else None

    def __call__(self, text: str) -> str:
        if not text or not self.table:
            return text
        if "\n" in text:
            lines = text.split("\n")
            report = lines[0].startswith("is-gpt-nerfed · ")
            return "\n".join(l if report and i == 0 else self.line(l) for i, l in enumerate(lines))
        return self.line(text)

    def line(self, text: str) -> str:
        if text in _EXACT:
            return self.f(_EXACT[text])
        c = self.m("session-title", text)
        if c:
            return self.f("backend.title.session", *c)
        for fn in (self._quote, self._evidence, self._report, self._error, self._update):
            r = fn(text)
            if r is not None:
                return r
        if text in _DEMO_TITLES:
            return self.f(_DEMO_TITLES[text])
        return text

    def _first(self, text: str, cases: list[tuple[str, str, Callable[[list[str]], list[str]] | None]]) -> str | None:
        for pat, key, mapper in cases:
            c = self.m(pat, text)
            if c is not None:
                return self.f(key, *(mapper(c) if mapper else c))
        return None

    def direction(self, v: str) -> str:
        return self.f(f"backend.direction.{v}") if v in ("upgrade", "downgrade", "lateral") else v

    def age(self, v: str) -> str | None:
        hit = re.fullmatch(r"(\d+)([smhd]) ago", v)
        if not hit:
            return None
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[hit.group(2)]
        return self.f(f"backend.report.{unit}-ago", hit.group(1))

    def verdict(self, v: str) -> str | None:
        return self.f(_EXACT[v]) if v in _EXACT else None

    # -- families

    def _quote(self, text: str) -> str | None:
        inner = lambda c: [self.line(c[0])]
        r = self._first(text, [
            ("quote-mismatch-downgrade-a", "backend.quote.mismatch-downgrade-a", None),
            ("quote-mismatch-downgrade-b", "backend.quote.mismatch-downgrade-b", None),
            ("quote-mismatch-upgrade", "backend.quote.mismatch-upgrade", None),
            ("quote-mismatch-lateral", "backend.quote.mismatch-lateral", None),
            ("quote-downgraded-hard", "backend.quote.downgraded-hard", inner),
            ("quote-upgraded", "backend.quote.upgraded", inner),
            ("quote-match-a", "backend.quote.match-a", None),
            ("quote-match-b", "backend.quote.match-b", None),
            ("quote-suspicious", "backend.quote.suspicious", None),
            ("quote-unlisted", "backend.quote.unlisted", None),
            ("quote-invalid", "backend.quote.invalid", inner),
            ("quote-settings-downgrade", "backend.quote.settings-downgrade", inner),
            ("quote-unknown-model", "backend.quote.unknown-model", None),
        ])
        if r is not None:
            return r
        c = self.m("quote-nudge", text)
        if c:
            return self.f("backend.quote.nudge", self._due(c[0]) or c[0], c[1], c[2])
        return None

    def _due(self, v: str) -> str | None:
        if v == "requested":
            return self.f("backend.quote.nudge.why-requested")
        if v == "account changed since the last probe":
            return self.f("backend.quote.nudge.why-account-changed")
        return self._first(v, [("probe-due-turns", "backend.quote.nudge.why-turns", None),
                               ("probe-due-minutes", "backend.quote.nudge.why-minutes", None)])

    def _evidence(self, text: str) -> str | None:
        d = lambda c: [c[0], c[1], self.direction(c[2])]
        if text == "Hidden model ran a turn":
            return self.f("backend.evidence.compact.hidden-model-turn")
        return self._first(text, [
            ("evidence-raw-hidden-model", "backend.evidence.raw.hidden-model", None),
            ("evidence-raw-applied-model", "backend.evidence.raw.applied-model", d),
            ("evidence-raw-silent-model", "backend.evidence.raw.silent-model", d),
            ("evidence-raw-applied-effort", "backend.evidence.raw.applied-effort", None),
            ("evidence-raw-silent-effort", "backend.evidence.raw.silent-effort", None),
            ("evidence-raw-tier", "backend.evidence.raw.tier", None),
            ("evidence-raw-context", "backend.evidence.raw.context", None),
            ("evidence-compact-upgraded-settings", "backend.evidence.compact.upgraded-settings", None),
            ("evidence-compact-upgraded", "backend.evidence.compact.upgraded", None),
            ("evidence-compact-silent-model", "backend.evidence.compact.silent-model", None),
            ("evidence-compact-limit-model", "backend.evidence.compact.limit-model", None),
            ("evidence-compact-settings-model", "backend.evidence.compact.settings-model", None),
            ("evidence-compact-silent-effort", "backend.evidence.compact.silent-effort", None),
            ("evidence-compact-limit-effort", "backend.evidence.compact.limit-effort", None),
            ("evidence-compact-settings-effort", "backend.evidence.compact.settings-effort", None),
            ("evidence-compact-hidden", "backend.evidence.compact.hidden-model", None),
            ("evidence-compact-context", "backend.evidence.compact.context", None),
            ("evidence-compact-tier", "backend.evidence.compact.tier", None),
        ])

    def _report(self, text: str) -> str | None:
        for pat, key in (("report-last-probe", "backend.report.last-probe"), ("report-earlier", "backend.report.earlier"),
                         ("report-last-attempt", "backend.report.last-attempt")):
            c = self.m(pat, text)
            if c:
                return self.f(key) + " · " + self._probe_line(c[0])
        c = self.m("report-fingerprint", text)
        if c:
            return self.f("backend.report.fingerprint") + " · " + c[0]
        c = self.m("report-evidence", text)
        if c:
            rest, reverted = c[0], False
            if rest.endswith(" · reverted"):
                rest, reverted = rest[: -len(" · reverted")], True
            parts = rest.split(" · ")
            age = self.age(parts[-1])
            if age:
                rest = " · ".join(parts[:-1])
            out = self.f("backend.report.evidence") + " · " + self.line(rest)
            if age:
                out += " · " + age
            if reverted:
                out += " · " + self.f("backend.report.reverted")
            return out
        return None

    def _probe_line(self, text: str) -> str:
        parts = text.split(" · ")
        first = self.verdict(parts[0])
        if first is None:
            return text
        out = [first]
        for part in parts[1:]:
            c = self.m("report-account-unknown", part)
            if c and (label := self.verdict(c[0])):
                out.append(self.f("backend.report.account-unknown", label))
                continue
            c = self.m("report-account-other", part)
            if c and (label := self.verdict(c[0])):
                out.append(self.f("backend.report.account-other", label))
                continue
            if part == "retried once":
                out.append(self.f("backend.report.retried-once"))
                continue
            r = self._first(part, [
                ("report-count", "backend.report.count", None),
                ("report-retried-count", "backend.report.retried-count", None),
                ("report-rounds", "backend.report.rounds", None),
                ("report-seconds", "backend.report.seconds", None),
                ("report-client", "backend.report.client", None),
                ("report-probe-id", "backend.report.probe-id", None),
                ("report-declared", "backend.report.prediction-declared", None),
            ])
            if r is None:
                c = self.m("report-prediction", part)
                r = c[0] + " " + c[1] if c else self.age(part) or self.line(part)
            out.append(r)
        return " · ".join(out)

    def _error(self, text: str) -> str | None:
        if text in _ERRORS:
            return self.f(_ERRORS[text])
        inner = lambda c: [self.line(c[0])]
        return self._first(text, [
            ("error-appserver-transport", "backend.error.appserver-transport", None),
            ("error-appserver-exit", "backend.error.appserver-exit", None),
            ("error-codex-timeout", "backend.error.codex-timeout", None),
            ("error-codex-method", "backend.error.codex-method", lambda c: [c[0], self.line(c[1])]),
            ("error-thread-field", "backend.error.thread-field", None),
            ("error-fork-model", "backend.error.fork-model", None),
            ("error-probe-tool", "backend.error.probe-tool", None),
            ("error-probe-turn-status", "backend.error.probe-turn-status", None),
            ("error-probe-inference", "backend.error.probe-inference", inner),
            ("error-probe-request", "backend.error.probe-request", None),
            ("error-answer-count", "backend.error.answer-count", None),
            ("error-unexpected", "backend.error.unexpected", inner),
            ("error-cannot-start-python", "backend.error.cannot-start-python", None),
            ("error-dgc-exit", "backend.error.dgc-exit", None),
        ])

    def _update(self, text: str) -> str | None:
        c = self.m("update-failed", text)
        if c:
            return self.f("backend.update.failed", self._first(c[0], [("update-http", "backend.update.http", None)]) or c[0])
        return None
