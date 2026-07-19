"""Launch the Card Inventory web app.

Env-configurable so the same entrypoint works locally and on a host like Azure
App Service:
    HOST    bind address (default 127.0.0.1; use 0.0.0.0 when hosted)
    PORT    port (default 8000; hosts set this)
    RELOAD  "1" to enable auto-reload for local dev (default off)
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "0") == "1",
        # don't leak the server technology in the Server header
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
