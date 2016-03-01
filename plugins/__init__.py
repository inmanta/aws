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
from impera.plugins.base import plugin
from impera.export import resource_to_id

from boto import ec2, vpc
from boto.ec2 import elb

import logging
import re
import json

LOGGER = logging.getLogger(__name__)

# Silence boto
boto_log = logging.getLogger("boto")
boto_log.setLevel(logging.WARNING)


@plugin
def elbid(name: "string") -> "string":
    return re.sub("[\.]", "-", name)

@resource_to_id("aws::ELB")
def vm_to_id(resource):
    """
        Convert a resource to an id
    """
    return "aws::ELB[%s,name=%s]" % (resource.iaas.name, resource.name)


def get_config(exporter, vm):
    """
        Create the auth url that openstack can use
    """
    if vm.iaas.iaas_config_string is None:
        raise Exception("A valid config string is required")
    return json.loads(vm.iaas.iaas_config_string)


def get_instances(exporter, elb):
    return sorted([vm.name for vm in elb.instances])


@resource("aws::ELB", agent = "iaas.name", id_attribute = "name")
class ELB(Resource):
    """
        Amazon Elastic loadbalancer
    """
    fields = ("name", "security_group", "listen_port", "dest_port", "protocol", "iaas_config",
              "instances")
    map = {"iaas_config": get_config, "instances" : get_instances, "listen_port": lambda _, x: int(x.listen_port),
           "dest_port": lambda _, x: int(x.dest_port)}


@provider("aws::ELB", name = "ec2")
class ELBHandler(ResourceHandler):
    """This class manages ELB instances on amazon ec2
    """
    def available(self, resource):
        """
            This handler is available to all elb's that have type set to aws in their iaas_config.
        """
        return "type" in resource.iaas_config and resource.iaas_config["type"] == "aws"

    def check_resource(self, resource):
        """
            This method will check what the status of the give resource is on
            openstack.
        """
        LOGGER.debug("Checking state of resource %s" % resource)

        ec2_conn = ec2.connect_to_region(resource.iaas_config["region"],
                                         aws_access_key_id = resource.iaas_config["access_key"],
                                         aws_secret_access_key = resource.iaas_config["secret_key"])

        elb_conn = elb.connect_to_region(resource.iaas_config["region"],
                                         aws_access_key_id = resource.iaas_config["access_key"],
                                         aws_secret_access_key = resource.iaas_config["secret_key"])

        loadbalancers = elb_conn.get_all_load_balancers()
        vm_names = {vm.id: vm.tags["Name"] for res in ec2_conn.get_all_instances() for vm in res.instances if "Name" in vm.tags}

        elb_state = {"purged" : True}

        for lb in loadbalancers:
            if lb.name == resource.name:
                elb_state["purged"] = False
                elb_state["instances"] = sorted([vm_names[x.id] for x in lb.instances if x.id in vm_names])
                if len(lb.listeners) > 0:
                    if len(lb.listeners) > 1:
                        LOGGER.warning("This handler does not support multiple listeners! Using the first one.")
                    lst = lb.listeners[0]
                    elb_state["listen_port"] = lst[0]
                    elb_state["dst_port"] = lst[1]
                    elb_state["protocol"] = lst[2].lower()

                security_groups = {sg.id: sg.name for sg in ec2_conn.get_all_security_groups()}

                if len(lb.security_groups) > 0:
                    if len(lb.security_groups) > 1:
                        LOGGER.warning("This handler does not support multiple security groups.")

                    sg = lb.security_groups[0]
                    if sg in security_groups:
                        elb_state["security_group"] = security_groups[sg]

                    else:
                        raise Exception("Invalid amazon response, security group is used but not defined?!?")

        return elb_state

    def list_changes(self, resource):
        """
            List the changes that are required to the vm
        """
        elb_state = self.check_resource(resource)
        LOGGER.debug("Determining changes required to resource %s" % resource.id)

        changes = {}
        for key, value in elb_state.items():
            if hasattr(resource, key):
                desired_value = getattr(resource, key)
                if desired_value != value:
                    changes[key] = (value, desired_value)

            elif key == "purged":
                if elb_state["purged"]:
                    changes["purged"] = (True, False)

        return changes

    def do_changes(self, resource):
        """
            Enact the changes
        """
        changes = self.list_changes(resource)

        if len(changes) > 0:
            LOGGER.debug("Making changes to resource %s" % resource.id)
            ec2_conn = ec2.connect_to_region(resource.iaas_config["region"],
                                             aws_access_key_id = resource.iaas_config["access_key"],
                                             aws_secret_access_key = resource.iaas_config["secret_key"])

            elb_conn = elb.connect_to_region(resource.iaas_config["region"],
                                             aws_access_key_id = resource.iaas_config["access_key"],
                                             aws_secret_access_key = resource.iaas_config["secret_key"])

            security_groups = {sg.name: sg.id for sg in ec2_conn.get_all_security_groups()}
            vm_names = {vm.tags["Name"]: vm.id for res in ec2_conn.get_all_instances()
                                               for vm in res.instances if "Name" in vm.tags}

            if "purged" in changes:
                if not changes["purged"][1]: # this is a new resource, lets create it
                    listener = (resource.listen_port, resource.dest_port, resource.protocol)
                    lb = elb_conn.create_load_balancer(resource.name, [resource.iaas_config["availability_zone"]], [listener])

                    # set the security group
                    if resource.security_group not in security_groups:
                        raise Exception("Security group %s is not defined on IaaS" % resource.security_group)
                    elb_conn.apply_security_groups_to_lb(resource.name, security_groups[resource.security_group])

                    # set the instances
                    instance_list = []
                    for inst in resource.instances:
                        if inst not in vm_names:
                            LOGGER.warning("Instance %s not added to aws::ELB with name %s, because it does not exist.",
                                           inst, resource.name)

                        else:
                            instance_list.append(vm_names[inst])

                    if len(instance_list) > 0:
                        elb_conn.register_instances(resource.name, instance_list)

                else: # delete the loadbalancer
                    elb_conn.delete_load_balancer(resource.name)

            else: # we need to make changes
                if "listener" in changes:
                    listener = (resource.listen_port, resource.dest_port, resource.protocol)
                    elb_conn.create_load_balancer_listeners(resource.name, listener)

                if "security_group" in changes:
                    # set the security group
                    if resource.security_group not in security_groups:
                        raise Exception("Security group %s is not defined on IaaS" % resource.security_group)

                    elb_conn.apply_security_groups_to_lb(resource.name, security_groups[resource.security_group])

                if "instances" in changes:
                    new_instances = set(changes["instances"][1])
                    old_instances = set(changes["instances"][0])
                    add = [vm_names[vm] for vm in new_instances-old_instances if vm in vm_names]
                    remove = [vm_names[vm] for vm in old_instances-new_instances if vm in vm_names]

                    if len(add) > 0:
                        elb_conn.register_instances(resource.name, add)

                    if len(remove) > 0:
                        elb_conn.deregister_instances(resource.name, remove)

            return True

    def facts(self, resource):
        """
            Get facts about this resource
        """
        LOGGER.debug("Finding facts for %s" % resource.id.resource_str())

        elb_conn = elb.connect_to_region(resource.iaas_config["region"],
                                         aws_access_key_id = resource.iaas_config["access_key"],
                                         aws_secret_access_key = resource.iaas_config["secret_key"])

        all_lb = elb_conn.get_all_load_balancers()

        the_lb = None
        for lb in all_lb:
            if lb.name == resource.name:
                the_lb = lb
                break

        if the_lb is not None:
            return {"dns_name": the_lb.dns_name}

        return {}


