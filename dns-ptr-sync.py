from extras.scripts import Script, BooleanVar, MultiObjectVar, StringVar, TextVar, ObjectVar, ChoiceVar

from dcim.models import Device
from ipam.models import IPAddress, Service
from core.models import ObjectType
from extras.models import ExportTemplate
from virtualization.models import VirtualMachine
from extras.models.customfields import CustomField
from django.contrib.contenttypes.models import ContentType

from netbox_dns.models import Zone, Record
from netbox_dns.choices import RecordTypeChoices

import re
from pprint import pp, pformat
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
        name = "Create templates"
        description = "Optionally, adds standard templates for easy use"

    def run(self, data, commit):
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

    allow_multi_records = BooleanVar(
        description="Allow records to have multiple addresses",
        default=True,
    )

    iterate_over = ChoiceVar(
        choices=(
            ('ip', "IP address list"),
            ('pIP', "Devices primary IP's"),
            ('services', "Services IP's"),
        ),
        default='ip'
    )

    select_zones = MultiObjectVar(
        label="Specify Zone(s)",
        model=Zone,
        required=True
    )

    default_filler = StringVar(
        label="default filler for unknown values",
        default="no-data",
        required=False
    )

    remove_chain_of_fillers = BooleanVar(
        default=True,
    )

    remove_other_records_in_zone = BooleanVar(
        description="BE CAREFUL! this will delete all other records in the zone, useful when you allocate a separate zone for generated records, which is recommended",
        default=True,
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
{{ (data.device if data.device else filler) | clear_dns }}""",
        description="all line breaks will be removed, use them for formatting"
    )

    disable_ptr = BooleanVar(
        description='simple value pass-through to record',
        default=False,
    )

    def delete_record(self, record):
        self.log_info(f'removing record `{record.name}`: `{record.value}`')
        record.delete()

    def run(self, data, commit):
        self.log_debug(f'data={pformat(data)}')

        zones = data["select_zones"]

        name_template = data['name_template'] if data['template'] is None else data['template'].template_code
        name_template = name_template.replace('\n', '').replace('\r', '')

        default_filler = data['default_filler']
        multi_record = data['allow_multi_records']
        remove_other_records_in_zone = data['remove_other_records_in_zone']

        for zone in zones:
            self.log_debug(f'Zone: `{zone}`')
            iterate_obj = []

            tenant = zone.tenant

            if zone.tenant is None:
                self.log_warning(f"zone: {zone.name}, has tenant {zone.tenant}")

            def get_vm_and_dev(tenant):
                devices = Device.objects.filter(tenant=tenant)
                vms = VirtualMachine.objects.filter(tenant=tenant)
                return [devices, vms]

            match (data['iterate_over']):
                case ('ip'):
                    iterate_obj = IPAddress.objects.filter(tenant = tenant)

                case ('pIP'):
                    machines = get_vm_and_dev(tenant)
                    iterate_obj = []
                    for machine in machines:
                        for device in machine:
                            if device.primary_ip4:
                                iterate_obj.append(device.primary_ip4)
                            if device.primary_ip6:
                                iterate_obj.append(device.primary_ip6)

                case ('services'):
                    machines = get_vm_and_dev(tenant)
                    iterate_obj = []
                    
                    services = Service.objects.filter(device__in=machines[0]) | Service.objects.filter(virtual_machine__in=machines[1])
                    for service in services:
                        if service.ipaddresses.exists():
                            #There may be several services at the address(and vice versa), we register the services and ip and divide in the next cycle
                            for ip in service.ipaddresses.all():
                                iterate_obj.append((service, ip))

                case (_):
                    self.log_failure("unknown iterate option")

            jenv = Environment()
            jenv.filters['clear_dns'] = dns_name_clean

            template = jenv.from_string(name_template)
            valid_records = []
            domains = []
            
            for ip in iterate_obj:
                context = {
                    'service': None,
                    'interface': None,
                    'vm': None,
                    'device': [],
                    'rack': [],
                    'site': [],
                    'regions': [[]],
                }

                if data['iterate_over'] == 'services':
                    context['service'] = ip[0]
                    ip = ip[1]

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

                if len(subdomain) == 0:
                    self.log_info(f"got empty subdomain for ip {ip.address.ip}")
                    continue

                record, created = Record.objects.get_or_create(
                    name = subdomain,
                    zone = zone,
                    type = RecordTypeChoices.AAAA if ip.family == 6 else RecordTypeChoices.A,
                    value = ip.address.ip,
                    defaults = {
                        'disable_ptr': data['disable_ptr'],
                        'tenant': tenant
                    }
                )

                if created:
                    self.log_info(f'added `{subdomain}`: `{record.value}` record')
                else:
                    self.log_debug(f'`{subdomain}`: `{record.value}`(DNS)/`{ip.address.ip}`(script) record already exist')
                
                if multi_record or not subdomain in domains:
                    valid_records.append((subdomain, str(ip.address.ip)))
                    domains.append(subdomain)
                elif remove_other_records_in_zone:
                    self.log_info(f'the record was not added to the list of created entries and will be deleted')
            # end for zone

            if remove_other_records_in_zone:
                for record in zone.records.filter(type__in=[RecordTypeChoices.A, RecordTypeChoices.AAAA]):
                    if (record.name, record.value) not in valid_records:
                        self.delete_record(record)
