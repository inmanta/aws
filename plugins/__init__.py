"""
    Copyright 2017 Inmanta

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

    Contact: code@inmanta.com
"""

from inmanta.resources import resource, PurgeableResource, ManagedResource, Resource
from inmanta.agent.handler import provider, ResourceHandler, CRUDHandler, HandlerContext, ResourcePurged, SkipResource
from inmanta.plugins import plugin
from inmanta import const

import boto3

import logging
import re
import json
import botocore

LOGGER = logging.getLogger(__name__)

# Silence boto
boto_log = logging.getLogger("boto3")
boto_log.setLevel(logging.WARNING)
boto_log2 = logging.getLogger("botocore")
boto_log2.setLevel(logging.WARNING)


@plugin
def elbid(name: "string") -> "string":
    return re.sub("[\.]", "-", name)


def get_config(exporter, vm):
    """
        Create the auth url that openstack can use
    """
    if vm.iaas.iaas_config_string is None:
        raise Exception("A valid config string is required")
    return json.loads(vm.iaas.iaas_config_string)


def get_instances(exporter, elb):
    return sorted([vm.name for vm in elb.instances])


class AWSResource(PurgeableResource, ManagedResource):
    fields = ("provider",)

    @staticmethod
    def get_provider(_, resource):
        return {"region": resource.provider.region, "availability_zone": resource.provider.availability_zone,
                "access_key": resource.provider.access_key, "secret_key": resource.provider.secret_key}


@resource("aws::ELB", agent="provider.name", id_attribute="name")
class ELB(AWSResource):
    """
        Amazon Elastic loadbalancer
    """
    fields = ("name", "security_group", "listen_port", "dest_port", "protocol", "instances")

    @staticmethod
    def get_instances(exporter, elb):
        return sorted([vm.name for vm in elb.instances])


@resource("aws::VirtualMachine", agent="provider.name", id_attribute="name")
class VirtualMachine(AWSResource):
    fields = ("name", "user_data", "flavor", "image", "key_name", "key_value", "subnet_id", "source_dest_check")

    @staticmethod
    def get_key_name(_, resource):
        return resource.public_key.name

    @staticmethod
    def get_key_value(_, resource):
        return resource.public_key.public_key


class AWSHandler(CRUDHandler):
    def __init__(self, agent, io=None) -> None:
        CRUDHandler.__init__(self, agent, io=io)

        self._session = None
        self._ec2 = None
        self._elb = None

    def pre(self, ctx: HandlerContext, resource: AWSResource) -> None:
        CRUDHandler.pre(self, ctx, resource)

        self._session = boto3.Session(region_name=resource.provider["region"],
                                      aws_access_key_id=resource.provider["access_key"],
                                      aws_secret_access_key=resource.provider["secret_key"])
        self._ec2 = self._session.resource("ec2")
        self._elb = self._session.client("elb")

    def post(self, ctx: HandlerContext, resource: AWSResource) -> None:
        CRUDHandler.post(self, ctx, resource)

        self._ec2 = None
        self._elb = None


