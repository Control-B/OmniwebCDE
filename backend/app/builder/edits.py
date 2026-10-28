"""Turns plain-language change requests into spec changes without a model.

This covers the common structural edits (fields, entities, names, colors, sign-in, targets). When
an AI provider is configured, the edit agent handles everything else; the result is always a new
AppSpec that templates render, so edits stay inside the tested structure.
"""

import re
from dataclasses import dataclass, field

from .spec import (
    COLOR_WORDS,
    KNOWN_ENTITIES,
    AppSpec,
    EntitySpec,
    F,
    FieldSpec,
    pascal,
    pluralize,
    singularize,
    snake,
)

ARTICLES = r"(?:an?\s+|the\s+|new\s+|some\s+)*"
FIELD_WORDS = r"(?:fields?|columns?|properties|property|attributes?|inputs?)"
ENTITY_WORDS = r"(?:entity|entities|tables?|pages?|sections?|models?|resources?|tabs?|screens?)"


@dataclass
class EditResult:
    spec: AppSpec
    changes: list[str] = field(default_factory=list)
    # Clauses no rule recognized. An edit with none fully covers the request.
    unhandled: list[str] = field(default_factory=list)


def infer_type(name: str) -> str:
    n = name.lower()
    if "email" in n:
        return "email"
    if re.search(
        r"\b(date|due|deadline|birthday|day|when|starts?|ends?)\b|_at$|_on$|_date$",
        n.replace("_", " "),
    ) or n.endswith(("_at", "_on")):
        return "date"
    if (
        re.search(
            r"\b(amount|price|cost|count|quantity|qty|number|age|rating|hours|score|total|budget|salary|rent|fee|capacity|weight|size|minutes|stock)\b",
            n.replace("_", " "),
        )
        and "phone" not in n
    ):
        return "number"
    if re.search(
        r"^(is|has|can)_|\b(paid|done|active|completed|archived|available|approved|published|verified|urgent|featured)\b",
        n.replace("_", " "),
    ):
        return "boolean"
    if re.search(
        r"\b(notes?|description|bio|comments?|details|summary|body|content|instructions|address)\b",
        n.replace("_", " "),
    ):
        return "text"
    return "string"


def _entity(spec: AppSpec, phrase: str) -> EntitySpec | None:
    words = re.sub(r"\b(the|a|an|each|every|all|my|our)\b", " ", phrase.lower()).split()
    if not words:
        return None
    candidates = {
        " ".join(words),
        singularize(" ".join(words)),
        "".join(words),
        singularize("".join(words)),
        words[-1],
        singularize(words[-1]),
    }
    for entity in spec.entities:
        names = {
            entity.name.lower(),
            entity.label.lower(),
            entity.table.replace("_", " "),
            entity.table.replace("_", ""),
            singularize(entity.label.lower()),
        }
        names |= {re.sub(r"(?<!^)(?=[A-Z])", " ", entity.name).lower()}
        if candidates & names:
            return entity
    return None


def _field(entity: EntitySpec, phrase: str) -> FieldSpec | None:
    key = snake(re.sub(r"\b(the|a|an)\b", " ", phrase))
    for f in entity.fields:
        if key in {f.name, snake(f.label)} or snake(singularize(key)) == f.name:
            return f
    return None


def _new_field(phrase: str, required: bool = False) -> FieldSpec | None:
    phrase = re.sub(
        rf"\b(the|a|an|new|optional|required|{FIELD_WORDS})\b", " ", phrase, flags=re.IGNORECASE
    ).strip()
    name = snake(phrase)[:40]
    if not name or not name[0].isalpha():
        return None
    try:
        return FieldSpec(
            name=name,
            label=phrase.strip()[:1].upper() + phrase.strip()[1:60],
            type=infer_type(name),
            required=required,
        )  # type: ignore[arg-type]
    except ValueError:
        return None


def _new_entity(phrase: str) -> EntitySpec | None:
    phrase = re.sub(rf"\b(the|a|an|new|{ENTITY_WORDS})\b", " ", phrase, flags=re.IGNORECASE).strip()
    if not phrase:
        return None
    key = singularize(phrase.split()[-1].lower())
    if len(phrase.split()) == 1 and key in KNOWN_ENTITIES:
        name, description, fields = KNOWN_ENTITIES[key]
        return EntitySpec(
            name=name,
            label=pluralize(re.sub(r"(?<!^)(?=[A-Z])", " ", name)),
            description=description,
            fields=fields,
        )
    name = pascal(
        " ".join(
            singularize(w) if i == len(phrase.split()) - 1 else w
            for i, w in enumerate(phrase.split())
        )
    )[:40]
    try:
        return EntitySpec(
            name=name,
            label=pluralize(re.sub(r"(?<!^)(?=[A-Z])", " ", name)),
            fields=[
                F("name", "Name", required=True),
                F("status", "Status"),
                F("notes", "Notes", "text"),
            ],
        )
    except ValueError:
        return None


