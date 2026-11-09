#!/usr/bin/env python3
#
# Envia alertas do Zabbix com o gráfico do item para o Telegram.
#
# Referência da API (https://core.telegram.org/bots/api):
#   POST {api}/bot{token}/sendPhoto     multipart: {chat_id, photo, caption, parse_mode, ...}
#   POST {api}/bot{token}/sendMessage   form: {chat_id, text, parse_mode, ...}
#
# Destino (TO): chat_id do usuário ou grupo (ex.: -1001234567890), @canal ou,
# para um tópico de grupo fórum, chat_id:thread_id (ex.: -1001234567890:42).
#
# Uso:
#   telegram-graph.py URLZBX USERZBX PWDZBX ITEMIDZBX TOKEN TO SUBJECT MSG
#

import base64
import json
import os
import re
import sys
import time
from urllib.parse import unquote

try:
    import requests
except ImportError:
    sys.stderr.write("Erro: biblioteca 'requests' não encontrada. Execute: pip install requests\n")
    sys.exit(1)

LOG_TAG = "Zabbix-Telegram"
EXPECTED_ARGS = 8

# Configurações do gráfico e da rede
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "20"))

# Telegram
API_URL = os.environ.get("TG_API_URL", "https://api.telegram.org").strip().rstrip("/")
PARSE_MODE = os.environ.get("TG_PARSE_MODE", "HTML").strip()
if PARSE_MODE.lower() == "html":
    PARSE_MODE = "HTML"


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
# Telegram
# --------------------------------------------------------------------------- #

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
RECIPIENT_RE = re.compile(r"^(-?\d+|@[A-Za-z0-9_]{5,}):(\d+)$")
BOLD_RE = re.compile(r"\*([^*\n]+)\*")


def tg_len(text):
    """O Telegram conta o tamanho em unidades UTF-16 (emojis contam 2)."""
    return len(text.encode("utf-16-le")) // 2


def tg_truncate(text, limit):
    if tg_len(text) <= limit:
        return text
    out = []
    size = 0
    for ch in text:
        size += tg_len(ch)
        if size > limit - 1:
            break
        out.append(ch)
    return "".join(out) + "…"


def format_text(text):
    """Converte o *negrito* dos templates para o PARSE_MODE configurado.

    Os valores das macros são escapados antes da conversão, então nomes de
    trigger com '<', '>' ou '&' não quebram a mensagem.
    """
    if PARSE_MODE == "HTML":
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return BOLD_RE.sub(r"<b>\1</b>", escaped)
    return BOLD_RE.sub(r"\1", text)


def plain_text(text):
    return BOLD_RE.sub(r"\1", text)


def parse_recipient(raw):
    """Aceita chat_id, @canal ou chat_id:thread_id (tópico de grupo fórum)."""
    raw = raw.strip()
    match = RECIPIENT_RE.match(raw)
    if match:
        return match.group(1), match.group(2)
    return raw, None


def parse_arguments():
    if len(sys.argv) != EXPECTED_ARGS + 1:
        fail(f"Parâmetros incorretos. Recebidos {len(sys.argv) - 1}, esperados {EXPECTED_ARGS}.")

    chat_id, thread_id = parse_recipient(sys.argv[6])
    cfg = {
        "url_zbx": sys.argv[1].strip().rstrip("/"),
        "user_zbx": os.environ.get("ZBX_USER") or sys.argv[2],
        "pwd_zbx": os.environ.get("ZBX_PASSWORD") or sys.argv[3],
        "item_id": clean_item_id(sys.argv[4]),
        "url_api": API_URL,
        "token": (os.environ.get("TG_TOKEN") or sys.argv[5]).strip(),
        "chat_id": chat_id,
        "thread_id": thread_id,
        "subject": sys.argv[7],
        "msg": sys.argv[8],
    }

    require_http_url(cfg["url_zbx"], "URLZBX")
    require_value(cfg["user_zbx"], "USERZBX")
    require_value(cfg["pwd_zbx"], "PWDZBX", placeholder_check=False)
    require_http_url(cfg["url_api"], "TG_API_URL")
    require_value(cfg["token"], "TOKEN")
    require_value(cfg["chat_id"], "Destinatário (TO)")

    if PARSE_MODE not in ("HTML", ""):
        fail("TG_PARSE_MODE deve ser 'HTML' ou vazio (texto puro).")

    return cfg


