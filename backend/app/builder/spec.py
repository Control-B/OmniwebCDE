"""The application specification that templates render into code.

A model (the architect agent) or the deterministic parser produces an AppSpec; templates are the
only thing that turns it into files, so every generated app has a known, testable structure.
"""

import hashlib
import keyword
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FieldType = Literal["string", "text", "number", "boolean", "date", "email"]
Target = Literal["web", "api", "mobile"]
RESERVED_ENTITIES = {"User", "App", "Base", "Settings", "Row", "Field", "Entity", "Session", "Auth"}
RESERVED_FIELDS = {
    "id", "created_at", "owner_id", "password", "password_hash", "metadata", "registry", "type", "json", "dict",
    "copy", "schema", "validate", "fields", "query", "constructor", "prototype", "toString",
}
PALETTE = ["#4f46e5", "#0d9488", "#db2777", "#ea580c", "#2563eb", "#7c3aed", "#059669", "#dc2626"]
COLOR_WORDS = {
    "blue": "#2563eb", "indigo": "#4f46e5", "purple": "#7c3aed", "violet": "#7c3aed", "pink": "#db2777",
    "red": "#dc2626", "orange": "#ea580c", "amber": "#d97706", "yellow": "#ca8a04", "green": "#16a34a",
    "emerald": "#059669", "teal": "#0d9488", "cyan": "#0891b2", "black": "#18181b", "gray": "#52525b", "grey": "#52525b",
}


