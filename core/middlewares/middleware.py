import time
from core.logger.logger import LOG
from fastapi import FastAPI, Request, Response



def middleware_handler(app: FastAPI):
    
    @app.middleware("http")
    async def _handler(request: Request, call_next):

        # Get HTTP method and route
        http_method = request.method
        route = request.scope.get("path", "Unknown")

        # Skip logging for less useful or internal methods
        if http_method in ["OPTIONS", "HEAD", "TRACE", "CONNECT"]:
            return await call_next(request)

        # Start time recording after the method check
        start_time = time.perf_counter()

        # Process the request and calculate the time taken
        response: Response
        response = await call_next(request)
        process_time = time.perf_counter() - start_time

        # Add the process time to response headers
        response.headers["X-Process-Time"] = str(process_time)

        # Log the processed request with time taken
        LOG.info(
            f"{http_method} {route} {response.status_code} {process_time * 1000:.0f}ms",
            extra={"event": "http.request", "method": http_method, "path": route, "status": response.status_code, "ms": round(process_time * 1000)},
        )

        return response