def mask(cfg, text):
    """Remove o token de qualquer texto que vá para o log (ele faz parte da URL)."""
    return str(text).replace(cfg["token"], "***")


def call_api(cfg, method, data, verify, files=None):
    """Chama a Bot API. Em caso de 429, espera o retry_after (até 30s) e tenta de novo."""
    url = f"{cfg['url_api']}/bot{cfg['token']}/{method}"
    for attempt in (1, 2):
        try:
            res = requests.post(url, data=data, files=files, verify=verify, timeout=HTTP_TIMEOUT)
        except Exception as exc:
            raise RuntimeError(mask(cfg, exc)) from None
        if res.status_code == 429 and attempt == 1:
            try:
                wait = int(res.json().get("parameters", {}).get("retry_after", 5))
            except ValueError:
                wait = 5
            log_err(f"Telegram pediu para aguardar {wait}s (HTTP 429).")
            time.sleep(min(wait, 30))
            continue
        return res
    return res


def is_parse_error(res):
    return res.status_code == 400 and "can't parse entities" in res.text


def base_data(cfg):
    data = {"chat_id": cfg["chat_id"]}
    if cfg["thread_id"]:
        data["message_thread_id"] = cfg["thread_id"]
    return data


def send_text(cfg, verify):
    """Envia somente o texto do alerta (também usado como fallback)."""
    text = tg_truncate(build_text(cfg), TEXT_LIMIT)
    data = base_data(cfg)
    data["text"] = format_text(text)
    data["link_preview_options"] = json.dumps({"is_disabled": True})
    if PARSE_MODE:
        data["parse_mode"] = PARSE_MODE

    try:
        res = call_api(cfg, "sendMessage", data, verify)
        if is_parse_error(res):
            log_err("Telegram não aceitou a formatação; reenviando como texto puro.")
            data.pop("parse_mode", None)
            data["text"] = plain_text(text)
            res = call_api(cfg, "sendMessage", data, verify)
    except RuntimeError as exc:
        fail(f"Erro de conexão com o Telegram: {exc}")
    if not res.ok:
        fail(f"Falha ao enviar texto no Telegram (HTTP {res.status_code}): {mask(cfg, res.text[:300])}")
    print("Mensagem de texto enviada com sucesso.")


def send_media(cfg, image_bytes, verify):
    """Envia o gráfico com o texto como legenda.

    Se o texto passar do limite de legenda (1024), envia a foto sem legenda e
    o texto completo logo em seguida. Se a foto falhar, envia só o texto.
    """
    text = build_text(cfg)
    fits = tg_len(plain_text(text)) <= CAPTION_LIMIT

    data = base_data(cfg)
    if fits:
        data["caption"] = format_text(text)
        if PARSE_MODE:
            data["parse_mode"] = PARSE_MODE

    def photo():
        files = {"photo": (f"graph_{cfg['item_id']}.png", image_bytes, "image/png")}
        return call_api(cfg, "sendPhoto", data, verify, files=files)

    try:
        res = photo()
        if fits and is_parse_error(res):
            log_err("Telegram não aceitou a formatação da legenda; reenviando como texto puro.")
            data.pop("parse_mode", None)
            data["caption"] = plain_text(text)
            res = photo()
        if res.ok:
            if fits:
                print("Mensagem e gráfico enviados com sucesso.")
                return
            print("Gráfico enviado; o texto excede a legenda e vai em mensagem separada.")
        else:
            log_err(f"Telegram recusou a foto (HTTP {res.status_code}): {mask(cfg, res.text[:300])}. Enviando só o texto.")
    except RuntimeError as exc:
        log_err(f"Erro ao enviar a foto: {exc}. Enviando só o texto.")

    send_text(cfg, verify)


def main():
    cfg = parse_arguments()
    zbx_verify = tls_option("ZBX_VERIFY_TLS")
    api_verify = tls_option("TG_VERIFY_TLS")

    image_bytes = fetch_graph(cfg, zbx_verify)
    if image_bytes:
        send_media(cfg, image_bytes, api_verify)
    else:
        send_text(cfg, api_verify)


if __name__ == "__main__":
    main()