def snake(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def pascal(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", value) if part)


def pluralize(word: str) -> str:
    lower = word.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and lower[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def singularize(word: str) -> str:
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if lower.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if lower.endswith("s") and not lower.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


class FieldSpec(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    label: str = Field(min_length=1, max_length=60)
    type: FieldType = "string"
    required: bool = False

    @field_validator("name")
    @classmethod
    def not_reserved(cls, value: str) -> str:
        if value in RESERVED_FIELDS or keyword.iskeyword(value) or value.startswith("model_"):
            raise ValueError(f"'{value}' is reserved")
        return value


class EntitySpec(BaseModel):
    name: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{0,40}$")
    label: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    fields: list[FieldSpec] = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def not_reserved(cls, value: str) -> str:
        if value in RESERVED_ENTITIES:
            raise ValueError(f"'{value}' is a reserved entity name")
        return value

    @model_validator(mode="after")
    def unique_fields(self) -> "EntitySpec":
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.name} has duplicate fields")
        return self

    @property
    def table(self) -> str:
        return snake(pluralize(self.name))

    @property
    def slug(self) -> str:
        return self.table.replace("_", "-")

    @property
    def title_field(self) -> str:
        return self.fields[0].name


class AppSpec(BaseModel):
    version: int = 1
    name: str = Field(min_length=2, max_length=60)
    tagline: str = Field(default="", max_length=160)
    targets: list[Target] = Field(min_length=1)
    accent: str = Field(default="#4f46e5", pattern=r"^#[0-9a-fA-F]{6}$")
    auth: bool = False
    roles: list[str] = Field(default_factory=list, max_length=8)
    entities: list[EntitySpec] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def consistent(self) -> "AppSpec":
        names = [e.name for e in self.entities]
        if len(names) != len(set(names)):
            raise ValueError("Entity names must be unique")
        if self.auth and "api" not in self.targets:
            self.auth = False
        self.targets = [t for t in ("web", "api", "mobile") if t in self.targets]
        return self

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")[:40] or "app"

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()[:12]


def F(name: str, label: str, type_: FieldType = "string", required: bool = False) -> FieldSpec:  # noqa: N802
    return FieldSpec(name=name, label=label, type=type_, required=required)


# Entities the deterministic parser recognizes. Keys are matched against singular nouns.
KNOWN_ENTITIES: dict[str, tuple[str, str, list[FieldSpec]]] = {
    "task": ("Task", "Work to be done", [F("title", "Title", required=True), F("status", "Status"), F("due_date", "Due date", "date"), F("notes", "Notes", "text")]),
    "project": ("Initiative", "Projects and initiatives", [F("name", "Name", required=True), F("owner", "Owner"), F("deadline", "Deadline", "date"), F("summary", "Summary", "text")]),
    "tenant": ("Tenant", "People renting a unit", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("phone", "Phone"), F("unit", "Unit")]),
    "landlord": ("Landlord", "Property owners", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("phone", "Phone")]),
    "property": ("Property", "Buildings and units", [F("name", "Name", required=True), F("address", "Address"), F("units", "Units", "number")]),
    "rent": ("RentPayment", "Rent collected", [F("tenant_name", "Tenant", required=True), F("amount", "Amount", "number", True), F("paid_on", "Paid on", "date"), F("status", "Status")]),
    "payment": ("Payment", "Money received", [F("payer", "Payer", required=True), F("amount", "Amount", "number", True), F("paid_on", "Paid on", "date"), F("method", "Method")]),
    "maintenance": ("MaintenanceRequest", "Repairs and upkeep", [F("title", "Title", required=True), F("description", "Description", "text"), F("priority", "Priority"), F("status", "Status")]),
    "request": ("Request", "Incoming requests", [F("title", "Title", required=True), F("details", "Details", "text"), F("status", "Status")]),
    "booking": ("Booking", "Reservations", [F("client_name", "Client", required=True), F("date", "Date", "date", True), F("service", "Service"), F("notes", "Notes", "text")]),
    "appointment": ("Appointment", "Scheduled appointments", [F("client_name", "Client", required=True), F("date", "Date", "date", True), F("time", "Time"), F("service", "Service")]),
    "stylist": ("Stylist", "Team members taking appointments", [F("full_name", "Full name", required=True), F("specialty", "Specialty"), F("phone", "Phone")]),
    "service": ("Service", "What you offer", [F("name", "Name", required=True), F("price", "Price", "number"), F("duration_minutes", "Duration (minutes)", "number")]),
    "product": ("Product", "Things you sell or stock", [F("name", "Name", required=True), F("sku", "SKU"), F("price", "Price", "number"), F("stock", "In stock", "number")]),
    "inventory": ("StockItem", "Inventory on hand", [F("name", "Name", required=True), F("sku", "SKU"), F("quantity", "Quantity", "number", True), F("location", "Location")]),
    "supplier": ("Supplier", "Vendors you buy from", [F("name", "Name", required=True), F("contact_email", "Contact email", "email"), F("phone", "Phone")]),
    "order": ("Order", "Customer orders", [F("reference", "Reference", required=True), F("customer", "Customer"), F("total", "Total", "number"), F("status", "Status")]),
    "purchase": ("PurchaseOrder", "Orders placed with suppliers", [F("reference", "Reference", required=True), F("supplier", "Supplier"), F("total", "Total", "number"), F("expected_on", "Expected on", "date")]),
    "customer": ("Customer", "People you serve", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("phone", "Phone"), F("notes", "Notes", "text")]),
    "client": ("Client", "Your clients", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("company", "Company")]),
    "contact": ("Contact", "People you keep in touch with", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("phone", "Phone")]),
    "lead": ("Lead", "Potential customers", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("source", "Source"), F("stage", "Stage")]),
    "deal": ("Deal", "Sales opportunities", [F("title", "Title", required=True), F("value", "Value", "number"), F("stage", "Stage"), F("close_date", "Close date", "date")]),
    "invoice": ("Invoice", "Bills sent to clients", [F("number", "Number", required=True), F("client", "Client"), F("amount", "Amount", "number", True), F("due_date", "Due date", "date"), F("paid", "Paid", "boolean")]),
    "expense": ("Expense", "Money spent", [F("description", "Description", required=True), F("amount", "Amount", "number", True), F("spent_on", "Date", "date"), F("category", "Category")]),
    "document": ("Document", "Files and paperwork", [F("title", "Title", required=True), F("category", "Category"), F("link", "Link"), F("notes", "Notes", "text")]),
    "employee": ("Employee", "Your team", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("role", "Role"), F("start_date", "Start date", "date")]),
    "member": ("Member", "Community members", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("joined_on", "Joined on", "date")]),
    "event": ("Event", "Things happening", [F("title", "Title", required=True), F("date", "Date", "date", True), F("location", "Location"), F("description", "Description", "text")]),
    "habit": ("Habit", "Routines to build", [F("name", "Name", required=True), F("frequency", "Frequency"), F("target_per_week", "Target per week", "number")]),
    "check": ("CheckIn", "Daily check-ins", [F("habit", "Habit", required=True), F("date", "Date", "date", True), F("done", "Done", "boolean"), F("note", "Note", "text")]),
    "streak": ("Streak", "Consecutive days", [F("habit", "Habit", required=True), F("days", "Days", "number")]),
    "reminder": ("Reminder", "Nudges at the right time", [F("title", "Title", required=True), F("remind_at", "Remind at", "date"), F("done", "Done", "boolean")]),
    "tool": ("Tool", "Tools available to borrow", [F("name", "Name", required=True), F("category", "Category"), F("condition", "Condition"), F("available", "Available", "boolean")]),
    "loan": ("Loan", "Items currently borrowed", [F("item", "Item", required=True), F("borrower", "Borrower", required=True), F("due_date", "Due date", "date"), F("returned", "Returned", "boolean")]),
    "equipment": ("Equipment", "Equipment you track", [F("name", "Name", required=True), F("serial_number", "Serial number"), F("location", "Location")]),
    "ticket": ("Ticket", "Support requests", [F("subject", "Subject", required=True), F("requester", "Requester"), F("priority", "Priority"), F("status", "Status")]),
    "recipe": ("Recipe", "Dishes and how to make them", [F("title", "Title", required=True), F("servings", "Servings", "number"), F("instructions", "Instructions", "text")]),
    "ingredient": ("Ingredient", "What goes into recipes", [F("name", "Name", required=True), F("unit", "Unit"), F("quantity", "Quantity", "number")]),
    "student": ("Student", "Learners", [F("full_name", "Full name", required=True), F("email", "Email", "email"), F("grade", "Grade")]),
    "course": ("Course", "Classes offered", [F("title", "Title", required=True), F("teacher", "Teacher"), F("starts_on", "Starts on", "date")]),
    "class": ("ClassSession", "Scheduled classes", [F("title", "Title", required=True), F("date", "Date", "date", True), F("instructor", "Instructor"), F("capacity", "Capacity", "number")]),
    "note": ("Note", "Things to remember", [F("title", "Title", required=True), F("body", "Body", "text")]),
    "post": ("Post", "Articles and updates", [F("title", "Title", required=True), F("body", "Body", "text"), F("published", "Published", "boolean")]),
    "message": ("Message", "Conversations", [F("subject", "Subject", required=True), F("sender", "From"), F("body", "Body", "text")]),
    "vehicle": ("Vehicle", "Fleet vehicles", [F("name", "Name", required=True), F("plate", "Plate"), F("mileage", "Mileage", "number")]),
    "patient": ("Patient", "People in your care", [F("full_name", "Full name", required=True), F("date_of_birth", "Date of birth", "date"), F("phone", "Phone")]),
}
ALIASES = {"lend": "loan", "lends": "loan", "lending": "loan", "borrow": "loan", "borrows": "loan", "borrowing": "loan", "rental": "booking", "reservation": "booking", "reservations": "booking", "staff": "employee", "team": "employee"}
COMPOUND_TAILS = {"maintenance": {"request"}, "purchase": {"order"}, "rent": {"payment", "collection"}, "support": {"ticket"}}
ROLE_WORDS = ["admin", "landlord", "tenant", "client", "staff", "manager", "customer", "teacher", "student", "member", "accountant", "stylist", "neighbour", "neighbor"]


