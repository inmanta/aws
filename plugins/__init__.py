"""
    Copyright 2015 Impera

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

    Contact: bart@impera.io
"""

from impera.resources import Resource, resource, ResourceNotFoundExcpetion
from impera.agent.handler import provider, ResourceHandler
from impera.execute.util import Unknown

from boto import ec2, vpc

import logging

LOGGER = logging.getLogger(__name__)

# Silence boto
boto_log = logging.getLogger("boto")
boto_log.setLevel(logging.WARNING)

@provider("vm::Host", name = "ec2")
class VMHandler(ResourceHandler):
    """
        This class handles managing openstack resources
    """
    vm_types = ["m1.small", "m1.medium", "m1.large", "m1.xlarge", "m3.medium", "m3.large",
        "m3.xlarge", "m3.2xlarge", "c1.medium", "c1.xlarge", "c3.large", "c3.xlarge", "c3.2xlarge",
        "c3.4xlarge", "c3.8xlarge", "cc2.8xlarge", "m2.xlarge", "m2.2xlarge", "m2.4xlarge", "r3.large"
        "r3.xlarge", "r3.2xlarge", "r3.4xlarge", "r3.8xlarge", "cr1.8xlarge", "hi1.4xlarge",
        "hs1.8xlarge", "i2.xlarge", "i2.2xlarge", "i2.4xlarge", "i2.8xlarge", "t1.micro",
        "cg1.4xlarge", "g2.2xlarge"]

    def available(self, resource):
        """
            This handler is available to all virtual machines that have type set to aws in their iaas_config.
        """
        return "type" in resource.iaas_config and resource.iaas_config["type"] == "aws"

    def check_resource(self, resource):
        """
            This method will check what the status of the give resource is on
            openstack.
        """
        LOGGER.debug("Checking state of resource %s" % resource)

        conn = ec2.connect_to_region(resource.iaas_config["region"],
                    aws_access_key_id = resource.iaas_config["access_key"],
                    aws_secret_access_key = resource.iaas_config["secret_key"])

        vm_state = {}

        reservations = conn.get_all_instances()
        vm_list = {}
        for res in reservations:
            for vm in res.instances:
                if "Name" in vm.tags:
                    vm_list[vm.tags["Name"]] = vm

                else:
                    vm_list[str(vm)] = vm

        # how the vm doing
        if resource.name in vm_list:
            vm_state["vm"] = vm_list[resource.name]
        else:
            vm_state["vm"] = None

        # check if the key is there
        vm_state["key"] = False
        for k in conn.get_all_key_pairs():
            if resource.key_name == k.name:
                vm_state["key"] = True

        # TODO: also check the key itself

        return vm_state

    def list_changes(self, resource):
        """
            List the changes that are required to the vm
        """
        vm_state = self.check_resource(resource)
        LOGGER.debug("Determining changes required to resource %s" % resource.id)

        changes = {}

        if not vm_state["key"]:
            changes["key"] = (resource.key_name, resource.key_value)

        if vm_state["vm"] is None or vm_state["vm"].state == "terminated":
            changes["vm"] = resource

        return changes

    def do_changes(self, resource):
        """
            Enact the changes
        """
        changes = self.list_changes(resource)

        if len(changes) > 0:
            LOGGER.debug("Making changes to resource %s" % resource.id)

            conn = ec2.connect_to_region(resource.iaas_config["region"],
                    aws_access_key_id = resource.iaas_config["access_key"],
                    aws_secret_access_key = resource.iaas_config["secret_key"])

            if "key" in changes:
                conn.import_key_pair(changes["key"][0], changes["key"][1].encode())

            if "vm" in changes:
                if resource.flavor not in VMHandler.vm_types:
                    raise Exception("Flavor %s does not exist for vm %s" % (resource.flavor, resource))

                res = conn.run_instances(image_id = resource.image, instance_type = resource.flavor,
                        key_name = resource.key_name, user_data = resource.user_data.encode(),
                        placement = "eu-west-1b")

                vm = res.instances[0]

                conn.create_tags(vm.id, {"Name" : resource.name})

            return True

    def facts(self, resource):
        """
            Get facts about this resource
        """
        LOGGER.debug("Finding facts for %s" % resource.id.resource_str())

        conn = ec2.connect_to_region(resource.iaas_config["region"],
            aws_access_key_id = resource.iaas_config["access_key"],
            aws_secret_access_key = resource.iaas_config["secret_key"])

        vpc_conn = vpc.connect_to_region(resource.iaas_config["region"],
            aws_access_key_id = resource.iaas_config["access_key"],
            aws_secret_access_key = resource.iaas_config["secret_key"])

        reservations = conn.get_all_instances()
        vm_list = {}
        for res in reservations:
            for vm in res.instances:
                if vm.state == "running":
                    if "Name" in vm.tags:
                        vm_list[vm.tags["Name"]] = vm

                    else:
                        vm_list[str(vm)] = vm

        facts = {}
        for hostname,vm in vm_list.items():
            key = "vm::Host[%s,name=%s]" % (resource.id.agent_name, hostname)
            facts[key] = {}
            if len(vm.interfaces) > 0:
                iface = vm.interfaces[0]

                facts[key]["mac_address"] = iface.mac_address
                facts[key]["ip_address"] = iface.private_ip_address

                subnets = vpc_conn.get_all_subnets(iface.subnet_id)
                if len(subnets) > 0:
                    subnet = subnets[0]

                    facts[key]["cidr"] = subnet.cidr_block

                    from Imp.iplib import CIDR
                    o = CIDR(facts[key]["cidr"])

                    facts[key]["netmask"] = str(o.nm)

        return facts

