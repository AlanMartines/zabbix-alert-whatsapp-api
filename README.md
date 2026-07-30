# Zabbix Alert WhatsApp API

Media types e scripts de alerta para enviar notificações do Zabbix para o WhatsApp,
através de diferentes provedores de API.

## Provedores suportados

| Provedor | Autenticação | Endpoint de texto | Envio para grupo |
|---|---|---|---|
| [ConnectZap](https://www.connectzap.com.br/api) | `SessionName` no corpo | `/sistema/sendText` | `/sistema/sendTextGrupo` |
| [Whaticket](https://github.com/AlanMartines/whaticket_baileys) | header `Authorization` | `/api/messages/send` | `/api/messages/sendGroup` |
| [Evolution API](https://doc.evolution-api.com/v2/pt/get-started/introduction) v2 | header `apikey` | `/message/sendText/{instance}` | mesmo endpoint |
| [Evolution Go](https://docs.evolutionfoundation.com.br/evolution-go/) | header `apikey` | `/send/text` | mesmo endpoint |
| [uazapiGO](https://docs.uazapi.com/) v2.1 | header `token` | `/send/text` | mesmo endpoint |

A instância é identificada de formas diferentes: no path (Evolution API), pelo
próprio token (Evolution Go e uazapiGO) ou no corpo da requisição (ConnectZap e
Whaticket). Para grupos, informe o ID do grupo em *Send to*.

## Estrutura do repositório

```
zbx_mediatypes/                     Media types (webhook), mensagens sem emojis
zbx_mediatypes_use_emojis/          Media types (webhook), mensagens com emojis
zbx_mediatypes_use_emojis_graphic/  Media types (script), enviam o gráfico do item
alertscripts/                       Scripts Python usados pelos media types do tipo SCRIPT
```

As três pastas contêm o mesmo conjunto de integrações; escolha **uma** conforme o
formato de mensagem desejado. Os media types do tipo `SCRIPT` dependem dos arquivos
em `alertscripts/`.

## Requisitos

- **Zabbix 7.0 ou superior** — os arquivos declaram `version: '7.0'` e o frontend
  recusa importar exports de versão superior à sua;
- Python 3 e a biblioteca `requests` no servidor Zabbix (apenas para os media types
  do tipo `SCRIPT`);
- Base de dados com `utf8mb4` para usar as mensagens com emojis (veja abaixo).

## Instalação

### 1. Importar o media type

No frontend: **Alerts → Media types → Import**, e selecione o `.yaml` do provedor
desejado, de uma das três pastas.

### 2. Instalar os scripts de alerta (apenas para os media types "Graphic")

Copie o script correspondente para o diretório `AlertScriptsPath` do servidor
Zabbix (por padrão `/usr/lib/zabbix/alertscripts/`):

```bash
install -o zabbix -g zabbix -m 0750 \
  alertscripts/whatsapp-graph-uazapi.py /usr/lib/zabbix/alertscripts/
pip install requests
```

Confirme o caminho configurado em `/etc/zabbix/zabbix_server.conf`:

```
AlertScriptsPath=/usr/lib/zabbix/alertscripts
```

### 3. Configurar os parâmetros

Em **Alerts → Media types**, edite o media type importado e substitua os
marcadores. Os valores entre `<>` são obrigatórios:

| Provedor | Parâmetros a preencher |
|---|---|
| ConnectZap / Whaticket | `Url`, `Authorization` |
| Evolution API | `Url`, `ApiKey`, `Instance` |
| Evolution Go | `Url`, `ApiKey` |
| uazapiGO | `Url` (com o subdomínio da conta), `Token` |

### 4. Associar ao usuário e criar a ação

Em **Users → Users → Media**, adicione o media type ao usuário e informe o número
de destino em *Send to* (formato internacional, somente dígitos — ex.: `5511999999999`).
Depois crie a ação em **Alerts → Actions → Trigger actions**.

Os media types do tipo `SCRIPT` vêm com `status: DISABLED`. Habilite-os apenas
depois de instalar o script e testar o envio.

## Alertas com gráfico

Os scripts em `alertscripts/` autenticam no frontend do Zabbix, baixam o PNG do
gráfico do item (`chart.php`) e enviam a imagem com a mensagem como legenda.

| Script | Argumentos |
|---|---|
| `whatsapp-graph-connectzap.py` | `URLZBX USERZBX PWDZBX ITEMIDZBX URLAPI TOKEN TO SUBJECT MSG` |
| `whatsapp-graph-evolution-api.py` | `URLZBX USERZBX PWDZBX ITEMIDZBX URLAPI APIKEY INSTANCE TO SUBJECT MSG` |
| `whatsapp-graph-evolution-go.py` | `URLZBX USERZBX PWDZBX ITEMIDZBX URLAPI APIKEY TO SUBJECT MSG` |
| `whatsapp-graph-uazapi.py` | `URLZBX USERZBX PWDZBX ITEMIDZBX URLAPI TOKEN TO SUBJECT MSG` |

Teste pela linha de comando antes de habilitar o media type:

```bash
/usr/lib/zabbix/alertscripts/whatsapp-graph-uazapi.py \
  https://zabbix.seudominio.com Admin senha 48061 \
  https://suaconta.uazapi.com SEU_TOKEN 5511999999999 'Teste' 'Mensagem de teste'
```

Em caso de falha o script encerra com status diferente de zero e imprime o corpo
da resposta da API, que o Zabbix registra no log da ação.

### Segredos por variável de ambiente

Argumentos de processo são visíveis para qualquer usuário do host via `ps aux`.
Prefira passar os segredos pelo ambiente, deixando o argumento correspondente
vazio (`''`):

| Variável | Substitui |
|---|---|
| `ZBX_USER` / `ZBX_PASSWORD` | usuário e senha do Zabbix |
| `EVO_APIKEY` | apikey da Evolution API |
| `EVOGO_APIKEY` | token do Evolution Go |
| `UAZ_TOKEN` | token da uazapi |

### Outras variáveis

| Variável | Padrão | Descrição |
|---|---|---|
| `ZBX_VERIFY_TLS` | `true` | `true`, `false` ou caminho para o CA bundle |
| `EVO_VERIFY_TLS` / `EVOGO_VERIFY_TLS` / `UAZ_VERIFY_TLS` | `true` | idem, para a chamada à API do WhatsApp |
| `ZBX_GRAPH_FROM` | `now-6h` | janela do gráfico |
| `ZBX_GRAPH_WIDTH` / `ZBX_GRAPH_HEIGHT` | `1024` / `220` | dimensões em pixels |
| `ZBX_HTTP_TIMEOUT` | `30` | timeout das requisições, em segundos |
| `EVOGO_MEDIA_MODE` / `UAZ_MEDIA_MODE` | `base64` | `base64` embute a imagem; `url` usa uma URL pública |
| `EVOGO_MEDIA_URL` / `UAZ_MEDIA_URL` | — | URL pública do PNG, obrigatória quando o modo é `url` |

Se o seu Zabbix usa certificado autoassinado, aponte `ZBX_VERIFY_TLS` para o CA
interno em vez de desativar a validação — desligá-la expõe as credenciais enviadas
no login.

# Template de Alertas do Zabbix

## Alertas de Problemas (Triggers)
- **Fonte do Evento**: TRIGGERS
- **Modo de Operação**: PROBLEM
- **Assunto**: "Problem: {EVENT.NAME}"
- **Mensagem**:
  - Início do problema às `{EVENT.TIME}` em `{EVENT.DATE}`
  - Nome do problema: `{EVENT.NAME}`
  - Host: `{HOST.NAME}`
  - Severidade: `{EVENT.SEVERITY}`
  - Dados operacionais: `{EVENT.OPDATA}`
  - ID original do problema: `{EVENT.ID}`
  - URL do Trigger: `{TRIGGER.URL}`

## Alertas de Recuperação (Triggers)
- **Fonte do Evento**: TRIGGERS
- **Modo de Operação**: RECOVERY
- **Assunto**: "Resolved in {EVENT.DURATION}: {EVENT.NAME}"
- **Mensagem**:
  - Problema resolvido em `{EVENT.DURATION}` às `{EVENT.RECOVERY.TIME}` em `{EVENT.RECOVERY.DATE}`
  - Nome do problema: `{EVENT.NAME}`
  - Host: `{HOST.NAME}`
  - Severidade: `{EVENT.SEVERITY}`
  - ID original do problema: `{EVENT.ID}`
  - URL do Trigger: `{TRIGGER.URL}`

## Atualizações de Problemas (Triggers)
- **Fonte do Evento**: TRIGGERS
- **Modo de Operação**: UPDATE
- **Assunto**: "Updated problem: {EVENT.NAME}"
- **Mensagem**:
  - `{USER.FULLNAME}` `{EVENT.UPDATE.ACTION}` o problema em `{EVENT.UPDATE.DATE}` `{EVENT.UPDATE.TIME}`.
  - Mensagem de atualização: `{EVENT.UPDATE.MESSAGE}`
  - Status atual do problema: `{EVENT.STATUS}`, reconhecimento: `{EVENT.ACK.STATUS}`.

## Descoberta de Dispositivos (Discovery)
- **Fonte do Evento**: DISCOVERY
- **Modo de Operação**: PROBLEM
- **Assunto**: "Discovery: {DISCOVERY.DEVICE.STATUS} {DISCOVERY.DEVICE.IPADDRESS}"
- **Mensagem**:
  - Regra de descoberta: `{DISCOVERY.RULE.NAME}`
  - IP do dispositivo: `{DISCOVERY.DEVICE.IPADDRESS}`
  - DNS do dispositivo: `{DISCOVERY.DEVICE.DNS}`
  - Status do dispositivo: `{DISCOVERY.DEVICE.STATUS}`
  - Tempo de atividade do dispositivo: `{DISCOVERY.DEVICE.UPTIME}`
  - Nome do serviço do dispositivo: `{DISCOVERY.SERVICE.NAME}`
  - Porta do serviço do dispositivo: `{DISCOVERY.SERVICE.PORT}`
  - Status do serviço do dispositivo: `{DISCOVERY.SERVICE.STATUS}`
  - Tempo de atividade do serviço do dispositivo: `{DISCOVERY.SERVICE.UPTIME}`

## Auto-registro de Hosts (Auto Registration)
- **Fonte do Evento**: AUTOREGISTRATION
- **Modo de Operação**: PROBLEM
- **Assunto**: "Autoregistration: {HOST.HOST}"
- **Mensagem**:
  - Nome do host: `{HOST.HOST}`
  - IP do host: `{HOST.IP}`
  - Porta do agente: `{HOST.PORT}`

# Nota Importante para Uso de Emojis nos Alertas

Ao configurar emojis nos alertas do Zabbix, é crucial garantir que a base de dados do Zabbix esteja configurada com as codificações apropriadas para suportar emojis. As configurações necessárias são:

- **Conjunto de Caracteres (Character Set)**: `utf8mb4`
- **Collation**: `utf8mb4_unicode_ci`

Essas configurações garantem que a base de dados possa armazenar e processar corretamente emojis e outros caracteres Unicode que requerem mais de 3 bytes de armazenamento.

Certifique-se de que estas configurações estejam aplicadas tanto no nível do servidor de banco de dados quanto nas configurações específicas do banco de dados do Zabbix para evitar quaisquer problemas de compatibilidade ou exibição de caracteres.


# Testado com
- mysql: 8.0.
- zabbix-snmptraps: 7.0.
- zabbix-server: 7.0.
- zabbix-frontend: 7.0.
- zabbix-agent 2: 7.0.

> Todos os media types declaram `version: '7.0'`, alinhados com as versões acima.


# Contribuições

[Contribuições](CONTRIBUTING.md) são bem-vindas! Por favor, abra uma issue ou pull request.

# Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.
