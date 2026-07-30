#!/usr/bin/env python3
#
# Envia alertas do Zabbix com o gráfico do item para o WhatsApp via uazapiGO.
#
# Referência da API (OpenAPI 2.1.1):
#   https://docs.uazapi.com/endpoint/post/send~media
#   POST {url}/send/media   header: token
#   body: {number*, type*, file*, text, docName, mimetype, delay, ...}
#   https://docs.uazapi.com/endpoint/post/send~text
#   POST {url}/send/text    header: token    body: {number*, text*, delay, ...}
#
# Diferenças em relação à Evolution API / Evolution Go:
#   - o header de autenticação é `token` (e não `apikey`);
#   - o campo da mídia é `file` (aceita URL ou base64);
#   - a legenda vai em `text` (e não `caption`);
#   - o tipo vai em `type`; `docName` só se aplica a documentos;
#   - a URL base inclui o subdomínio da sua conta: https://{subdominio}.uazapi.com
#

import base64
import os
import sys

try:
    import requests
except ImportError:
    sys.stderr.write(
        "Erro: a biblioteca 'requests' não está instalada.\n"
        "Instale no deploy com: pip install requests\n"
    )
    sys.exit(1)


# --- Configuração do gráfico (ajuste conforme necessário) --------------------
GRAPH_FROM = os.environ.get("ZBX_GRAPH_FROM", "now-6h")   # Tempo inicial
GRAPH_TO = os.environ.get("ZBX_GRAPH_TO", "now")          # Tempo final
GRAPH_WIDTH = os.environ.get("ZBX_GRAPH_WIDTH", "1024")   # Largura do gráfico
GRAPH_HEIGHT = os.environ.get("ZBX_GRAPH_HEIGHT", "220")  # Altura do gráfico
GRAPH_TYPE = os.environ.get("ZBX_GRAPH_TYPE", "0")        # 0=linha simples, 1=empilhado
GRAPH_PROFILE_IDX = "web.item.graph.filter"

HTTP_TIMEOUT = int(os.environ.get("ZBX_HTTP_TIMEOUT", "30"))
SEND_DELAY = int(os.environ.get("WA_SEND_DELAY", "1200"))

# 'base64' (padrão) envia o PNG codificado no campo `file`.
# 'url' usa UAZ_MEDIA_URL como URL pública do PNG, sem embutir a imagem.
MEDIA_MODE = os.environ.get("UAZ_MEDIA_MODE", "base64").strip().lower()
MEDIA_URL = os.environ.get("UAZ_MEDIA_URL", "").strip()

USAGE = """\
Usage: {prog} {{URLZBX}} {{USERZBX}} {{PWDZBX}} {{ITEMIDZBX}} {{URLAPI}} {{TOKEN}} {{TO}} {{SUBJECT}} {{MSG}}

URLAPI é a URL da sua conta uazapi, incluindo o subdomínio.
A instância é identificada pelo TOKEN informado.

Os segredos podem (e devem) vir do ambiente, deixando o argumento vazio (''):
  ZBX_USER      usuário do Zabbix       (substitui USERZBX)
  ZBX_PASSWORD  senha do Zabbix         (substitui PWDZBX)
  UAZ_TOKEN     token da instância      (substitui TOKEN)

Outras variáveis opcionais:
  ZBX_VERIFY_TLS   'true' (padrão), 'false' ou caminho para o CA bundle
  UAZ_VERIFY_TLS   idem, para a chamada à uazapi
  UAZ_MEDIA_MODE   'base64' (padrão) ou 'url'
  UAZ_MEDIA_URL    URL pública do PNG, obrigatória quando MODE='url'
  ZBX_GRAPH_FROM   janela do gráfico (padrão: now-6h)
  ZBX_HTTP_TIMEOUT timeout em segundos (padrão: 30)

Example:
========
{prog} https://zabbix.seudominio.com Admin zabbix 48061 https://suaconta.uazapi.com KHKHKHGKGJ 550000000000 'Subject' 'Msg from to WhatsApp'
"""


def fail(msg):
    """Encerra com status 1 para que o Zabbix registre a falha do alerta."""
    sys.stderr.write("Erro: {}\n".format(msg))
    sys.exit(1)


def tls_option(env_name):
    """Traduz a variável de ambiente para o parâmetro `verify` do requests.

    Aceita 'false' (desliga a validação), 'true' (padrão) ou um caminho de CA.
    """
    value = os.environ.get(env_name, "true").strip()
    if value.lower() in ("false", "0", "no"):
        sys.stderr.write(
            "Aviso: validação de certificado desativada em {} — o tráfego "
            "(inclusive credenciais) fica sujeito a interceptação.\n".format(env_name)
        )
        return False
    if value.lower() in ("true", "1", "yes", ""):
        return True
    return value  # caminho para o CA bundle


