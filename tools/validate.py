#!/usr/bin/env python3
"""
Validação estrutural do repositório.

Verifica:
  - todos os media types abrem como YAML e declaram version '7.0';
  - media types SCRIPT apontam para um arquivo existente e executável em
    alertscripts/, vêm desabilitados e passam o número de argumentos que o
    script espera;
  - media types WEBHOOK declaram HTTPProxy, não usam ParseMode e têm o mesmo
    JavaScript nas pastas com e sem emojis;
  - o JavaScript dos webhooks compila (quando o Node.js está disponível);
  - os scripts Python compilam;
  - os templates de mensagem não têm negrito (*) aberto sem fechar.

Uso: python3 tools/validate.py
"""

import glob
import os
import re
import shutil
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML é necessário: pip install pyyaml\n")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBHOOK_DIRS = ("zbx_mediatypes", "zbx_mediatypes_use_emojis")
ALL_DIRS = WEBHOOK_DIRS + ("zbx_mediatypes_use_emojis_graphic",)

errors = []


def error(path, msg):
    errors.append(f"{os.path.relpath(path, ROOT)}: {msg}")


def load_media_type(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        error(path, f"YAML inválido: {exc}")
        return None

    export = data.get("zabbix_export", {})
    if str(export.get("version")) != "7.0":
        error(path, f"version deve ser '7.0' (encontrado {export.get('version')!r})")

    media_types = export.get("media_types") or []
    if len(media_types) != 1:
        error(path, f"esperado 1 media type, encontrados {len(media_types)}")
        return None
    return media_types[0]


def expected_args(script_path):
    with open(script_path, encoding="utf-8") as fh:
        match = re.search(r"^EXPECTED_ARGS = (\d+)$", fh.read(), re.M)
    return int(match.group(1)) if match else None


def check_script_media_type(path, mt):
    name = mt.get("script_name", "")
    script_path = os.path.join(ROOT, "alertscripts", name)

    if not os.path.isfile(script_path):
        error(path, f"script_name '{name}' não existe em alertscripts/")
        return
    if not os.access(script_path, os.X_OK):
        error(path, f"alertscripts/{name} não tem permissão de execução")
    if mt.get("status") != "DISABLED":
        error(path, "media types SCRIPT devem vir com status: DISABLED")

    n_params = len(mt.get("parameters") or [])
    n_expected = expected_args(script_path)
    if n_expected is None:
        error(path, f"alertscripts/{name} não define EXPECTED_ARGS")
    elif n_params != n_expected:
        error(path, f"{n_params} parâmetros, mas alertscripts/{name} espera {n_expected}")


def check_webhook_media_type(path, mt):
    names = {p.get("name") for p in mt.get("parameters") or []}
    if "ParseMode" in names:
        error(path, "parâmetro ParseMode não se aplica ao WhatsApp")
    if "HTTPProxy" not in names:
        error(path, "parâmetro HTTPProxy não declarado")
    for required in ("Url", "To", "Subject", "Message"):
        if required not in names:
            error(path, f"parâmetro {required} não declarado")
    if "ParseMode" in mt.get("script", "") or "escapeMarkup" in mt.get("script", ""):
        error(path, "script ainda contém o tratamento de ParseMode do Telegram")


def check_js_syntax(path, script):
    node = shutil.which("node")
    if not node:
        return
    # O Zabbix executa o script como corpo de uma função que recebe `value`.
    wrapped = "(function (value) {\n" + script + "\n});"
    res = subprocess.run([node, "--check", "-"], input=wrapped, capture_output=True, text=True)
    if res.returncode != 0:
        error(path, "JavaScript inválido:\n" + res.stderr.strip())


def check_templates(path, mt):
    for tpl in mt.get("message_templates") or []:
        label = f"{tpl.get('event_source')}/{tpl.get('operation_mode')}"
        for field in ("subject", "message"):
            for line in str(tpl.get(field, "")).splitlines():
                if line.count("*") % 2:
                    error(path, f"template {label}: negrito sem fechar em {line.strip()!r}")


def main():
    webhook_scripts = {}

    for folder in ALL_DIRS:
        for path in sorted(glob.glob(os.path.join(ROOT, folder, "*.yaml"))):
            mt = load_media_type(path)
            if mt is None:
                continue
            check_templates(path, mt)
            if mt.get("type") == "SCRIPT":
                check_script_media_type(path, mt)
            elif mt.get("type") == "WEBHOOK":
                check_webhook_media_type(path, mt)
                check_js_syntax(path, mt.get("script", ""))
                webhook_scripts.setdefault(os.path.basename(path), {})[folder] = mt.get("script")
            else:
                error(path, f"tipo inesperado: {mt.get('type')}")

    for name, by_folder in sorted(webhook_scripts.items()):
        missing = [d for d in WEBHOOK_DIRS if d not in by_folder]
        if missing:
            errors.append(f"{name}: ausente em {', '.join(missing)}")
        elif len(set(by_folder.values())) != 1:
            errors.append(f"{name}: o JavaScript difere entre {' e '.join(WEBHOOK_DIRS)}")

    for path in sorted(glob.glob(os.path.join(ROOT, "alertscripts", "*.py"))):
        with open(path, encoding="utf-8") as fh:
            try:
                compile(fh.read(), path, "exec")
            except SyntaxError as exc:
                error(path, f"erro de sintaxe: {exc}")

    if errors:
        print(f"{len(errors)} problema(s) encontrado(s):")
        for msg in errors:
            print(f"  - {msg}")
        return 1

    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
