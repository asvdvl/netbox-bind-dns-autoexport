### Default template built into the script
```jinja
{{ data.ip.ip | clear_dns }}-id{{ data.ip_id }}.
{{ (data.interface if data.interface else filler) | clear_dns }}.
{% if data.vm %}
{{ data.vm | clear_dns }}.
{% endif %}
{{ (data.device if data.device else filler) | clear_dns }}.
{{ (data.rack if data.rack else filler) | clear_dns }}.
{{ (data.site if data.site else filler) | clear_dns }}.
{{ data.region | map('clear_dns') | join('.') if data.region else filler }}
```

### For primary ips
```jinja
{% if data.vm %}
{{ data.vm | clear_dns }}.
{% endif %}
{{ (data.device if data.device else filler) | clear_dns }}.
{{ (data.rack if data.rack else filler) | clear_dns }}.
{{ (data.site if data.site else filler) | clear_dns }}.
{{ data.region | map('clear_dns') | join('.') if data.region else filler }}
```
