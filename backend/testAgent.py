import asyncio
from deerflow.client import DeerFlowClient
from deerflow.config import get_app_config


# 加载配置
get_app_config()

client = DeerFlowClient()


async def main():
    for event in client.stream(
            thread_id="my-first-thread",
            message="你好",
            model_name="test38flash0911",
    ):
        print(event)


asyncio.run(main())
