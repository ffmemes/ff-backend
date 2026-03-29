import json
import logging
import time

from openai import AsyncOpenAI
from sqlalchemy import text

from src.config import settings
from src.database import execute
from src.tgbot.handlers.chat.agent.prompts import SYSTEM_PROMPT
from src.tgbot.handlers.chat.agent.tools import TOOL_SCHEMAS, dispatch_tool
from src.tgbot.handlers.chat.ai import _messages_to_text
from src.tgbot.handlers.chat.service import get_latest_chat_messages

logger = logging.getLogger(__name__)

MAX_TURNS = 8
MAX_TOOL_CALLS = 15


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

    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=30.0,
    )

    # Build initial context from recent messages
    messages_history = await get_latest_chat_messages(chat_id=chat_id, limit=20)
    chat_context = _messages_to_text(messages_history)

    api_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Вот последние сообщения в чате:\n\n{chat_context}\n\n"
                "Ответь на последнее сообщение."
            ),
        },
    ]

    start_time = time.time()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    tool_calls_count = 0

    for turn in range(MAX_TURNS):
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=api_messages,
                tools=TOOL_SCHEMAS if turn < MAX_TURNS - 1 else None,
                max_tokens=500,
                temperature=0.8,
            )
        except Exception as e:
            logger.error("DeepSeek API error: %s", e)
            return None

        choice = response.choices[0]
        message = choice.message

        if response.usage:
            total_prompt_tokens += response.usage.prompt_tokens
            total_completion_tokens += response.usage.completion_tokens

        # Tool calls
        if message.tool_calls:
            api_messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                tool_calls_count += 1
                if tool_calls_count > MAX_TOOL_CALLS:
                    logger.warning("Agent exceeded max tool calls in chat %s", chat_id)
                    break
                logger.info("Agent tool: %s(%s)", tool_name, tool_args)

                result = await dispatch_tool(
                    tool_name,
                    tool_args,
                    bot,
                    chat_id,
                    reply_to_message_id=reply_to_message_id,
                )

                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    }
                )
            continue

        # Final text response
        _log_usage(
            chat_id,
            user_id,
            total_prompt_tokens,
            total_completion_tokens,
            tool_calls_count,
            start_time,
            trigger_type,
        )
        return message.content

    # Max turns reached
    _log_usage(
        chat_id,
        user_id,
        total_prompt_tokens,
        total_completion_tokens,
        tool_calls_count,
        start_time,
        trigger_type,
    )
    return None


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
            logger.warning("Failed to log agent usage: %s", e)

    asyncio.create_task(_insert())
