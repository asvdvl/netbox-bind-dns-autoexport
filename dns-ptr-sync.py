from extras.scripts import Script, BooleanVar
from ipam.models import IPAddress
from extras.models.customfields import CustomField
from netbox_dns.models import NameServer, Zone
from core.models import ObjectType

from pprint import pp

name = "Add devices to DNS"
ptr_zone_cust_field_name = 'ptr_zone'

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

    def run(self, data, commit):
        pp(data)
        nameservers = NameServer.objects.all()
        for server in nameservers:
            if not ptr_zone_cust_field_name in server.custom_field_data:
                raise ValueError("ptr_zone not found! Please run `Add Ptr Zone To Cust Fields` script first")
            all_ips = {}
            if server.tenant is not None or data['allow_none_tenant']: #ignore None tenant if allow_none_tenant
                all_ips = IPAddress.objects.filter(tenant = server.tenant)
            else:
                continue
            pp(all_ips)
