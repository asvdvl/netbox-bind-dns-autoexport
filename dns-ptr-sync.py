from extras.scripts import Script, BooleanVar, MultiObjectVar, StringVar, TextVar
from ipam.models import IPAddress
from extras.models.customfields import CustomField
from netbox_dns.models import NameServer, Zone
from core.models import ObjectType
from netbox_dns.choices import RecordTypeChoices

from pprint import pp
import re
from jinja2 import Environment

name = "Add devices to DNS"
ptr_zone_cust_field_name = 'ptr_zone'

def dns_name_clean(name):
    defises = re.sub(r'[^a-zA-Z0-9-]', '-', str(name)) #replaces all invalid characters with -
    return re.sub(r'^-+|-+$', '', defises) #deletes everything - from the beginning and from the end of the line

class AddPtrZoneToCustFields(Script):
    class Meta:
        name = "Add Ptr Zone To Cust Fields"
        description = ""
    def run(self, data, commit):
        fields=CustomField.objects.filter(name = ptr_zone_cust_field_name)
        #for item in CustomField.objects.filter(name = 'ptr_exmlpl'):
        #    pp(item)
        if len(fields) == 0:
            custom_field = CustomField.objects.create(
                name=ptr_zone_cust_field_name,
                label="PTR export zone",
                type='object',
                required=False,
                related_object_type=ObjectType.objects.get_for_model(Zone),
                is_cloneable=True,
                description="Zone where DNS records for IP addresses will be generated",
                default=None
            )
            custom_field.object_types.set([ObjectType.objects.get_for_model(NameServer)])

class AddDevicesToDNS(Script):
    class Meta:
        name = "Add devices to DNS"

    allow_none_tenant = BooleanVar(
        description="Allow tenant to be None in nameserver",
        default=False,
    )

    only_for_servers = MultiObjectVar(
        label="Specify NameServer",
        model=NameServer,
        required=False
    )

    name_template = TextVar(
        label="DNS path template",
        default="""{{ data.ip.ip | clear_dns }}-id{{ data.ip_id }}.
{{ (data.interface if data.interface else filler) | clear_dns }}.
{{ (data.device if data.device else filler) | clear_dns }}.
{{ (data.rack if data.rack else filler) | clear_dns }}.
{{ (data.site if data.site else filler) | clear_dns }}.
{{ data.region | map('clear_dns') | join('.') if data.region else filler }}
""",
        description="all line breaks will be removed, use them for formatting"
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

    def run(self, data, commit):
        pp(data)
        nameservers = data["only_for_servers"] if len(data["only_for_servers"]) > 0 else NameServer.objects.all()

        for server in nameservers:
            if not ptr_zone_cust_field_name in server.custom_field_data:
                reason = "ptr_zone not found! Please run `Add Ptr Zone To Cust Fields` script first"
                self.log_failure(reason)
                raise ValueError(reason)

            if server.custom_field_data[ptr_zone_cust_field_name] is None:
                self.log_failure(f"ptr zone is empty for `{server}`")
                continue

            all_ips = {}
            if server.tenant is not None or data['allow_none_tenant']: #ignore None tenant if allow_none_tenant
                all_ips = IPAddress.objects.filter(tenant = server.tenant)
            else:
                self.log_info(f"skip server: {server.name}, tenant is {server.tenant}")
                continue

            jenv = Environment()
            jenv.filters['clear_dns'] = dns_name_clean

            template = jenv.from_string(data['name_template'].replace('\n', '').replace('\r', ''))
            valid_records = []
            zone = Zone.objects.get(pk=server.custom_field_data[ptr_zone_cust_field_name])

            for ip in all_ips:
                context = {
                    'interface': None,
                    'device': [],
                    'rack': [],
                    'site': [],
                    'regions': [[]],
                }

                context['ip'] = ip.address
                context['ip_id'] = str(ip.id)
                
                if ip.assigned_object:
                    context['interface'] = ip.assigned_object

                    device = ip.assigned_object.device
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