@provider("aws::ELB", name="ec2")
class ELBHandler(AWSHandler):
    """
        This class manages ELB instances on amazon ec2
    """
    def _get_name(self, vm):
        tags = vm.tags if vm.tags is not None else []
        for tag in tags:
            if tag["Key"] == "Name":
                return tag["Value"]

        return vm.instance_id

    def _get_security_group(self, security_groups, name):
        for sg in security_groups.values():
            if sg.group_name == name:
                return sg.id

        return None

    def read_resource(self, ctx, resource: ELB):
        vms = {self._get_name(x): x for x in self._ec2.instances.all()}
        vm_ids = {x.id: x for x in vms.values()}
        security_groups = {sg.id: sg for sg in self._ec2.security_groups.all()}

        ctx.set("vms", vms)
        ctx.set("security_groups", security_groups)

        try:
            loadbalancer = self._elb.describe_load_balancers(LoadBalancerNames=[resource.name])["LoadBalancerDescriptions"][0]
        except botocore.exceptions.ClientError:
            raise ResourcePurged()

        resource.purged = False
        resource.instances = sorted(self._get_name(vm_ids[x["InstanceId"]]) for x in loadbalancer["Instances"])

        if len(loadbalancer["ListenerDescriptions"]) > 0:
            if len(loadbalancer["ListenerDescriptions"]) > 1:
                ctx.warning("This handler does not support multiple listeners! Using the first one.")
            lb = loadbalancer["ListenerDescriptions"][0]["Listener"]
            resource.listen_port = lb["LoadBalancerPort"]
            resource.dst_port = lb["InstancePort"]
            resource.protocol = lb["Protocol"]

        if len(loadbalancer["SecurityGroups"]) > 0:
            if len(loadbalancer["SecurityGroups"]) > 1:
                ctx.warning("This handler does not support multiple security groups. Only using the first one")

            sg = loadbalancer["SecurityGroups"][0]
            if sg in security_groups:
                resource.security_group = security_groups[sg].group_name
            else:
                raise Exception("Invalid amazon response, a security group is used by the loadbalancer but not defined?!?")

    def create_resource(self, ctx: HandlerContext, resource: ELB) -> None:
        sg_id = self._get_security_group(ctx.get("security_groups"), resource.security_group)
        ctx.debug("Creating loadbalancer with security group %(sg)s", sg=sg_id)
        if sg_id is None:
            raise Exception("Security group %s is not defined at AWS" % resource.security_group)

        self._elb.create_load_balancer(LoadBalancerName=resource.name,
                                       Listeners=[{'Protocol': resource.protocol, 'LoadBalancerPort': resource.listen_port,
                                                   'InstanceProtocol': resource.protocol, 'InstancePort': resource.dest_port}],
                                       AvailabilityZones=[resource.provider["region"] + resource.provider["availability_zone"]],
                                       SecurityGroups=[sg_id])

        # register instances
        vms = ctx.get("vms")
        instance_list = []
        for inst in resource.instances:
            if inst not in vms:
                ctx.warning("Instance %(instance)s not added to aws::ELB %(elb)s, because it does not exist.",
                            instances=inst.id, elb=resource.name)
            else:
                instance_list.append({"InstanceId": vms[inst].id})

        if len(instance_list) > 0:
            self._elb.register_instances_with_load_balancer(LoadBalancerName=resource.name, Instances=instance_list)

        ctx.set_created()

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        self._elb.delete_load_balancer(LoadBalancerName=resource.name)
        ctx.set_purged()

    def update_resource(self, ctx: HandlerContext, changes: dict, resource: VirtualMachine) -> None:
        vms = ctx.get("vms")

        if "instances" in changes:
            new_instances = set(changes["instances"]["desired"])
            old_instances = set(changes["instances"]["current"])
            add = [vms[vm].id for vm in new_instances - old_instances if vm in vms]
            remove = [vms[vm].id for vm in old_instances - new_instances if vm in vms]

            if len(add) > 0:
                self._elb.register_instances_with_load_balancer(LoadBalancerName=resource.name,
                                                                Instances=[{"InstanceId": x} for x in add])

            if len(remove) > 0:
                self._elb.deregister_instances_from_load_balancer(LoadBalancerName=resource.name,
                                                                Instances=[{"InstanceId": x} for x in remove])

        if "security_group" in changes:
            # set the security group
            sg_id = self._get_security_group(ctx.get("security_groups"), resource.security_group)
            ctx.debug("Change loadbalancer with security group %(sg)s", sg=sg_id)
            if sg_id is None:
                raise Exception("Security group %s is not defined at AWS" % resource.security_group)

            self._elb.apply_security_groups_to_load_balancer(LoadBalancerName=resource.name, SecurityGroups=[sg_id])

        if "listener" in changes:
            self._elb.create_load_balancer_listeners(LoadBalancerName='string',
                                                     Listeners=[{'Protocol': resource.protocol,
                                                                 'LoadBalancerPort': resource.listen_port,
                                                                 'InstanceProtocol': resource.protocol,
                                                                 'InstancePort': resource.dest_port}])

            self._elb.delete_load_balancer_listeners(LoadBalancerName='string', LoadBalancerPorts=[resource.listen_port])

    def facts(self, ctx, resource):
        try:
            loadbalancer = self._elb.describe_load_balancers(LoadBalancerNames=[resource.name])["LoadBalancerDescriptions"][0]
            return {"dns_name": loadbalancer["DNSName"]}
        except botocore.exceptions.ClientError:
            return {}