def _color(value: str) -> str | None:
    value = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    return next(
        (hex_ for word, hex_ in COLOR_WORDS.items() if re.search(rf"\b{word}\b", value)), None
    )


def _clauses(instruction: str) -> list[str]:
    parts = re.split(
        r"(?:[.;\n]|,?\s+\band then\b|,\s*and\s+(?=add|remove|delete|drop|rename|make|change|call|track|include|use|set|let))",
        instruction,
    )
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def apply_instruction(
    spec: AppSpec, instruction: str, notes: list[str] | None = None
) -> EditResult | None:
    """Returns the edited spec and a description of each change, or None when nothing changed.

    Requests that were understood but are already satisfied are described in `notes`, when given."""
    data = spec.model_copy(deep=True)
    changes: list[str] = []
    notes = notes if notes is not None else []
    unhandled: list[str] = []
    for clause in _clauses(instruction):
        text = clause.strip()
        low = text.lower()
        notes_before = len(notes)

        if m := re.search(
            r"\b(?:rename|call|name)\s+(?:the\s+)?(?:app|application|project|site)\s+(?:to\s+|as\s+)?[\"“']?([^\"”']{2,60})[\"”']?$",
            text,
            re.IGNORECASE,
        ):
            data.name = m.group(1).strip()
            changes.append(f"Renamed the app to {data.name}")
            continue
        if m := re.search(
            r"\brename\s+(?:the\s+)?(.+?)\s+(?:to|as)\s+[\"“']?([^\"”']{2,60}?)[\"”']?$",
            text,
            re.IGNORECASE,
        ):
            source, target = m.group(1), m.group(2).strip()
            entity = _entity(data, re.sub(ENTITY_WORDS, "", source))
            if entity:
                entity.label = target[:60]
                changes.append(f"Renamed {entity.name} to “{entity.label}” in the interface")
                continue
            for e in data.entities:
                f = _field(e, re.sub(FIELD_WORDS, "", source))
                if f:
                    f.label = target[:60]
                    changes.append(f"Relabeled {e.name}.{f.name} to “{f.label}”")
                    break
            else:
                if source.lower() in {data.name.lower(), "it", "this"}:
                    data.name = target
                    changes.append(f"Renamed the app to {data.name}")
            continue
        if m := re.search(
            r"\b(?:change|set|update|make)\s+(?:the\s+)?tagline\s+(?:to\s+)?[\"“']?(.{3,160}?)[\"”']?$",
            text,
            re.IGNORECASE,
        ):
            data.tagline = m.group(1).strip()
            changes.append("Updated the tagline")
            continue
        if re.search(r"\b(colou?r|accent|theme|brand|primary)\b", low) or re.match(
            r"^make (it|the app|everything) ", low
        ):
            color = _color(low.split(" to ", 1)[-1] if " to " in low else low)
            if color:
                data.accent = color
                changes.append(f"Changed the accent color to {color}")
                continue
        if re.search(
            r"\b(add|enable|include|require|need|support)\b.*\b(log ?in|sign ?in|sign ?up|auth|authentication|accounts?|passwords?)\b",
            low,
        ):
            if "api" not in data.targets:
                data.targets = [*data.targets, "api"]
                changes.append("Added a FastAPI backend with a database")
            data.auth = True
            changes.append("Added sign-in with email and password")
            continue
        if re.search(
            r"\b(remove|disable|drop|turn off)\b.*\b(log ?in|sign ?in|auth|authentication|accounts?)\b",
            low,
        ):
            data.auth = False
            changes.append("Removed sign-in")
            continue
        if re.search(
            r"\b(add|create|build|include|make)\b.*\b(mobile|ios|android|expo|phone app|native app)\b",
            low,
        ) and not re.search(rf"\b{FIELD_WORDS}\b|\bto\s+(?!the\s+app)", low.split("mobile")[0]):
            if "mobile" not in data.targets:
                data.targets = [*data.targets, "mobile"]
                changes.append("Added an Expo mobile app")
            continue
        if re.search(
            r"\b(add|create|include|use)\b.*\b(backend|api|database|server|persist|postgres)\b", low
        ):
            if "api" not in data.targets:
                data.targets = [*data.targets, "api"]
                changes.append("Added a FastAPI backend with a database")
            continue
        if re.search(r"\b(add|create|include)\b.*\b(web ?app|website|web version|browser)\b", low):
            if "web" not in data.targets:
                data.targets = [*data.targets, "web"]
                changes.append("Added a React web app")
            continue

        if m := re.search(
            r"\bmake\s+(?:the\s+)?(.+?)\s+(?:field\s+)?(required|optional|mandatory)(?:\s+(?:on|for|in)\s+(.+))?$",
            low,
        ):
            scope = [_entity(data, m.group(3))] if m.group(3) else data.entities
            for e in [e for e in scope if e]:
                f = _field(e, m.group(1))
                if f:
                    f.required = m.group(2) != "optional"
                    changes.append(
                        f"Made {e.name}.{f.name} {'required' if f.required else 'optional'}"
                    )
            continue
        if m := re.search(
            rf"\b(?:remove|delete|drop|get rid of)\s+{ARTICLES}(.+?)\s+(?:{FIELD_WORDS}\s+)?(?:from|on|in)\s+{ARTICLES}(.+)$",
            low,
        ):
            entity = _entity(data, m.group(2))
            f = _field(entity, re.sub(FIELD_WORDS, "", m.group(1))) if entity else None
            if entity and f and len(entity.fields) > 1:
                entity.fields = [x for x in entity.fields if x.name != f.name]
                changes.append(f"Removed the {f.label} field from {entity.label}")
            continue
        if m := re.search(
            rf"\b(?:remove|delete|drop|get rid of)\s+{ARTICLES}(.+?)(?:\s+{ENTITY_WORDS})?$", low
        ):
            entity = _entity(data, re.sub(ENTITY_WORDS, "", m.group(1)))
            if entity and len(data.entities) > 1:
                data.entities = [e for e in data.entities if e.name != entity.name]
                changes.append(f"Removed {entity.label}")
                continue
        if m := re.search(
            rf"\b(?:add|include|track|store|record|capture)\s+{ARTICLES}(?:(required|optional)\s+)?(.+?)\s+(?:{FIELD_WORDS}\s+)?(?:to|on|for|in)\s+{ARTICLES}(.+)$",
            low,
        ):
            entity = _entity(data, m.group(3))
            if entity:
                added = []
                for phrase in re.split(r",|\band\b", m.group(2)):
                    if not phrase.strip():
                        continue
                    new = _new_field(phrase, required=m.group(1) == "required")
                    if new and (existing := _field(entity, new.name)):
                        notes.append(f"{entity.label} already have a {existing.label} field.")
                    elif new and len(entity.fields) < 20:
                        entity.fields.append(new)
                        added.append(new.label)
                if added:
                    changes.append(f"Added {', '.join(added)} to {entity.label}")
                continue
        if m := re.search(
            rf"\b(\w+?)s?\s+(?:should|need to|needs to|must)\s+(?:have|include|show|store)\s+{ARTICLES}(.+)$",
            low,
        ):
            entity = _entity(data, m.group(1))
            if entity:
                added = []
                for phrase in re.split(r",|\band\b", m.group(2)):
                    new = _new_field(phrase) if phrase.strip() else None
                    if new and (existing := _field(entity, new.name)):
                        notes.append(f"{entity.label} already have a {existing.label} field.")
                    elif new:
                        entity.fields.append(new)
                        added.append(new.label)
                if added:
                    changes.append(f"Added {', '.join(added)} to {entity.label}")
                continue
        if m := re.search(
            rf"\b(?:add|create|track|manage|include|support)\s+{ARTICLES}(.+?)(?:\s+{ENTITY_WORDS})?$",
            low,
        ):
            added = []
            for phrase in re.split(r",|\band\b", m.group(1)):
                phrase = phrase.strip()
                if not phrase or _entity(data, phrase) or len(data.entities) >= 12:
                    continue
                entity = _new_entity(phrase)
                if entity and entity.name not in {e.name for e in data.entities}:
                    data.entities.append(entity)
                    added.append(entity.label)
            if added:
                changes.append(f"Added {', '.join(added)}")
                continue
        if text and len(notes) == notes_before:
            unhandled.append(text)
    if not changes:
        return None
    try:
        return EditResult(AppSpec.model_validate(data.model_dump()), changes, unhandled)
    except ValueError:
        return None


EDIT_SYSTEM_PROMPT = (
    "You are Omniweb's edit agent. You receive the current application specification as JSON and a change request. "
    "Respond with a single JSON object and nothing else: "
    '{"spec": <the complete updated specification, same shape as the input>, "changes": [short past-tense description of each change], '
    '"files": {"<path>": "<full file content>"} (optional; only for visual or copy changes the specification cannot express)}. '
    "Prefer changing the specification. Only include files under apps/web/src, apps/mobile/src, or apps/mobile/App.tsx, and never "
    "include package.json, lockfiles, migrations, secrets, or configuration files. Keep every existing entity and field unless asked to remove it."
)
