import os

import uvicorn

if __name__ == "__main__":
    # Get port and host from env, or use default
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))

    print(f"Starting Stock Control module at http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
