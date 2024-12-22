# Add Devices to DNS Script

This script adds PTR records to a DNS zone based on the devices and their IP addresses. It can be used to automate the creation of DNS records for devices within a given zone, ensuring all necessary information is included based on device properties.

## Requirements

- **NetBox**: This script is designed to work with NetBox and assumes you have access to its models.
- [**netbox-plugin-dns**](https://github.com/peteeckel/netbox-plugin-dns/tree/main): NetBox plugin for handling DNS records. The script for exporting zones can be found [in the examples](https://github.com/peteeckel/netbox-plugin-dns/tree/main/examples/custom-scripts).

## Installation

- **Add sctipt to your netbox**
    open Customization > Scripts and upload dns-ptr-sync.py file
- **Create PTR Zone Custom Field**  
    Before using the main script, make sure that the `ptr_zone` custom field exists for your servers. This field should     reference the zone where PTR records will be created.  
    - You can create this field using the **"Add Ptr Zone To Cust Fields"** script if it doesn’t already exist.
- **fill the PTR export zone field**
    After executing the **Add Ptr Zone To Cust Fields** script, you must go to your **NameServer**'s settings and fill in the **PTR export zone** field. This zone is where the records for IP addresses will be generated. Make sure to specify the correct DNS zone to ensure proper PTR record creation.

    Personally, **I recommend creating a separate zone**, especially if you want to run the script with Remove Other Records in Zone, e.g. ptr.example.com

## Usage

1. **Run the Main Script**  

    Hint: if you don't see fields filled with default values ​​(e.g. a record template or filler), then you used "run again", try to enter the menu through the script name

    - **Allow Tenant to be None in Nameserver**:  
    Enable this option if you want to allow servers without a tenant to be processed.
     
    - **Only for Servers**:  
    Use this field to specify which name servers should be processed. You can select multiple servers from the list.
   
    - **DNS Path Template**:  
    This template defines the structure for the DNS name. It uses Jinja2 templating syntax.

    The default template generates such subdomains:
    ```txt
    #for vm's
    172-16-0-1-id31.eth0.vm1.ncsu128-distswitch1.IDF128.Butler-Communications.North-Carolina.United-States.North-America
    
    #regular devices
    172-16-0-2-id32.GigabitEthernet0-0-0.dmi01-akron-rtr01. Comms-closet.DM-Akron.Ohio.United-States.North-America

    #if some rows are missing
    192-168-0-5-id5.no-data
    ```

    You can adjust this template to match your DNS naming conventions.

    - **Default Filler for Unknown Values**:  
    Specify the value to use when information is missing for a device.
   
    - **Remove Chain of Fillers**:  
    This option removes consecutive fillers (e.g., `no-data.no-data.no-data.a.b`) and replaces them with a single filler (`no-data.a.b`).

    - **Remove Other Records in Zone**:  
    Enabling this option will delete existing DNS records in the zone that are not part of the newly generated list.

    Hint: you can always change these parameters to yours if you edit the script

2. **Run the Script**
    - After configuring the parameters, click the **Run** button to execute the script.
    - The script will process the selected name servers and create DNS records for each IP address.

3. **Results**
    - The script will automatically generate DNS records for the devices in the specified zone.
    - If the **"Remove Other Records in Zone"** option is enabled, it will clean up any old or irrelevant records from the zone.
    - The script will log the actions it performs, such as adding new records and deleting old ones.
