from extras.scripts import Script, BooleanVar, MultiObjectVar, StringVar, TextVar, ObjectVar, ChoiceVar

from dcim.models import Device
from ipam.models import IPAddress
from core.models import ObjectType
from extras.models import ExportTemplate
from extras.models.customfields import CustomField
from django.contrib.contenttypes.models import ContentType

from netbox_dns.models import NameServer, Zone
from netbox_dns.choices import RecordTypeChoices

import re
from pprint import pp
from jinja2 import Environment

name = "Add devices to DNS"
ptr_zone_cust_field_name_default = 'ptr_zone'
ENABLE_FILTER_TEMPLATE_SELECTION=True   #enables template filter in AddDevicesToDNS
FILTER_TEMPLATE_PREFIX='dnsPtrGen-'

def dns_name_clean(name):
    defises = re.sub(r'[^a-zA-Z0-9-]', '-', str(name)) #replaces all invalid characters with -
    return re.sub(r'^-+|-+$', '', defises) #deletes everything - from the beginning and from the end of the line

class AddPtrZoneToCustFields(Script):
    class Meta:
        name = "Add Ptr Zone To Cust Fields"
        description = ""

    ptr_zone_cust_field_name = StringVar(
        label="zone name",
        default=ptr_zone_cust_field_name_default,
        description="Enter your value here if you have multiple zones for different purposes"
    )

    def run(self, data, commit):
        ptr_zone_name = data["ptr_zone_cust_field_name"]
        fields=CustomField.objects.filter(name = ptr_zone_name)

        if len(fields) == 0:
            custom_field = CustomField.objects.create(
                name=ptr_zone_name,
                label=f"PTR export zone({ptr_zone_name})",
                type='object',
                required=False,
                related_object_type=ObjectType.objects.get_for_model(Zone),
                is_cloneable=True,
                description="Zone where DNS records for IP addresses will be generated",
                default=None
            )
            custom_field.object_types.set([ObjectType.objects.get_for_model(NameServer)])
        
        templates = {
            "per IP(ip-ipID.iface.(vm).device.rack.site.region[])": """{{ data.ip.ip | clear_dns }}-id{{ data.ip_id }}.
{{ (data.interface if data.interface else filler) | clear_dns }}.
{% if data.vm %}
{{ data.vm | clear_dns }}.
{% endif %}
{{ (data.device if data.device else filler) | clear_dns }}.
{{ (data.rack if data.rack else filler) | clear_dns }}.
{{ (data.site if data.site else filler) | clear_dns }}.
{{ data.region | map('clear_dns') | join('.') if data.region else filler }}""",
            
            "per primaty IPs((vm).device.rack.site.region[])": """{% if data.vm %}
{{ data.vm | clear_dns }}.
{% endif %}
{{ (data.device if data.device else filler) | clear_dns }}.
{{ (data.rack if data.rack else filler) | clear_dns }}.
{{ (data.site if data.site else filler) | clear_dns }}.
{{ data.region | map('clear_dns') | join('.') if data.region else filler }}""",
        }

        IPAddress_content_type = ContentType.objects.get_for_model(IPAddress)
        for templ_name in templates:
            template_name = FILTER_TEMPLATE_PREFIX+templ_name if ENABLE_FILTER_TEMPLATE_SELECTION else templ_name
            code = templates[templ_name]

            exist_template, created = ExportTemplate.objects.get_or_create(
                name=template_name,
                defaults={
                    "template_code": code,
                    "as_attachment": False,
                },
            )

            if created:
                exist_template.object_types.set([IPAddress_content_type.id])
                self.log_info(f"Template '{template_name}' was created.")
            else:
                self.log_debug(f"Template '{template_name}' already exists.")
            