@provider("aws::VirtualMachine", name="ec2")
class VirtualMachineHandler(AWSHandler):
    def read_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        key_pairs = list(self._ec2.key_pairs.filter(Filters=[{"Name": "key-name", "Values": [resource.key_name]}]))
        if len(key_pairs) == 0:
            ctx.set("key", None)
        elif len(key_pairs) > 1:
            ctx.info("Multiple keys with name %(name)s already deployed", name=resource.key_name)
            raise SkipResource()
        else:
            ctx.set("key", True)

        instance = [x for x in self._ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [resource.name]}])
                    if x.state["Name"] != "terminated"]
        if len(instance) == 0:
            raise ResourcePurged()

        elif len(instance) > 1:
            ctx.info("Found more than one instance with tag Name %(name)s", name=resource.name, instances=instance)
            raise SkipResource()

        instance = instance[0]
        ctx.set("instance", instance)
        resource.purged = False
        resource.flavor = instance.instance_type
        resource.image = instance.image_id
        resource.key_name = instance.key_name

        if instance.state["Name"] == "terminated":
            resource.purged = True
            return

        # these do not work on terminated instances
        result = instance.describe_attribute(Attribute="sourceDestCheck")
        resource.source_dest_check = result["SourceDestCheck"]["Value"]


    def _ensure_key(self, ctx: HandlerContext, key_name, key_value):
        self._ec2.import_key_pair(KeyName=key_name, PublicKeyMaterial=key_value.encode())

    def create_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        if not ctx.get("key"):
            self._ensure_key(ctx, resource.key_name, resource.key_value)

        instances = self._ec2.create_instances(ImageId=resource.image, KeyName=resource.key_name, UserData=resource.user_data,
                                              InstanceType=resource.flavor, SubnetId=resource.subnet_id,
                                              Placement={'AvailabilityZone': resource.provider["region"] +
                                                         resource.provider["availability_zone"]},
                                              MinCount=1, MaxCount=1)
        if len(instances) != 1:
            ctx.set_status(const.ResourceState.failed)
            ctx.error("Requested one instance but do not receive it.", instances=instances)
            return

        instance = instances[0]
        instance.create_tags(Tags=[{"Key": "Name", "Value": resource.name}])

        if not resource.source_dest_check:
            instance.modify_attribute(Attribute="sourceDestCheck", Value="False")

    def update_resource(self, ctx: HandlerContext, changes: dict, resource: VirtualMachine) -> None:
        raise SkipResource("Modifying a running instance is not supported.")

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        instance = ctx.get("instance")
        instance.terminate()

    def facts(self, ctx, resource):
        facts = {}

        instance = list(self._ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [resource.name]}]))
        if len(instance) == 0:
            return {}

        elif len(instance) > 1:
            ctx.info("Found more than one instance with tag Name %(name)s", name=resource.name, instances=instance)
            raise SkipResource()

        instance = instance[0]

        # find eth0
        iface = None
        for i in instance.network_interfaces_attribute:
            if i["Attachment"]["DeviceIndex"] == 0:
                iface = i

        if iface is None:
            return facts

        facts["mac_address"] = iface["MacAddress"]
        facts["ip_address"] = iface["PrivateIpAddress"]
        facts["public_ip"] = instance.public_ip_address

        return facts
