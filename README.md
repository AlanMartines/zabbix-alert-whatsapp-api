# Zabbix Alert Whatsapp API
- Integração do zabbix com api da [ConnectZap](https://www.connectzap.com.br/api) para envio de notificações.
- Integração do zabbix com api do [Whaticket](https://github.com/AlanMartines/whaticket_baileys) para envio de notificações.
- Integração do zabbix com api da [Evolution v2.2.0](https://doc.evolution-api.com/v2/pt/get-started/introduction) para envio de notificações.


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


# Contribuições

[Contribuições](CONTRIBUTING.md) são bem-vindas! Por favor, abra uma issue ou pull request.

# Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.
