import json
import anthropic
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.middleware.auth import verify_token
from app.agent.tools import TOOL_DEFINITIONS, run_tool
from app.config import settings

router = APIRouter(prefix="/agent", tags=["agent"])

# This is the Anthropic client — it reads ANTHROPIC_API_KEY from env automatically
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)



class ChatMessage(BaseModel):
    role: str      # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@router.post("/chat")
def chat(
    data: ChatRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    current_month = datetime.utcnow().strftime("%Y-%m")

    system_prompt = f"""You are Subtrack's financial assistant. Today's date is {today}. The current month is {current_month}.

You have access to the user's real financial data through tools.

Rules:
- Always use tools to get real data before answering financial questions. Never guess amounts.
- When the user asks about "this month", always use {current_month} as the month parameter.
- Be concise. One or two sentences is usually enough.
- If asked to create something, do it and confirm it was done.
- When a user can't afford something, offer to create a savings goal.
- Always refer to amounts in the user's base currency unless they specify otherwise.
- Never make up financial data. If you don't have it, say so.
- Subtrack is not licensed to give financial product advice. Never recommend or comment on
  the merits of investments, shares, ETFs, crypto, super funds, insurance, or specific bank
  products, even if asked directly. Say it's outside what Subtrack does and move on.
- You can always talk about the user's own cashflow: what they're committed to, what share of
  their income it takes, what changed since last month, and whether a given cost looks high
  relative to their own history. That is the job.

Personality: Direct, helpful, occasionally dry. Not overly enthusiastic."""

    # Build the messages list from history + new message
    # Claude needs the full conversation history each time —
    # it has no memory between requests, so we pass it all in
    messages = [
        {"role": m.role, "content": m.content}
        for m in data.history
    ]
    messages.append({"role": "user", "content": data.message})

    # ── Agent loop ────────────────────────────────────────────────────────
    # We loop until Claude gives a final text response.
    # Max 10 iterations — safety net to prevent infinite loops.

    for _ in range(10):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages
        )

        # stop_reason tells us why Claude stopped:
        # "end_turn"   → Claude is done, has a final answer
        # "tool_use"   → Claude wants to call one or more tools

        if response.stop_reason == "end_turn":
            # Extract the text from the response content blocks
            final_text = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "I couldn't generate a response."
            )
            return {"reply": final_text}

        if response.stop_reason == "tool_use":
            # Add Claude's response to the messages list
            # (including its tool_use blocks — Claude needs to see its own requests)
            messages.append({"role": "assistant", "content": response.content})

            # Process every tool Claude requested
            # Claude can request multiple tools in one turn
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    # Run the actual Python function
                    result = run_tool(block.name, block.input, db, user_id)

                    # Package the result in the format Claude expects
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,   # must match the request id
                        "content": json.dumps(result)
                    })

            # Send all tool results back to Claude in one message
            messages.append({"role": "user", "content": tool_results})

            # Loop continues — Claude will now reason over the results

    # If we hit 10 iterations without a final answer, something went wrong
    raise HTTPException(status_code=500, detail="Agent did not complete in time.")