class AddDevicesToDNS(Script):
    class Meta:
        name = "Add devices to DNS"

    allow_none_tenant = BooleanVar(
        description="Allow tenant to be None in nameserver",
        default=False,
    )

    iterate_over = ChoiceVar(
        choices=(
            ('ip', "IP address list"),
            ('pIP', "Devices primary IP's"),
        ),
        default='ip'
    )

    only_for_servers = MultiObjectVar(
        label="Specify NameServer",
        model=NameServer,
        required=False
    )

    default_filler = StringVar(
        label="default filler for unknown values",
        default="no-data"
    )

    remove_chain_of_fillers = BooleanVar(
        default=True,
    )

    remove_other_records_in_zone = BooleanVar(
        description="BE CAREFUL! this will delete all other records in the zone, useful when you allocate a separate zone for generated records, which is recommended",
        default=False,
    )

    template = ObjectVar(
        label="Select template",
        description="selectable from custom templates, if selected, the template below will be ignored",
        model=ExportTemplate,
        required=False,
        query_params=(
            {"name__isw": FILTER_TEMPLATE_PREFIX} if ENABLE_FILTER_TEMPLATE_SELECTION else {}
        ),
    )

    name_template = TextVar(
        label="DNS path template",
        default="""{{ data.ip.ip | clear_dns }}-id{{ data.ip_id }}.
{% if data.vm %}
{{ data.vm | clear_dns }}.
{% endif %}
{{ (data.device if data.device else filler) | clear_dns }}
""",
        description="all line breaks will be removed, use them for formatting"
    )

    ptr_zone_name = ObjectVar(
        label="Zone name",
        description="",
        model=CustomField,
        required=True,
        query_params=(
            {"related_object_type": "netbox_dns.zone"}
        ),
        default=CustomField.objects.filter(
            name=ptr_zone_cust_field_name_default
        ).first().id
    )

    def run(self, data, commit):
        pp(data)
        nameservers = data["only_for_servers"] if len(data["only_for_servers"]) > 0 else NameServer.objects.all()
        name_template = data['name_template'] if data['template'] is None else data['template'].template_code
        name_template = name_template.replace('\n', '').replace('\r', '')
        default_filler = data['default_filler']

        for server in nameservers:
            ptr_zone_name = data["ptr_zone_name"].name

            if server.custom_field_data[ptr_zone_name] is None:
                self.log_warning(f"ptr zone is empty for `{server}`")
                continue

            iterate_obj = []
            if server.tenant is None and not data['allow_none_tenant']: #ignore None tenant if allow_none_tenant
                self.log_info(f"skip server: {server.name}, tenant is {server.tenant}")
                continue                    

            match (data['iterate_over']):
                case ('ip'):
                        iterate_obj = IPAddress.objects.filter(tenant = server.tenant)

                case ('pIP'):
                    devices = Device.objects.filter(tenant=server.tenant)
                    iterate_obj = []
                    for device in devices:
                        if device.primary_ip4:
                            iterate_obj.append(device.primary_ip4)
                        if device.primary_ip6:
                            iterate_obj.append(device.primary_ip6)

                    pass

                case (_):
                    self.log_failure("unknown iterate option")

            jenv = Environment()
            jenv.filters['clear_dns'] = dns_name_clean

            template = jenv.from_string(name_template)
            valid_records = []
            zone = Zone.objects.get(pk=server.custom_field_data[ptr_zone_name])

            for ip in iterate_obj:
                context = {
                    'interface': None,
                    'vm': None,
                    'device': [],
                    'rack': [],
                    'site': [],
                    'regions': [[]],
                }

                context['ip'] = ip.address
                context['ip_id'] = str(ip.id)
                
                if ip.assigned_object:
                    context['interface'] = ip.assigned_object

                    device = None
                    if ip.assigned_object_type.model == 'interface':
                        device = ip.assigned_object.device
                    elif ip.assigned_object_type.model == 'vminterface':
                        context['vm'] = ip.assigned_object.parent_object
                        device = context['vm'].device

                    if device is not None:
                        context['device'] = device

                        if device.rack:
                            context['rack'] = device.rack

                        context['site'] = device.site

                        region = device.site.region
                        chain = []
                        while region:
                            chain.append(region)
                            region = region.parent
                        context['region'] = chain

                subdomain = template.render(data=context, filler=dns_name_clean(data['default_filler']))
                if data['remove_chain_of_fillers']:
                    subdomain = re.sub(rf"(\.{data['default_filler']}){{2,}}", f".{data['default_filler']}", subdomain)

                fixed_dots_sd = re.sub(r'\.+', '.', subdomain)
                fixed_dots_sd = re.sub(r'^\.+|\.+$', '', fixed_dots_sd)
                if fixed_dots_sd != subdomain:
                    self.log_warning(f"found wrong placed dots, was: `{subdomain}` now: `{fixed_dots_sd}`")
                    subdomain = fixed_dots_sd

                self.log_debug(f"got `{subdomain}` for ip `{ip.address}`")
                
                records = zone.records
                if len(records.model.objects.filter(name=subdomain)) == 0:
                    records.model.objects.create(
                        name = subdomain,
                        value = ip.address.ip,
                        zone = zone,
                        type = RecordTypeChoices.AAAA if ip.family == 6 else RecordTypeChoices.A,
                        tenant = zone.tenant
                    )
                    self.log_info(f'added `{subdomain}` record, zone `{zone.name}`')
                else:
                    self.log_debug(f'`{subdomain}` record, already exist in zone `{zone.name}`')
                
                valid_records.append(subdomain)
            
            if data['remove_other_records_in_zone']:
                for record in zone.records.exclude(name__in=valid_records).filter(type__in=[RecordTypeChoices.A, RecordTypeChoices.AAAA]):
                    if record.name not in valid_records:
                        self.log_info(f'removing {record.name} in {zone.name}')
                        record.delete()

script_order = (AddPtrZoneToCustFields, AddDevicesToDNS)