# Zabbix Whaticket API
Integração do zabbix com api do whaticket para envio de notificações.

```yaml
zabbix_export:
  version: '6.4'
  media_types:
    - name: 'WhatsApp Whaticket API'
      type: WEBHOOK
      parameters:
        - name: Authorization
          value: B6D711FCDE4D4FD5936544120E713976
        - name: Instance
          value: zabbixbot
        - name: Message
          value: '{ALERT.MESSAGE}'
        - name: ParseMode
        - name: Subject
          value: '{ALERT.SUBJECT}'
        - name: To
          value: '{ALERT.SENDTO}'
        - name: Url
          value: 'http://localhost/8080'
      attempts: '1'
      script: |
        var WhatsApp = {
            baseurl: null,
            instance: null,
            Authorization: null,
            to: null,
            message: null,
            proxy: null,
            parse_mode: null,
        
            escapeMarkup: function (str, mode) {
                switch (mode) {
                    case 'markdown':
                        return str.replace(/([_*\[`])/g, '\\$&');
        
                    case 'markdownv2':
                        return str.replace(/([_*\[\]()~`>#+\-=|{}.!])/g, '\\$&');
        
                    case 'html':
                        return str.replace(/<(\s|[^a-z\/])/g, '&lt;$1');
        
                    default:
                        return str;
                }
            },
        
            sendMessage: function () {
                var params = {
                    number: WhatsApp.to,
                    options: {
                        delay: 1200,
                        presence: "composing"
                    },
                    textMessage: {
                        "text": WhatsApp.message
                    }
                },
                data,
                response,
                request = new HttpRequest(),
                url = WhatsApp.baseurl + '/api/messages/send';
        
                if (WhatsApp.parse_mode !== null) {
                    params['parse_mode'] = WhatsApp.parse_mode;
                }
        
                if (WhatsApp.proxy) {
                    request.setProxy(WhatsApp.proxy);
                }
        
                request.addHeader('Content-Type: application/json');
                request.addHeader('Authorization: ' + WhatsApp.Authorization);
                data = JSON.stringify(params);
        
                // Remove replace() function if you want to see the exposed token in the log file.
                Zabbix.log(4, '[WhatsApp Webhook] URL: ' + url);
                Zabbix.log(4, '[WhatsApp Webhook] params: ' + data);
                response = request.post(url, data);
                Zabbix.log(4, '[WhatsApp Webhook] HTTP code: ' + request.getStatus());
        
                if (request.getStatus() == 202 || request.getStatus() == 201 || request.getStatus() == 202) {
                    // we did it. lets just exit for now.
                    Zabbix.log(4, '[WhatsApp Webhook] request sent successfully');
                    return;
                } else {
                    throw 'Unknown error. Check debug log for more information.';
                }
            }
        };
        
        try {
            var params = JSON.parse(value);
        
            if (typeof params.Url === 'undefined') {
                throw 'Incorrect value is given for parameter "Url": parameter is missing';
            }

            if (typeof params.Authorization === 'undefined') {
                throw 'Incorrect value is given for parameter "Authorization": parameter is missing';
            }
        
            WhatsApp.baseurl = params.Url;
            WhatsApp.Authorization = params.Authorization;
        
            if (params.HTTPProxy) {
                WhatsApp.proxy = params.HTTPProxy;
            } 
        
            params.ParseMode = params.ParseMode.toLowerCase();
            
            if (['markdown', 'html', 'markdownv2'].indexOf(params.ParseMode) !== -1) {
                WhatsApp.parse_mode = params.ParseMode;
            }
        
            WhatsApp.to = params.To;
            WhatsApp.message = params.Subject + '\n' + params.Message;
        
            if (['markdown', 'html', 'markdownv2'].indexOf(params.ParseMode) !== -1) {
                WhatsApp.message = WhatsApp.escapeMarkup(WhatsApp.message, params.ParseMode);
            }
        
            WhatsApp.sendMessage();
        
            return 'OK';
        }
        catch (error) {
            Zabbix.log(4, '[WhatsApp Webhook] notification failed: ' + error);
            throw 'Sending failed: ' + error + '.';
        }
      timeout: 10s
      description: //TODO
      message_templates:
        - event_source: TRIGGERS
          operation_mode: PROBLEM
          subject: 'Problem: {EVENT.NAME}'
          message: |
            Problem started at {EVENT.TIME} on {EVENT.DATE}
            Problem name: {EVENT.NAME}
            Host: {HOST.NAME}
            Severity: {EVENT.SEVERITY}
            Operational data: {EVENT.OPDATA}
            Original problem ID: {EVENT.ID}
            {TRIGGER.URL}
        - event_source: TRIGGERS
          operation_mode: RECOVERY
          subject: 'Resolved in {EVENT.DURATION}: {EVENT.NAME}'
          message: |
            Problem has been resolved in {EVENT.DURATION} at {EVENT.RECOVERY.TIME} on {EVENT.RECOVERY.DATE}
            Problem name: {EVENT.NAME}
            Host: {HOST.NAME}
            Severity: {EVENT.SEVERITY}
            Original problem ID: {EVENT.ID}
            {TRIGGER.URL}
        - event_source: TRIGGERS
          operation_mode: UPDATE
          subject: 'Updated problem: {EVENT.NAME}'
          message: |
            {USER.FULLNAME} {EVENT.UPDATE.ACTION} problem at {EVENT.UPDATE.DATE} {EVENT.UPDATE.TIME}.
            {EVENT.UPDATE.MESSAGE}
            
            Current problem status is {EVENT.STATUS}, acknowledged: {EVENT.ACK.STATUS}.
        - event_source: DISCOVERY
          operation_mode: PROBLEM
          subject: 'Discovery: {DISCOVERY.DEVICE.STATUS} {DISCOVERY.DEVICE.IPADDRESS}'
          message: |
            Discovery rule: {DISCOVERY.RULE.NAME}
            
            Device IP: {DISCOVERY.DEVICE.IPADDRESS}
            Device DNS: {DISCOVERY.DEVICE.DNS}
            Device status: {DISCOVERY.DEVICE.STATUS}
            Device uptime: {DISCOVERY.DEVICE.UPTIME}
            
            Device service name: {DISCOVERY.SERVICE.NAME}
            Device service port: {DISCOVERY.SERVICE.PORT}
            Device service status: {DISCOVERY.SERVICE.STATUS}
            Device service uptime: {DISCOVERY.SERVICE.UPTIME}
        - event_source: AUTOREGISTRATION
          operation_mode: PROBLEM
          subject: 'Autoregistration: {HOST.HOST}'
          message: |
            Host name: {HOST.HOST}
            Host IP: {HOST.IP}
            Agent port: {HOST.PORT}
```