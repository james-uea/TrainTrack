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
