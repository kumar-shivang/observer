"""Root entry point — delegates to monitor.main."""
import asyncio
from monitor.main import main

if __name__ == "__main__":
    asyncio.run(main())
