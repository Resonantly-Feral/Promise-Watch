"""Pipeline step 1, Capture: read the declared bundle into sources.

No AI here. Every chat line and every non-empty document line becomes one
Source with its source type (rule 1). Attachment lines are matched to the
documents in the bundle; an attachment that is not in the bundle is marked
not provided and turned into an outside-bundle statement (rule 18).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from promisewatch.model import MYT, Source, SourceType, Statement, StatementKind

CHAT_LINE = re.compile(r"^(\d{2}/\d{2}/\d{4}), (\d{2}:\d{2}) - ([^:]+): (.*)$")
ATTACHMENT = re.compile(r"^(\S+)\.(\w+) \(file attached\)$")


@dataclass(frozen=True)
class Line:
    """A captured source plus what capture knows about it."""

    source: Source
    channel: str
    said_at: datetime | None = None  # chat lines only
    speaker: str | None = None  # the person, e.g. "Puan Aina"
    not_provided: bool = False  # an attachment missing from the bundle
    attachment_of: str | None = None  # the document id this line attaches


@dataclass
class Captured:
    bundle_id: str
    user: str
    now: datetime
    near_window: timedelta
    lines: list[Line] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)  # outside-bundle
    parties: list[str] = field(default_factory=list)
    answer_key: Path | None = None

    def source(self, source_id: str) -> Source:
        return self.by_id[source_id].source

    @property
    def by_id(self) -> dict[str, Line]:
        return {l.source.id: l for l in self.lines}


def parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%d/%m/%Y %H:%M").replace(tzinfo=MYT)


def party_of(sender: str) -> tuple[str, str]:
    """'Puan Aina (Syarikat Hijau)' -> ('Syarikat Hijau', 'Puan Aina')."""
    m = re.match(r"^(.*?)\s*\((.+)\)$", sender.strip())
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return sender.strip(), sender.strip()


def doc_number(filename: str) -> str:
    """'CJ-Q-0217_quotation.txt' or 'CJ-Q-0217.pdf' -> 'CJ-Q-0217'."""
    return Path(filename).stem.split("_")[0]


def capture(bundle_toml: Path) -> Captured:
    root = bundle_toml.parent
    spec = tomllib.loads(bundle_toml.read_text())
    cap = Captured(
        bundle_id=spec["id"],
        user=spec["user"],
        now=parse_time(spec["reference_time"]),
        near_window=timedelta(days=spec.get("near_window_days", 7)),
    )
    if "answer_key" in spec:
        cap.answer_key = root / spec["answer_key"]["file"]

    docs = {doc_number(d["file"]): d for d in spec.get("documents", [])}
    attached_in: dict[str, str] = {}  # document number -> chat channel
    parties: list[str] = [cap.user]

    for chat in spec.get("chats", []):
        channel = Path(chat["file"]).stem
        for n, raw in enumerate((root / chat["file"]).read_text().splitlines(), 1):
            if not raw.strip():
                continue
            m = CHAT_LINE.match(raw)
            if not m:
                raise ValueError(f"{chat['file']}:{n}: not a chat line: {raw!r}")
            day, clock, sender, text = m.groups()
            party, speaker = party_of(sender)
            if party not in parties:
                parties.append(party)
            sid = f"{channel}:{n}"
            line = Line(
                Source(sid, SourceType.MESSAGE, text, party),
                channel,
                said_at=parse_time(f"{day} {clock}"),
                speaker=speaker,
            )
            att = ATTACHMENT.match(text)
            if att:
                number = doc_number(att.group(0).split(" ")[0])
                if number in docs:
                    attached_in[number] = channel
                    line = Line(line.source, channel, line.said_at, speaker,
                                attachment_of=number)
                else:
                    line = Line(line.source, channel, line.said_at, speaker,
                                not_provided=True)
                    cap.statements.append(Statement(StatementKind.OUTSIDE_BUNDLE, sid))
            cap.lines.append(line)

    for number, d in docs.items():
        issuer = d["issuer"]
        if issuer not in parties:
            parties.append(issuer)
        channel = attached_in.get(number, Path(d["file"]).stem)
        stem = Path(d["file"]).stem
        for n, raw in enumerate((root / d["file"]).read_text().splitlines(), 1):
            if raw.strip():
                cap.lines.append(Line(
                    Source(f"{stem}:{n}", SourceType.DOCUMENT, raw.strip(), issuer),
                    channel,
                ))

    cap.parties = parties
    return cap
