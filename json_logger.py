import datetime, json, logging, os, sys, traceback
try:
    import orjson  # optional speed-up
except Exception:
    orjson = None

def _safe_to_json(obj):
    try:
        if orjson:
            return orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS).decode("utf-8")
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"unserializable": str(obj)}, ensure_ascii=False)

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "timestamp": datetime.datetime.utcfromtimestamp(record.created).isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
            "process": record.process,
            "thread": record.thread,
        }
        for k, v in record.__dict__.items():
            if k.startswith("_") or k in base or k in ("args","msg","exc_info","exc_text","stack_info","message"):
                continue
            base[k] = v
        if record.exc_info:
            base["exc_info"] = "".join(traceback.format_exception(*record.exc_info))
        return _safe_to_json(base)

def install_json_logging(level: int | str = None):
    level = level or os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.handlers[:] = [handler]
    logging.getLogger("urllib3").propagate = False
    logging.getLogger("playwright").propagate = False
    return root
