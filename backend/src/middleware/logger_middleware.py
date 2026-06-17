import copy
import time
from typing import Any

from fastapi import Request

from backend.src.config import logger_config
from backend.src.constants import log_constants


class LoggerConfigMiddleware:
    async def __call__(self, request: Request, call_next):
        start_time = time.perf_counter()
        request.state.start_time = start_time

        skip_urls = [""]
        if request.url.path in skip_urls:
            return await call_next(request)

        logger_config.add_trace_id(request)

        log_data: dict[str, Any] = {"headers": dict(request.headers)}

        if request.query_params:
            log_data["query_params"] = dict(request.query_params)

        if (
            request.json
            and "content-type" in request.headers
            and "multipart/form-data" not in request.headers["content-type"]
        ):
            try:
                request.state.request_json = await request.json()
                body = copy.deepcopy(request.state.request_json)
                for doc in body.get("documents", []) if isinstance(body, dict) else []:
                    if isinstance(doc, dict):
                        doc.pop("file_data", None)
                log_data["body"] = body
            except Exception:
                log_data["body"] = "No JSON body found"

        logger_config.req_res_logger.info("Request Data: %s", log_data)

        response = await call_next(request)
        response.headers[log_constants.X_Trace_ID] = request.state.trace_id
        return response