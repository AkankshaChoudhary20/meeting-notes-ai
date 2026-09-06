"""Summary + action-item extraction via the Anthropic Claude API.

Transcription is fully local/offline (see transcription.py); this is the one
step in the pipeline that calls out to a cloud API, and only text (the
transcript) is sent — never the audio itself.
"""
import json
import logging
from typing import List, TypedDict

import anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

ACTION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "A concise summary of the meeting, 3-6 sentences.",
        },
        "action_items": {
            "type": "array",
            "description": "Concrete follow-up tasks mentioned in the meeting.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What needs to be done.",
                    },
                    "owner": {
                        "type": ["string", "null"],
                        "description": (
                            "The person named as responsible for this item, "
                            "if the transcript mentions one. Null otherwise."
                        ),
                    },
                },
                "required": ["description", "owner"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "action_items"],
    "additionalProperties": False,
}


class ActionItemDict(TypedDict):
    description: str
    owner: str | None


class MeetingAnalysis(TypedDict):
    summary: str
    action_items: List[ActionItemDict]


def analyze_transcript(transcript: str) -> MeetingAnalysis:
    """Ask Claude for a summary + structured action items for a transcript.

    Raises RuntimeError if ANTHROPIC_API_KEY is not configured, and
    anthropic.APIError subclasses on request failures (see error handling in
    main.py's background task, which catches and records failures per-meeting
    rather than crashing the process).
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if not transcript.strip():
        return {"summary": "(No speech detected in the audio.)", "action_items": []}

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=(
            "You analyze meeting transcripts. Produce a concise, factual summary "
            "and extract concrete action items. Only include an action item if the "
            "transcript clearly describes a task someone should follow up on. Only "
            "set an owner if a specific person is named as responsible for that "
            "item; otherwise leave owner null. Do not invent details not present "
            "in the transcript."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Here is a meeting transcript:\n\n{transcript}",
            }
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": ACTION_ITEM_SCHEMA,
            }
        },
    )

    if response.stop_reason == "refusal":
        logger.warning("Claude refused to analyze this transcript")
        return {
            "summary": "(Summary unavailable — the request was declined.)",
            "action_items": [],
        }

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise RuntimeError("Claude response contained no text content")

    data = json.loads(text_block.text)
    action_items: List[ActionItemDict] = [
        {"description": item["description"], "owner": item.get("owner")}
        for item in data.get("action_items", [])
    ]
    return {"summary": data["summary"], "action_items": action_items}
