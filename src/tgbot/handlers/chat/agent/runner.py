import logging
import re
import time
from dataclasses import dataclass

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_export_api_key
from openai import AsyncOpenAI
from sqlalchemy import text

from src.config import settings
from src.database import execute
from src.tgbot.handlers.chat.agent.prompts import SYSTEM_PROMPT
from src.tgbot.handlers.chat.agent.tools import get_tools
from src.tgbot.handlers.chat.ai import _messages_to_text
from src.tgbot.handlers.chat.service import get_latest_chat_messages

logger = logging.getLogger(__name__)

MAX_TURNS = 5

# DSML cleanup: DeepSeek sometimes leaks internal XML as plain text
_DSML_RE = re.compile(r"<[｜\|]DSML[｜\|].*?</[｜\|]DSML[｜\|]\w+>", re.DOTALL)

# Per-agent DeepSeek client (not global — avoids cross-feature bleed with OpenAI calls in ai.py)
_deepseek_client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY or "dummy",
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=60.0,
    max_retries=1,
)

_deepseek_model = OpenAIChatCompletionsModel(
    model="deepseek-chat",
    openai_client=_deepseek_client,
)

# Tracing: export to OpenAI dashboard for observability
if settings.OPENAI_API_KEY:
    set_tracing_export_api_key(settings.OPENAI_API_KEY)


@dataclass
class ChatAgentContext:
    """Runtime context passed to tools via RunContextWrapper."""

    bot: object  # telegram.Bot
    chat_id: int
    user_id: int
    reply_to_message_id: int | None = None


def clean_response(text: str | None) -> str | None:
    """Strip DeepSeek DSML artifacts from response text."""
    if not text:
        return None
    cleaned = _DSML_RE.sub("", text).strip()
    return cleaned or None


async def run_chat_agent(
    bot,
    chat_id: int,
    user_id: int,
    reply_to_message_id: int | None = None,
    trigger_type: str = "mention",
) -> str | None:
    """Run the DeepSeek chat agent. Returns text response or None."""
    if not settings.DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not configured")
        return None

    # Build context from recent messages
    messages_history = await get_latest_chat_messages(chat_id=chat_id, limit=20)
    chat_context = _messages_to_text(messages_history)

    agent_input = (
        f"Вот последние сообщения в чате:\n\n{chat_context}\n\nОтветь на последнее сообщение."
    )

    ctx = ChatAgentContext(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        reply_to_message_id=reply_to_message_id,
    )

    agent = Agent(
        name="ffmemes",
        instructions=SYSTEM_PROMPT,
        model=_deepseek_model,
        tools=get_tools(),
    )

    start_time = time.time()

    try:
        result = await Runner.run(
            starting_agent=agent,
            input=agent_input,
            context=ctx,
            max_turns=MAX_TURNS,
        )
    except Exception as e:
        logger.error("Agent SDK error in chat %s: %s", chat_id, e, exc_info=True)
        return None

    # Extract usage from raw responses
    total_prompt_tokens = 0
    total_completion_tokens = 0
    tool_calls_count = 0
    for raw in result.raw_responses:
        if hasattr(raw, "usage") and raw.usage:
            total_prompt_tokens += (
                getattr(raw.usage, "input_tokens", None)
                or getattr(raw.usage, "prompt_tokens", None)
                or 0
            )
            total_completion_tokens += (
                getattr(raw.usage, "output_tokens", None)
                or getattr(raw.usage, "completion_tokens", None)
                or 0
            )
        for choice in getattr(raw, "choices", []):
            if hasattr(choice, "message") and choice.message and choice.message.tool_calls:
                tool_calls_count += len(choice.message.tool_calls)

    _log_usage(
        chat_id,
        user_id,
        total_prompt_tokens,
        total_completion_tokens,
        tool_calls_count,
        start_time,
        trigger_type,
    )

    response_text = str(result.final_output).strip() if result.final_output else None
    return clean_response(response_text)


def _log_usage(
    chat_id: int,
    user_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    tool_calls: int,
    start_time: float,
    trigger_type: str,
):
    """Fire-and-forget usage logging."""
    import asyncio

    response_time_ms = int((time.time() - start_time) * 1000)

    async def _insert():
        try:
            await execute(
                text(
                    """
                    INSERT INTO chat_agent_usage
                    (chat_id, user_id, prompt_tokens, completion_tokens,
                     tool_calls, response_time_ms, trigger_type)
                    VALUES (:chat_id, :user_id, :prompt_tokens, :completion_tokens,
                            :tool_calls, :response_time_ms, :trigger_type)
                """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "tool_calls": tool_calls,
                    "response_time_ms": response_time_ms,
                    "trigger_type": trigger_type,
                },
            )
        except Exception as e:
            logger.error("Failed to log agent usage: %s", e, exc_info=True)

    asyncio.create_task(_insert())
