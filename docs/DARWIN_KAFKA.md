# Darwin's Kafka Server

## Messages

### Keys
dict_keys(['destination', 'messageID', 'type', 'priority', 'redelivered', 'messageType', 'deliveryMode', 'bytes', 'replyTo', 'correlationID', 'expiration', 'text', 'map', 'properties', 'timestamp'])

**Example**:
```
%% prod-1010-Darwin-Train-Information-Push-Port-IIII2_0-JSON [0] at offset 327295935 with key b'{"messageID":"ID:ip-100-80-26-50.eu-west-1.compute.internal-45175-639239848127001540-1:11:1:1:4367365"}':
b'{"destination":{"name":"Consumer.rdmportal.VirtualTopic.PushPort-v18","destinationType":"queue"},"messageID":"ID:ip-100-80-26-50.eu-west-1.compute.internal-45175-639239848127001540-1:11:1:1:4367365","type":null,"priority":5,"redelivered":false,"messageType":"bytes","deliveryMode":1,"bytes":"{\\"ts\\":\\"2026-09-04T23:49:02.185589+01:00\\",\\"version\\":\\"18.0\\",\\"uR\\":{\\"updateOrigin\\":\\"TD\\",\\"TS\\":{\\"rid\\":\\"202609048087246\\",\\"uid\\":\\"P87246\\",\\"ssd\\":\\"2026-09-04\\",\\"LateReason\\":\\"520\\",\\"Location\\":{\\"tpl\\":\\"WDULWCH\\",\\"wta\\":\\"23:19\\",\\"wtd\\":\\"23:20\\",\\"pta\\":\\"23:19\\",\\"ptd\\":\\"23:20\\",\\"arr\\":{\\"at\\":\\"23:47\\",\\"atClass\\":\\"Automatic\\",\\"src\\":\\"TD\\"},\\"dep\\":{\\"at\\":\\"23:48\\",\\"atClass\\":\\"Automatic\\",\\"src\\":\\"TD\\"},\\"plat\\":{\\"platsrc\\":\\"A\\",\\"conf\\":\\"true\\",\\"\\":\\"1\\"},\\"length\\":\\"8\\"}}}}","replyTo":null,"correlationID":null,"expiration":1788562742185,"text":null,"map":null,"properties":{"Username":{"boolean":null,"string":"externalmqapps","byte":null,"double":null,"bytes":null,"propertyType":"string","short":null,"integer":null,"float":null,"long":null},"PushPortSequence":{"boolean":null,"string":"4367364","byte":null,"double":null,"bytes":null,"propertyType":"string","short":null,"integer":null,"float":null,"long":null}},"timestamp":1788562142185}'
```

#### destination
#### messageType
#### bytes
This key contains the raw updates from Darwin

#### Origin Types
TD
CIS
Trust
Darwin
GPS

### Status
```
{'rid': '202609048315515', 'uid': 'S15515', 'ssd': '2026-09-04', 'Location': [{'tpl': 'PRINRIS', 'wta': '00:38:30', 'wtd': '00:39:30', 'pta': '00:39', 'ptd': '00:39', 'arr': {'at': '00:37', 'atClass': 'Automatic', 'src': 'TRUST', 'srcInst': 'Auto'}, 'dep': {'et': '00:39', 'src': 'Darwin'}, 'plat': {'platsrc': 'M', '': '2'}, 'length': '5'}, {'tpl': 'LTLKMBL', 'wtp': '00:45', 'pass': {'et': '00:44', 'src': 'Darwin'}, 'plat': {'platsup': 'true', 'platsrc': 'M', '': '1'}, 'length': '5'}, {'tpl': 'MSHLLC', 'wtp': '00:48', 'pass': {'et': '00:47', 'src': 'Darwin'}, 'length': '5'}, {'tpl': 'AYLSBRY', 'wta': '00:55', 'pta': '00:55', 'arr': {'et': '00:55', 'wet': '00:52', 'src': 'Darwin'}, 'plat': {'platsrc': 'M', '': '2'}, 'length': '5'}]}

{'rid': '202609047680912', 'uid': 'L80912', 'ssd': '2026-09-04', 'Location': {'tpl': 'STAINES', 'wta': '00:37', 'pta': '00:37', 'arr': {'et': '00:38', 'src': 'TD'}, 'plat': {'platsup': 'true', 'cisPlatsup': 'true', '': '1'}, 'length': '8'}}

{'rid': '202609057161941', 'uid': 'G61941', 'ssd': '2026-09-05', 'Location': [{'tpl': 'CLAPTNJ', 'wtp': '00:30:30', 'pass': {'at': '00:36', 'atClass': 'Automatic', 'src': 'TRUST', 'srcInst': 'Auto'}}, {'tpl': 'STJMSST', 'wta': '00:32:30', 'wtd': '00:33', 'pta': '00:33', 'ptd': '00:33', 'arr': {'et': '00:38', 'src': 'Darwin'}, 'dep': {'et': '00:38', 'src': 'Darwin'}, 'plat': {'platsrc': 'A', 'conf': 'true', '': '2'}}, {'tpl': 'WLTWCEN', 'wta': '00:34', 'wtd': '00:35', 'pta': '00:35', 'ptd': '00:35', 'arr': {'et': '00:39', 'src': 'Darwin'}, 'dep': {'et': '00:40', 'src': 'Darwin'}, 'plat': '2'}, {'tpl': 'WDST', 'wta': '00:37', 'wtd': '00:37:30', 'pta': '00:37', 'ptd': '00:37', 'arr': {'et': '00:42', 'src': 'Darwin'}, 'dep': {'et': '00:42', 'src': 'Darwin'}, 'plat': '2'}, {'tpl': 'HGHMSPK', 'wta': '00:40', 'wtd': '00:40:30', 'pta': '00:40', 'ptd': '00:40', 'arr': {'et': '00:45', 'src': 'Darwin'}, 'dep': {'et': '00:45', 'src': 'Darwin'}, 'plat': '2'}, {'tpl': 'CHINGFD', 'wta': '00:45', 'pta': '00:46', 'arr': {'et': '00:50', 'src': 'Darwin'}, 'plat': '2'}]}

{'rid': '202609056736455', 'uid': 'C36455', 'ssd': '2026-09-05', 'Location': {'tpl': 'ABWDXR', 'wtd': '00:36', 'dep': {'at': '00:36', 'atClass': 'Automatic', 'src': 'TD'}, 'plat': {'platsup': 'true', 'platsrc': 'A', '': '4'}}}
```