@provider("vm::Host", name = "ec2")
class VMHandler(ResourceHandler):
    """
        This class manages vm::Host on amazon ec2
    """
    vm_types = ["m1.small", "m1.medium", "m1.large", "m1.xlarge", "m3.medium", "m3.large",
        "m3.xlarge", "m3.2xlarge", "c1.medium", "c1.xlarge", "c3.large", "c3.xlarge", "c3.2xlarge",
        "c3.4xlarge", "c3.8xlarge", "cc2.8xlarge", "m2.xlarge", "m2.2xlarge", "m2.4xlarge", "r3.large"
        "r3.xlarge", "r3.2xlarge", "r3.4xlarge", "r3.8xlarge", "cr1.8xlarge", "hi1.4xlarge",
        "hs1.8xlarge", "i2.xlarge", "i2.2xlarge", "i2.4xlarge", "i2.8xlarge", "t1.micro",
        "cg1.4xlarge", "g2.2xlarge", "t2.micro", "t2.small", "t2.medium"]

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
                name = str(vm)

                if "Name" in vm.tags:
                    name = vm.tags["Name"]

                if name in vm_list:
                    if vm.state != "terminated":
                        vm_list[name] = vm
                else:
                    vm_list[name] = vm


        # how the vm doing
        if resource.name in vm_list:
            vm_state["vm"] = vm_list[resource.name].state
        else:
            vm_state["vm"] = "terminated"

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

        purged = "running"
        if resource.purged:
            purged = "terminated"

        if vm_state["vm"] != purged:
            changes["state"] = (vm_state["vm"], purged)

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
            if "state" in changes:
                if changes["state"][0] == "terminated" and changes["state"][1] == "running":
                    if resource.flavor not in VMHandler.vm_types:
                        raise Exception("Flavor %s does not exist for vm %s" % (resource.flavor, resource))

                    res = conn.run_instances(image_id=resource.image, instance_type=resource.flavor,
                                             key_name=resource.key_name,
                                             user_data=resource.user_data.encode(),
                                             placement=resource.iaas_config["availability_zone"],
                                             subnet_id=resource.network)

                    vm = res.instances[0]
                    conn.modify_instance_attribute(vm.id, attribute='sourceDestCheck', value=False)
                    conn.create_tags(vm.id, {"Name" : resource.name})

                elif changes["state"][1] == "terminated" and changes["state"][0] == "running":
                    reservations = conn.get_all_instances()
                    vm_list = {}
                    for res in reservations:
                        for vm in res.instances:
                            if vm.state == "running":
                                if "Name" in vm.tags:
                                    vm_list[vm.tags["Name"]] = vm

                                else:
                                    vm_list[str(vm)] = vm

                    if resource.name in vm_list:
                        vm_list[resource.name].terminate()

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
                facts[key]["public_ip"] = vm.ip_address

                subnets = vpc_conn.get_all_subnets(iface.subnet_id)
                if len(subnets) > 0:
                    subnet = subnets[0]

                    facts[key]["cidr"] = subnet.cidr_block

                    from iplib import CIDR
                    o = CIDR(facts[key]["cidr"])

                    facts[key]["netmask"] = str(o.nm)

        if resource.id.resource_str() in facts:
            return facts[resource.id.resource_str()]
        return {}
