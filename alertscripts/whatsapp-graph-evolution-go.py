#!/usr/bin/env python3
#
# Envia alertas do Zabbix com o gráfico do item para o WhatsApp via Evolution Go.
#
# Referência da API (https://docs.evolutionfoundation.com.br/evolution-go/):
#   POST {url}/send/media    header: apikey    body: {number, type, url, caption, ...}
#   POST {url}/send/text     header: apikey    body: {number, text, ...}
#
# Diferenças em relação à Evolution API:
#   - a instância NÃO vai no path; ela é identificada pelo token (apikey) usado;
#   - o campo da mídia chama-se `url` (e não `media`) e o tipo, `type` (e não
#     `mediatype`). `url` aceita tanto uma URL quanto o conteúdo em base64.
#
# Uso:
#   whatsapp-graph-evolution-go.py URLZBX USERZBX PWDZBX ITEMIDZBX URLAPI APIKEY TO SUBJECT MSG
#

import base64
import json
import os
import re
import sys
from urllib.parse import unquote

try:
    import requests
except ImportError:
    sys.stderr.write("Erro: biblioteca 'requests' não encontrada. Execute: pip install requests\n")
    sys.exit(1)

LOG_TAG = "Zabbix-EvolutionGo"
EXPECTED_ARGS = 9

# Configurações do gráfico e da rede
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "20"))
SEND_DELAY = int(os.environ.get("WA_SEND_DELAY", "500"))

MEDIA_MODE = os.environ.get("EVOGO_MEDIA_MODE", "base64").strip().lower()
MEDIA_URL = os.environ.get("EVOGO_MEDIA_URL", "").strip()


# --------------------------------------------------------------------------- #
# Utilitários comuns (mantidos iguais em todos os scripts de alertscripts/)
# --------------------------------------------------------------------------- #

def log_err(msg):
    sys.stderr.write(f"[{LOG_TAG}] {msg}\n")


def fail(msg):
    log_err(f"FATAL: {msg}")
    sys.exit(1)


def tls_option(env_name):
    """Lê a opção de verificação TLS: true/false ou caminho para um CA bundle."""
    val = os.environ.get(env_name, "true").strip()
    if val.lower() in ("false", "0", "no"):
        return False
    if val.lower() in ("true", "1", "yes", ""):
        return True
    return val


def clean_item_id(raw):
    """Macro não resolvida ({ITEM.ID1}) ou vazio significa alerta sem gráfico."""
    raw = raw.strip()
    return raw if raw.isdigit() else None


def clean_recipient(raw):
    """Mantém IDs de grupo (com '@'); para números, deixa somente os dígitos."""
    raw = raw.strip()
    return raw if "@" in raw else re.sub(r"\D", "", raw)


def require_value(value, name, placeholder_check=True):
    if not value:
        fail(f"{name} não pode estar vazio.")
    # A senha pode conter '<' e '>' legitimamente, por isso a checagem é opcional.
    if placeholder_check and re.search(r"<[^>]+>", value):
        fail(f"{name} ainda contém um marcador não substituído: {value}")


def require_http_url(value, name):
    require_value(value, name)
    if not value.startswith(("http://", "https://")):
        fail(f"{name} deve começar com 'http://' ou 'https://'.")


def zabbix_session_id(session):
    """Extrai o sessionid do cookie zbx_session (base64 de um JSON)."""
    raw = session.cookies.get("zbx_session")
    if not raw:
        return None
    try:
        data = json.loads(base64.b64decode(unquote(raw)))
        return data.get("sessionid")
    except (ValueError, TypeError):
        return None


def zabbix_logout(session, cfg, verify):
    """Encerra a sessão aberta no frontend para não acumular sessões no banco."""
    sid = zabbix_session_id(session)
    if not sid:
        return
    payload = {"jsonrpc": "2.0", "method": "user.logout", "params": [], "id": 1}
    headers = {"Content-Type": "application/json-rpc", "Authorization": f"Bearer {sid}"}
    try:
        res = session.post(
            f"{cfg['url_zbx']}/api_jsonrpc.php",
            json=payload, headers=headers, verify=verify, timeout=HTTP_TIMEOUT,
        )
        if "error" in res.json():
            log_err(f"Logout no Zabbix não concluído: {res.text[:200]}")
    except Exception as exc:
        log_err(f"Falha ao encerrar a sessão no Zabbix: {exc}")


