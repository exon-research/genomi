from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
from typing import Any, Mapping

JsonObject = dict[str, Any]

WELCOME_INTRO = (
    "Ask about symptoms, a diagnosis, a medication, or your genome. "
    "Genomi researches the question and keeps every record and source it used in this workspace."
)


@dataclass(frozen=True)
class StarterCard:
    card_id: str
    label: str
    detail: str
    prompt: str = ""
    source_operation: str = ""
    source_params: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        model: JsonObject = {
            "id": self.card_id,
            "label": self.label,
            "detail": self.detail,
        }
        if self.prompt:
            model["prompt"] = self.prompt
        if self.source_operation:
            model["sourceOperation"] = self.source_operation
        if self.source_params:
            model["sourceParams"] = dict(self.source_params)
        return model


STARTER_CARDS: tuple[StarterCard, ...] = (
    StarterCard(
        card_id="investigate-health-question",
        label="Investigate a health question",
        detail=(
            "Bring symptoms, diagnoses, and test results. Genomi keeps competing explanations, "
            "evidence, and open questions together as the investigation grows."
        ),
        prompt=(
            "I have been dealing with the following: describe your symptoms, when they started, "
            "and anything that makes them better or worse. My diagnoses so far: list them. "
            "Medications I take: list them. What I want to understand: say it in your own words."
        ),
    ),
    StarterCard(
        card_id="review-a-medication",
        label="Review a medication",
        detail="Ask how your genetics could change how a drug you take, or are about to start, works for you.",
        prompt=(
            "How could my genetics affect the way I respond to this medication: name the drug. "
            "I am taking it for: say the reason."
        ),
    ),
    StarterCard(
        card_id="add-genome",
        label="Add your genome",
        detail="Point Genomi at a 23andMe, AncestryDNA, MyHeritage, VCF, or BAM export saved on this computer.",
        source_operation="genomi.parse_source",
    ),
)


def welcome_model() -> JsonObject:
    return {
        "intro": WELCOME_INTRO,
        "cards": [card.to_json() for card in STARTER_CARDS],
    }


def welcome_model_json() -> str:
    return json.dumps(welcome_model(), separators=(",", ":"), sort_keys=True).replace("</", "<\\/")


def welcome_message_markup() -> str:
    return "".join(
        (
            '<div class="message assistant">',
            '<div class="role">GenomiLab</div>',
            '<div class="body">',
            f"<p>{html.escape(WELCOME_INTRO)}</p>",
            '<div class="message-suggestions" data-testid="genomi-chat-suggestions">',
            "".join(_card_markup(card) for card in STARTER_CARDS),
            "</div>",
            "</div>",
            "</div>",
        )
    )


def _card_markup(card: StarterCard) -> str:
    attrs = [
        ('class', 'suggestion-chip'),
        ('type', 'button'),
        ('data-starter-card-id', card.card_id),
    ]
    if card.prompt:
        attrs.append(('data-prompt', card.prompt))
    if card.source_operation:
        attrs.append(('data-source-operation', card.source_operation))
    attr_text = " ".join(_double_quoted_attr(name, value) for name, value in attrs)
    if card.source_params:
        params = json.dumps(dict(card.source_params), separators=(",", ":"), sort_keys=True)
        attr_text += " " + _single_quoted_attr("data-source-params", params)
    return (
        f"<button {attr_text}>"
        f"<strong>{html.escape(card.label)}</strong>"
        f'<span data-starter-card-detail>{html.escape(card.detail)}</span>'
        "</button>"
    )


def _double_quoted_attr(name: str, value: str) -> str:
    return f'{name}="{html.escape(value, quote=True)}"'


def _single_quoted_attr(name: str, value: str) -> str:
    escaped = html.escape(value, quote=False).replace("'", "&#x27;")
    return f"{name}='{escaped}'"