def _accent(prompt: str, name: str) -> str:
    for word, color in COLOR_WORDS.items():
        if re.search(rf"\b{word}\b", prompt, re.IGNORECASE):
            return color
    return PALETTE[int(hashlib.sha256(name.encode()).hexdigest(), 16) % len(PALETTE)]


def _targets(template: str, prompt: str) -> list[Target]:
    mobile = bool(re.search(r"\b(mobile|ios|android|expo|react native|phone app)\b", prompt, re.IGNORECASE))
    return {
        "react-web": ["web"],
        "fastapi-backend": ["api"],
        "expo-mobile": ["mobile"],
        "full-stack": ["web", "api", "mobile"] if mobile else ["web", "api"],
    }.get(template, ["web"])  # type: ignore[return-value]


def _generic_entity(noun: str) -> EntitySpec | None:
    name = pascal(singularize(noun))[:40]
    if not name or not name[0].isalpha() or name in RESERVED_ENTITIES:
        return None
    return EntitySpec(name=name, label=pluralize(name), fields=[F("name", "Name", required=True), F("status", "Status"), F("notes", "Notes", "text")])


def heuristic_spec(prompt: str, template: str, name: str) -> AppSpec:
    """Deterministic spec from the prompt. Used when no AI provider is configured."""
    text = prompt.lower()
    found: list[EntitySpec] = []
    words = re.findall(r"[a-z]+", text)
    for index, word in enumerate(words):
        key = ALIASES.get(word, singularize(word))
        previous = singularize(words[index - 1]) if index else ""
        if key in COMPOUND_TAILS.get(previous, set()):
            continue
        if key in KNOWN_ENTITIES:
            entity_name, description, fields = KNOWN_ENTITIES[key]
            if entity_name not in {e.name for e in found}:
                found.append(EntitySpec(name=entity_name, label=pluralize(re.sub(r"(?<!^)(?=[A-Z])", " ", entity_name)), description=description, fields=fields))
    if not found:
        tail = re.search(r"\b(?:with|manage|track|tracking|for managing|of)\s+([a-z ,]+)", text)
        if tail:
            for chunk in re.split(r",|\band\b", tail.group(1)):
                noun = chunk.strip().split(" ")[-1] if chunk.strip() else ""
                entity = _generic_entity(noun) if len(noun) > 2 else None
                if entity and entity.name not in {e.name for e in found}:
                    found.append(entity)
    if not found:
        found.append(EntitySpec(name="Item", label="Items", description="Things you track", fields=[F("name", "Name", required=True), F("status", "Status"), F("notes", "Notes", "text")]))
    targets = _targets(template, prompt)
    auth = "api" in targets and bool(re.search(r"\b(log ?in|sign ?in|accounts?|users?|auth|portal|roles?|permissions?|members?)\b", text))
    roles = [r.replace("neighbor", "neighbour") for r in ROLE_WORDS if re.search(rf"\b{r}s?\b", text)]
    tagline = re.sub(r"\s+", " ", prompt.strip())[:157]
    return AppSpec(
        name=name[:60] if len(name) >= 2 else "My app",
        tagline=tagline + ("…" if len(prompt.strip()) > 157 else ""),
        targets=targets,
        accent=_accent(prompt, name),
        auth=auth,
        roles=list(dict.fromkeys(roles))[:8],
        entities=found[:8],
    )


ARCHITECT_SYSTEM_PROMPT = (
    "You are Omniweb's application architect. Convert the conversation into an application specification. "
    "Respond with a single JSON object and nothing else, matching this shape: "
    '{"name": str, "tagline": str (<=160 chars), "targets": ["web"|"api"|"mobile", ...], "accent": "#rrggbb", '
    '"auth": bool, "roles": [str], "entities": [{"name": PascalCase singular, "label": plural title, "description": str, '
    '"fields": [{"name": snake_case, "label": str, "type": "string"|"text"|"number"|"boolean"|"date"|"email", "required": bool}]}]}. '
    "Use at most 8 entities and 10 fields each. Do not include id, created_at, owner_id, or password fields. "
    "Do not use the entity names User, App, Settings, Session, or Auth. Keep the targets you are given unless the user asked otherwise."
)


def parse_model_spec(content: str, fallback: AppSpec) -> AppSpec | None:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        data.setdefault("targets", fallback.targets)
        data.setdefault("name", fallback.name)
        return AppSpec.model_validate(data)
    except (ValueError, TypeError):
        return None
