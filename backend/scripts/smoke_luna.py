import asyncio

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.settings import get_settings
from src.observability.usage import UsageTracker, track_usage
from src.providers.llm.openai import OpenAIProvider


async def main() -> None:
    get_settings.cache_clear()
    tracker = UsageTracker()
    with track_usage(tracker):
        llm = OpenAIProvider().get_chat_model(model="gpt-5.6-luna", max_tokens=64)
        resp = await llm.ainvoke(
            [
                SystemMessage(content="Reply with the single word: pong"),
                HumanMessage(content="ping"),
            ]
        )
        print("content:", str(resp.content)[:300])
        print("usage_metadata:", getattr(resp, "usage_metadata", None))
        print("response_metadata:", getattr(resp, "response_metadata", None))
    print("tracker:", tracker.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
