import json
import os
from pathlib import Path
import sys

from app.download_model import valid_snapshot
from app.privacy import emit, silence_raw_output


def main():
    silence_raw_output()
    try:
        model_id = os.environ["MODEL_ID"]
        revision = os.environ["MODEL_REVISION"]
        model_path = Path(os.environ.get("MODEL_ROOT", "/models")) / revision
        if not valid_snapshot(model_path, model_id, revision):
            raise RuntimeError("Model cache is missing or corrupt")
        if not os.environ.get("VLLM_API_KEY", "").strip():
            raise RuntimeError("API token is required")
        # Set these before importing vLLM or Transformers.
        os.environ.update({
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
            "VLLM_NO_USAGE_STATS": "1", "VLLM_DEBUG_LOG_API_SERVER_RESPONSE": "0",
            "VLLM_LOGGING_CONFIG_PATH": "/app/config/logging.json",
        })
        config_path = os.environ.get("VLLM_CONFIG", "/config/vllm.json")
        config = json.loads(Path(config_path).read_text())
        # Security settings cannot be switched off through the inference ConfigMap.
        config.update({
            "model": str(model_path), "tokenizer": str(model_path),
            "trust-remote-code": False, "enable-log-requests": False,
            "enable-log-outputs": False, "disable-uvicorn-access-log": True,
            "log-config-file": "/app/config/logging.json",
            "middleware": ["app.privacy.AuditMiddleware"],
        })
        config.pop("api-key", None)
        # In 0.27.0 false YAML values are skipped by the CLI config loader.
        # Spell them as explicit --no-* flags so defaults cannot turn them on.
        config = {("no-" + key if value is False else key):
                  (True if value is False else value) for key, value in config.items()}
        # vLLM checks the suffix even though JSON is valid YAML syntax.
        Path("/tmp/vllm.yaml").write_text(json.dumps(config))
        emit("server_starting")
        from vllm.entrypoints.cli.main import main as vllm_main
        sys.argv = ["vllm", "serve", "--config", "/tmp/vllm.yaml"]
        vllm_main()
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            return
        if isinstance(error, SystemExit) and error.code in (None, 0):
            return
        emit("server_failed", error_type=type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