def parse_arguments():
    expected_args = 10
    if len(sys.argv) != expected_args:
        sys.stderr.write("Erro: número incorreto de argumentos fornecidos.\n\n")
        sys.stderr.write(USAGE.format(prog=sys.argv[0]))
        sys.exit(1)

    cfg = {
        "url_zbx": sys.argv[1].rstrip("/"),
        "user_zbx": os.environ.get("ZBX_USER") or sys.argv[2],
        "pwd_zbx": os.environ.get("ZBX_PASSWORD") or sys.argv[3],
        "item_id": sys.argv[4],
        "url_api": sys.argv[5].rstrip("/"),
        "token": os.environ.get("UAZ_TOKEN") or sys.argv[6],
        "to": sys.argv[7],
        "subject": sys.argv[8],
        "msg": sys.argv[9],
    }

    if not cfg["url_zbx"].startswith(("http://", "https://")):
        fail("URLZBX deve começar com 'http://' ou 'https://'.")
    if not cfg["user_zbx"]:
        fail("USERZBX não pode estar vazio (nem o argumento nem ZBX_USER).")
    if not cfg["pwd_zbx"]:
        fail("PWDZBX não pode estar vazio (nem o argumento nem ZBX_PASSWORD).")
    if not cfg["item_id"].isdigit():
        fail("ITEMIDZBX deve ser um número.")
    if not cfg["url_api"].startswith(("http://", "https://")):
        fail("URLAPI deve começar com 'http://' ou 'https://'.")
    if not cfg["token"]:
        fail("TOKEN não pode estar vazio (nem o argumento nem UAZ_TOKEN).")
    if not cfg["to"]:
        fail("TO não pode estar vazio.")
    if not cfg["subject"]:
        fail("SUBJECT não pode estar vazio.")
    if not cfg["msg"]:
        fail("MSG não pode estar vazio.")

    if MEDIA_MODE not in ("base64", "url"):
        fail("UAZ_MEDIA_MODE deve ser 'base64' ou 'url'.")
    if MEDIA_MODE == "url" and not MEDIA_URL:
        fail("UAZ_MEDIA_MODE='url' exige UAZ_MEDIA_URL preenchida.")

    return cfg


def fetch_graph(cfg, verify):
    """Autentica no frontend do Zabbix e baixa o PNG do gráfico do item.

    O chart.php é um endpoint do frontend e exige cookie de sessão — o token da
    API JSON-RPC não serve aqui, por isso o login é feito via formulário.
    """
    session = requests.Session()
    login_url = "{}/index.php".format(cfg["url_zbx"])

    login_data = {
        "name": cfg["user_zbx"],
        "password": cfg["pwd_zbx"],
        "enter": "Sign in",
        "autologin": 1,
        "request": "",
    }

    try:
        session.post(login_url, data=login_data, verify=verify, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        fail("falha ao conectar no Zabbix: {}".format(exc))

    # Detecta o sucesso pelo cookie de sessão, e não pelo texto da página, que
    # muda conforme o idioma do frontend.
    if "zbx_session" not in session.cookies:
        fail("falha no login do Zabbix — verifique usuário, senha e permissões.")

    graph_url = (
        "{base}/chart.php?from={_from}&to={_to}&itemids[0]={item}"
        "&type={type}&profileIdx={profile}&width={width}&height={height}"
    ).format(
        base=cfg["url_zbx"],
        _from=GRAPH_FROM,
        _to=GRAPH_TO,
        item=cfg["item_id"],
        type=GRAPH_TYPE,
        profile=GRAPH_PROFILE_IDX,
        width=GRAPH_WIDTH,
        height=GRAPH_HEIGHT,
    )

    try:
        response = session.get(graph_url, verify=verify, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        fail("falha ao obter o gráfico: {}".format(exc))

    if not response.ok:
        fail("falha ao obter o gráfico (HTTP {}).".format(response.status_code))

    # Sessão expirada devolve HTML com HTTP 200; o conteúdo precisa ser um PNG.
    if not response.content.startswith(b"\x89PNG"):
        fail(
            "o Zabbix não retornou uma imagem PNG (content-type: {}). "
            "Confira o ITEMID e as permissões do usuário.".format(
                response.headers.get("Content-Type", "desconhecido")
            )
        )

    return response.content


def post_json(cfg, path, payload, verify):
    """POST autenticado na uazapi. Devolve o objeto response."""
    url = "{}{}".format(cfg["url_api"], path)
    headers = {"Content-Type": "application/json", "token": cfg["token"]}

    try:
        return requests.post(
            url, json=payload, headers=headers, verify=verify, timeout=HTTP_TIMEOUT
        )
    except requests.RequestException as exc:
        fail("falha ao conectar na uazapi: {}".format(exc))


def send_text(cfg, verify):
    """Fallback: envia somente o texto do alerta via POST /send/text."""
    payload = {
        "number": cfg["to"],
        "text": "{}\n{}".format(cfg["subject"], cfg["msg"]),
        "delay": SEND_DELAY,
    }

    response = post_json(cfg, "/send/text", payload, verify)
    if response.status_code not in (200, 201):
        fail(
            "falha ao enviar a mensagem de texto (HTTP {}): {}".format(
                response.status_code, response.text[:500]
            )
        )

    print("Mensagem enviada sem o gráfico")


def send_media(cfg, image_bytes, verify):
    """Envia a imagem com legenda via POST /send/media.

    O campo `file` aceita uma URL ou o conteúdo em base64; a legenda vai em
    `text`. `docName` é omitido porque só se aplica a `type: document`.
    """
    if MEDIA_MODE == "url":
        file_ref = MEDIA_URL
    else:
        file_ref = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "number": cfg["to"],
        "type": "image",
        "file": file_ref,
        "text": "{}\n{}".format(cfg["subject"], cfg["msg"]),
        "mimetype": "image/png",
        "delay": SEND_DELAY,
    }

    response = post_json(cfg, "/send/media", payload, verify)

    if response.status_code in (200, 201):
        print("Mensagem e gráfico enviados com sucesso")
        return

    # Se a mídia foi recusada, o alerta ainda precisa chegar: cai para texto.
    sys.stderr.write(
        "Aviso: falha ao enviar o gráfico (HTTP {}): {}\n"
        "Reenviando apenas o texto do alerta.\n".format(
            response.status_code, response.text[:500]
        )
    )
    send_text(cfg, verify)


def main():
    cfg = parse_arguments()
    uaz_verify = tls_option("UAZ_VERIFY_TLS")
    image_bytes = fetch_graph(cfg, tls_option("ZBX_VERIFY_TLS"))
    send_media(cfg, image_bytes, uaz_verify)


if __name__ == "__main__":
    main()
