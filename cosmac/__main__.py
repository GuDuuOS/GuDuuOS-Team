"""CosMac 主 AI Bot 的启动入口。

用法（在项目根目录、且已激活/指定 .venv）：
    python -m cosmac

环境变量可覆盖配置，例如换模型后端：
    COSMAC_LLM_PROVIDER=echo python -m cosmac
"""

from __future__ import annotations

import logging

from cosmac.bots.appservice_bot import run
from cosmac.config import CosmacConfig


def main() -> None:
    # 统一日志格式，方便观察主 AI"看到了什么、做了什么"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = CosmacConfig.from_env()
    # 启动前先校验 appservice 密钥存在（密钥不再硬编码，缺失就明确报错）
    config.require_tokens()
    run(config)


if __name__ == "__main__":
    main()
