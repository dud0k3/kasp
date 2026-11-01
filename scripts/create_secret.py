"""Keep secret values out of shell history, process arguments and git."""
import os
from pathlib import Path
import secrets
import subprocess

root = Path(__file__).resolve().parents[1]
directory = root / ".secrets"
directory.mkdir(mode=0o700, exist_ok=True)
os.chmod(directory, 0o700)
api_file = directory / "api-key"
hf_file = directory / "hf-token"
if "API_KEY" in os.environ:
    api_file.write_text(os.environ["API_KEY"])
elif not api_file.exists():
    api_file.write_text(secrets.token_urlsafe(32))
if not api_file.read_text().strip():
    raise SystemExit("API_KEY cannot be empty")
if "HF_TOKEN" in os.environ or not hf_file.exists():
    hf_file.write_text(os.environ.get("HF_TOKEN", ""))
for path in (api_file, hf_file):
    os.chmod(path, 0o600)
subprocess.run(["kubectl", "apply", "-f", str(root / "k8s/namespace.yaml")], check=True)
manifest = subprocess.check_output([
    "kubectl", "-n", "vllm-cpu", "create", "secret", "generic", "vllm-secrets",
    "--from-file=api-key=" + str(api_file), "--from-file=hf-token=" + str(hf_file),
    "--dry-run=client", "-o", "json",
])
# Use stdin; kubectl output contains only the resource name.
subprocess.run(["kubectl", "apply", "--server-side", "--field-manager=kasp-secrets", "-f", "-"],
               input=manifest, check=True)
print("Secret is ready. Local token files are in .secrets/ (gitignored).")