def fetch_graph(cfg, verify):
    """Autentica no frontend do Zabbix 7, baixa o PNG do gráfico e faz logout."""
    if not cfg["item_id"]:
        return None

    session = requests.Session()
    login_url = f"{cfg['url_zbx']}/index.php"
    login_data = {
        "name": cfg["user_zbx"],
        "password": cfg["pwd_zbx"],
        "enter": "Sign in",
        "autologin": 0,
        "request": "",
    }

    try:
        # GET inicial para receber o cookie de sessão
        session.get(login_url, verify=verify, timeout=HTTP_TIMEOUT)
        res = session.post(login_url, data=login_data, verify=verify, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        log_err(f"Falha de conexão com o Zabbix: {exc}")
        return None

    # Em caso de sucesso o Zabbix redireciona para o dashboard; em caso de
    # falha, devolve de novo o formulário de index.php.
    if "zbx_session" not in session.cookies or res.url.split("?")[0].endswith("index.php"):
        log_err("Não foi possível autenticar no Zabbix. Verifique usuário e senha.")
        return None

    graph_url = f"{cfg['url_zbx']}/chart.php"
    graph_params = {
        "from": GRAPH_FROM,
        "to": GRAPH_TO,
        "itemids[0]": cfg["item_id"],
        "type": GRAPH_TYPE,
        "profileIdx": GRAPH_PROFILE_IDX,
        "width": GRAPH_WIDTH,
        "height": GRAPH_HEIGHT,
    }

    image = None
    try:
        res = session.get(graph_url, params=graph_params, verify=verify, timeout=HTTP_TIMEOUT)
        if res.ok and res.content.startswith(b"\x89PNG"):
            image = res.content
        else:
            log_err(f"chart.php não devolveu um PNG válido (HTTP {res.status_code}).")
    except Exception as exc:
        log_err(f"Erro ao baixar o gráfico do item {cfg['item_id']}: {exc}")
    finally:
        zabbix_logout(session, cfg, verify)

    return image


def build_text(cfg):
    return f"{cfg['subject']}\n\n{cfg['msg']}" if cfg["subject"] else cfg["msg"]


# --------------------------------------------------------------------------- #
# Evolution Go
# --------------------------------------------------------------------------- #

def parse_arguments():
    if len(sys.argv) != EXPECTED_ARGS + 1:
        fail(f"Parâmetros incorretos. Recebidos {len(sys.argv) - 1}, esperados {EXPECTED_ARGS}.")

    cfg = {
        "url_zbx": sys.argv[1].strip().rstrip("/"),
        "user_zbx": os.environ.get("ZBX_USER") or sys.argv[2],
        "pwd_zbx": os.environ.get("ZBX_PASSWORD") or sys.argv[3],
        "item_id": clean_item_id(sys.argv[4]),
        "url_api": sys.argv[5].strip().rstrip("/"),
        "apikey": os.environ.get("EVOGO_APIKEY") or sys.argv[6],
        "to": clean_recipient(sys.argv[7]),
        "subject": sys.argv[8],
        "msg": sys.argv[9],
    }

    require_http_url(cfg["url_zbx"], "URLZBX")
    require_value(cfg["user_zbx"], "USERZBX")
    require_value(cfg["pwd_zbx"], "PWDZBX", placeholder_check=False)
    require_http_url(cfg["url_api"], "URLAPI")
    require_value(cfg["apikey"], "APIKEY")
    require_value(cfg["to"], "Destinatário (TO)")

    if MEDIA_MODE not in ("base64", "url"):
        fail("EVOGO_MEDIA_MODE deve ser 'base64' ou 'url'.")
    if MEDIA_MODE == "url" and not MEDIA_URL:
        fail("EVOGO_MEDIA_MODE='url' exige EVOGO_MEDIA_URL preenchida.")

    return cfg


def post_json(cfg, path, payload, verify):
    url = f"{cfg['url_api']}{path}"
    headers = {"Content-Type": "application/json", "apikey": cfg["apikey"]}
    return requests.post(url, json=payload, headers=headers, verify=verify, timeout=HTTP_TIMEOUT)


def send_text(cfg, verify):
    """Envia somente o texto do alerta (também usado como fallback)."""
    payload = {
        "number": cfg["to"],
        "text": build_text(cfg),
        "delay": SEND_DELAY,
    }
    try:
        res = post_json(cfg, "/send/text", payload, verify)
    except Exception as exc:
        fail(f"Erro de conexão com o Evolution Go: {exc}")
    if not res.ok:
        fail(f"Falha ao enviar texto no Evolution Go (HTTP {res.status_code}): {res.text[:300]}")
    print("Mensagem de texto enviada com sucesso.")


def send_media(cfg, image_bytes, verify):
    """Envia o gráfico com o texto como legenda; se falhar, envia só o texto."""
    if MEDIA_MODE == "url":
        media_ref = MEDIA_URL
    else:
        media_ref = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "number": cfg["to"],
        "type": "image",
        "url": media_ref,
        "caption": build_text(cfg),
        "filename": f"graph_{cfg['item_id']}.png",
        "delay": SEND_DELAY,
    }

    try:
        res = post_json(cfg, "/send/media", payload, verify)
        if res.ok:
            print("Mensagem e gráfico enviados com sucesso.")
            return
        log_err(f"Evolution Go recusou a mídia (HTTP {res.status_code}): {res.text[:300]}. Enviando só o texto.")
    except Exception as exc:
        log_err(f"Erro ao enviar a mídia: {exc}. Enviando só o texto.")

    send_text(cfg, verify)


def main():
    cfg = parse_arguments()
    zbx_verify = tls_option("ZBX_VERIFY_TLS")
    api_verify = tls_option("EVOGO_VERIFY_TLS")

    image_bytes = fetch_graph(cfg, zbx_verify)
    if image_bytes:
        send_media(cfg, image_bytes, api_verify)
    else:
        send_text(cfg, api_verify)


if __name__ == "__main__":
    main()
