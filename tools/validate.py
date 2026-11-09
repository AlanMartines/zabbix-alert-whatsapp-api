#!/usr/bin/env python3
"""
Validação estrutural do repositório (WhatsApp e Telegram).

Verifica:
  - todos os media types abrem como YAML e declaram version '7.0';
  - os nomes dos media types são únicos dentro de cada pasta e não colidem
    com os que já vêm no Zabbix (ex.: "Telegram");
  - media types SCRIPT apontam para um arquivo existente e executável na pasta
    alertscripts/ correspondente, vêm desabilitados e passam o número de
    argumentos que o script espera;
  - media types WEBHOOK declaram os parâmetros esperados e têm o mesmo
    JavaScript nas pastas com e sem emojis;
  - o JavaScript dos webhooks compila (quando o Node.js está disponível);
  - os scripts Python compilam e compartilham o mesmo bloco de utilitários;
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

# (pasta base, canal). Cada base tem as mesmas subpastas e seu próprio alertscripts/.
GROUPS = (
    (ROOT, "whatsapp"),
    (os.path.join(ROOT, "telegram"), "telegram"),
)
WEBHOOK_DIRS = ("zbx_mediatypes", "zbx_mediatypes_use_emojis")
GRAPHIC_DIR = "zbx_mediatypes_use_emojis_graphic"

# Media types que já vêm no Zabbix 7.0 e que não podem ser sobrescritos na importação.
BUILTIN_NAMES = {"Telegram", "Email", "SMS"}

COMMON_START = "# --------------------------------------------------------------------------- #\n# Utilitários comuns"
COMMON_END_RE = re.compile(r"\n# -{75} #\n# (?!Utilitários comuns)")

REQUIRED_WEBHOOK_PARAMS = {
    "whatsapp": ("Url", "To", "Subject", "Message", "HTTPProxy"),
    "telegram": ("Url", "Token", "To", "Subject", "Message", "HTTPProxy", "ParseMode"),
}

errors = []


def rel(path):
    return os.path.relpath(path, ROOT)


def error(path, msg):
    errors.append(f"{rel(path)}: {msg}")


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


def check_script_media_type(path, mt, scripts_dir):
    name = mt.get("script_name", "")
    script_path = os.path.join(scripts_dir, name)

    if not os.path.isfile(script_path):
        error(path, f"script_name '{name}' não existe em {rel(scripts_dir)}/")
        return
    if not os.access(script_path, os.X_OK):
        error(path, f"{rel(script_path)} não tem permissão de execução")
    if mt.get("status") != "DISABLED":
        error(path, "media types SCRIPT devem vir com status: DISABLED")

    n_params = len(mt.get("parameters") or [])
    n_expected = expected_args(script_path)
    if n_expected is None:
        error(path, f"{rel(script_path)} não define EXPECTED_ARGS")
    elif n_params != n_expected:
        error(path, f"{n_params} parâmetros, mas {rel(script_path)} espera {n_expected}")


def check_webhook_media_type(path, mt, channel):
    names = {p.get("name") for p in mt.get("parameters") or []}
    script = mt.get("script", "")

    for required in REQUIRED_WEBHOOK_PARAMS[channel]:
        if required not in names:
            error(path, f"parâmetro {required} não declarado")

    if channel == "whatsapp":
        if "ParseMode" in names:
            error(path, "parâmetro ParseMode não se aplica ao WhatsApp")
        if "ParseMode" in script or "escapeMarkup" in script:
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


def common_block(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.find(COMMON_START)
    if start == -1:
        return None
    match = COMMON_END_RE.search(text, start + len(COMMON_START))
    return text[start:match.start()] if match else None


def check_group(base, channel, names_seen):
    scripts_dir = os.path.join(base, "alertscripts")
    webhook_scripts = {}

    for folder in WEBHOOK_DIRS + (GRAPHIC_DIR,):
        for path in sorted(glob.glob(os.path.join(base, folder, "*.yaml"))):
            mt = load_media_type(path)
            if mt is None:
                continue

            # As variantes (sem emojis, com emojis, gráfico) são alternativas,
            # então o nome só precisa ser único dentro da mesma pasta.
            name = mt.get("name", "")
            key = (os.path.join(base, folder), name)
            if name in BUILTIN_NAMES:
                error(path, f"o nome '{name}' colide com um media type nativo do Zabbix")
            if key in names_seen:
                error(path, f"nome '{name}' repetido (também em {names_seen[key]})")
            names_seen[key] = rel(path)

            check_templates(path, mt)
            if mt.get("type") == "SCRIPT":
                check_script_media_type(path, mt, scripts_dir)
            elif mt.get("type") == "WEBHOOK":
                check_webhook_media_type(path, mt, channel)
                check_js_syntax(path, mt.get("script", ""))
                webhook_scripts.setdefault(os.path.basename(path), {})[folder] = mt.get("script")
            else:
                error(path, f"tipo inesperado: {mt.get('type')}")

    for name, by_folder in sorted(webhook_scripts.items()):
        missing = [d for d in WEBHOOK_DIRS if d not in by_folder]
        if missing:
            errors.append(f"{rel(base) if base != ROOT else '.'}/{name}: ausente em {', '.join(missing)}")
        elif len(set(by_folder.values())) != 1:
            errors.append(f"{name}: o JavaScript difere entre {' e '.join(WEBHOOK_DIRS)}")

    return sorted(glob.glob(os.path.join(scripts_dir, "*.py")))


def main():
    names_seen = {}
    scripts = []
    for base, channel in GROUPS:
        if os.path.isdir(base):
            scripts += check_group(base, channel, names_seen)

    reference = None
    for path in scripts:
        with open(path, encoding="utf-8") as fh:
            try:
                compile(fh.read(), path, "exec")
            except SyntaxError as exc:
                error(path, f"erro de sintaxe: {exc}")
                continue

        block = common_block(path)
        if block is None:
            error(path, "bloco 'Utilitários comuns' não encontrado")
        elif reference is None:
            reference = (path, block)
        elif block != reference[1]:
            error(path, f"bloco 'Utilitários comuns' difere de {rel(reference[0])}")

    if errors:
        print(f"{len(errors)} problema(s) encontrado(s):")
        for msg in errors:
            print(f"  - {msg}")
        return 1

    print(f"Tudo certo ({len(names_seen)} media types, {len(scripts)} scripts).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
