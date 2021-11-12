"""
    Copyright 2018 Inmanta

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

import binascii
import json
import logging
import os
import re
import time

import boto3
import botocore
from inmanta import const
from inmanta.agent.handler import (
    CRUDHandler,
    HandlerContext,
    ResourcePurged,
    SkipResource,
    provider,
)
from inmanta.ast import OptionalValueException
from inmanta.execute.util import Unknown
from inmanta.plugins import plugin
from inmanta.resources import ManagedResource, PurgeableResource, resource

LOGGER = logging.getLogger(__name__)

# Silence boto
boto_log = logging.getLogger("boto3")
boto_log.setLevel(logging.WARNING)
boto_log2 = logging.getLogger("botocore")
boto_log2.setLevel(logging.WARNING)


@plugin
def elbid(name: "string") -> "string":
    return re.sub(r"[\.]", "-", name)


def pkcs1_unpad(text):
    # From http://kfalck.net/2011/03/07/decoding-pkcs1-padding-in-python
    if len(text) > 0 and text[0] == 2:
        # Find end of padding marked by nul
        pos = text.find(b"\x00")
        if pos > 0:
            return text[pos + 1 :].decode()
    return None


def long_to_bytes(val, endianness="big"):
    # From http://stackoverflow.com/questions/8730927/convert-python-long-int-to-fixed-size-byte-array

    # one (1) hex digit per four (4) bits
    width = val.bit_length()

    # unhexlify wants an even multiple of eight (8) bits, but we don't
    # want more digits than we need (hence the ternary-ish 'or')
    width += 8 - ((width % 8) or 8)

    # format width specifier: four (4) bits per hex digit
    fmt = "%%0%dx" % (width // 4)

    # prepend zero (0) to the width, to zero-pad the output
    s = binascii.unhexlify(fmt % val)

    if endianness == "little":
        # see http://stackoverflow.com/a/931095/309233
        s = s[::-1]

    return s


@plugin
def get_api_id(provider: "aws::Provider", api_name: "string") -> "string":
    access_key = provider.access_key
    if access_key is None:
        access_key = os.environ.get("AWS_ACCESS_KEY")
    if access_key is None:
        raise Exception("AWS_ACCESS_KEY has to be provided as an environment variable.")

    secret_key = provider.secret_key
    if secret_key is None:
        secret_key = os.environ.get("AWS_SECRET_KEY")
    if secret_key is None:
        raise Exception("AWS_SECRET_KEY has to be provided as an environment variable.")

    session = boto3.Session(
        region_name=provider.region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client = session.client("apigateway")

    apis = client.get_rest_apis()

    for api in apis["items"]:
        if api["name"] == api_name:
            return api["id"]

    return Unknown(source=provider)


# # Handlers
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
        return {
            "region": resource.provider.region,
            "availability_zone": resource.provider.availability_zone,
            "access_key": resource.provider.access_key,
            "secret_key": resource.provider.secret_key,
        }


@resource("aws::ELB", agent="provider.name", id_attribute="name")
class ELB(AWSResource):
    """
    Amazon Elastic loadbalancer
    """

    fields = (
        "name",
        "security_group",
        "listen_port",
        "dest_port",
        "protocol",
        "instances",
    )

    @staticmethod
    def get_instances(exporter, elb):
        return sorted([vm.name for vm in elb.instances])


@resource("aws::VirtualMachine", agent="provider.name", id_attribute="name")
class VirtualMachine(AWSResource):
    fields = (
        "name",
        "user_data",
        "flavor",
        "image",
        "key_name",
        "key_value",
        "subnet_id",
        "source_dest_check",
        "tags",
        "subnet",
        "security_groups",
        "volumes",
        "volume_attachment",
        "ebs_optimized",
        "ignore_extra_volumes",
        "ignore_wrong_image",
        "root_volume_size",
        "root_volume_type",
    )

    @staticmethod
    def get_key_name(_, resource):
        return resource.public_key.name

    @staticmethod
    def get_key_value(_, resource):
        return resource.public_key.public_key

    @staticmethod
    def get_subnet_id(_, resource):
        """
        Validation of subnet and subnet_id combination is done in get_subnet
        """
        try:
            subnet_id = resource.subnet_id
        except OptionalValueException:
            subnet_id = None
        return subnet_id

    @staticmethod
    def get_subnet(_, resource):
        try:
            subnet_name = resource.subnet.name
        except OptionalValueException:
            subnet_name = None

        subnet_id = VirtualMachine.get_subnet_id(None, resource)

        if (subnet_id is None and subnet_name is None) or (
            subnet_id is not None and subnet_name is not None
        ):
            raise ValueError(
                "A virtual machine requires either a subnet instance or a subnet_id"
            )

        return subnet_name

    @staticmethod
    def get_security_groups(_, resource):
        return [x.name for x in resource.security_groups]

    @staticmethod
    def get_volumes(_, resource):
        return [x.name for x in resource.volumes]

    @staticmethod
    def get_volume_attachment(_, resource):
        return {x.name: x.attachmentpoint for x in resource.volumes}


@resource("aws::Volume", agent="provider.name", id_attribute="name")
class Volume(AWSResource):
    fields = ("name", "availability_zone", "encrypted", "size", "volume_type", "tags")


@resource(
    "aws::analytics::ElasticSearch", agent="provider.name", id_attribute="domain_name"
)
class ElasticSearch(AWSResource):
    fields = (
        "domain_name",
        "elasticsearch_version",
        "instance_type",
        "instance_count",
        "dedicated_master_enabled",
        "zone_awareness_enabled",
        "dedicated_master_type",
        "dedicated_master_count",
        "ebs_enabled",
        "volume_type",
        "volume_size",
        "access_policies",
        "automated_snapshot_start_hour",
    )

    @staticmethod
    def get_access_policies(_, resource):
        try:
            return json.dumps(json.loads(resource.access_policies), sort_keys=True)
        except Exception:
            print(resource.access_policies)
            raise


@resource("aws::VPC", agent="provider.name", id_attribute="name")
class VPC(AWSResource):
    fields = ("name", "cidr_block", "instance_tenancy")


@resource("aws::Subnet", agent="provider.name", id_attribute="name")
class Subnet(AWSResource):
    fields = (
        "name",
        "cidr_block",
        "availability_zone",
        "vpc",
        "map_public_ip_on_launch",
    )

    @staticmethod
    def get_vpc(_, resource):
        return resource.vpc.name


@resource("aws::InternetGateway", agent="provider.name", id_attribute="name")
class InternetGateway(AWSResource):
    fields = ("name", "vpc")

    @staticmethod
    def get_vpc(_, resource):
        return resource.vpc.name


@resource("aws::Route", agent="provider.name", id_attribute="destination")
class Route(AWSResource):
    fields = ("destination", "nexthop", "vpc")

    @staticmethod
    def get_vpc(_, resource):
        return resource.vpc.name


@resource("aws::SecurityGroup", agent="provider.name", id_attribute="name")
class SecurityGroup(AWSResource):
    """
    A security group in an OpenStack tenant
    """

    fields = ("name", "description", "manage_all", "rules", "retries", "wait", "vpc")

    @staticmethod
    def get_rules(exporter, group):
        rules = []
        for rule in group.rules:
            json_rule = {"protocol": rule.ip_protocol, "direction": rule.direction}

            if rule.port > 0:
                json_rule["port_range_min"] = rule.port
                json_rule["port_range_max"] = rule.port

            else:
                json_rule["port_range_min"] = rule.port_min
                json_rule["port_range_max"] = rule.port_max

            if json_rule["port_range_min"] == 0:
                json_rule["port_range_min"] = -1

            if json_rule["port_range_max"] == 0:
                json_rule["port_range_max"] = -1

            try:
                json_rule["remote_ip_prefix"] = rule.remote_prefix
            except Exception:
                pass

            try:
                json_rule["remote_group"] = rule.remote_group.name
            except Exception:
                pass

            rules.append(json_rule)

        return rules

    @staticmethod
    def get_vpc(_, resource):
        return resource.vpc.name


@resource("aws::database::RDS", agent="provider.name", id_attribute="name")
class RDS(AWSResource):
    fields = (
        "name",
        "allocated_storage",
        "flavor",
        "engine",
        "engine_version",
        "master_user_name",
        "master_user_password",
        "port",
        "public",
        "subnet_group",
        "tags",
    )


class AWSHandler(CRUDHandler):
    def __init__(self, agent, io=None) -> None:
        CRUDHandler.__init__(self, agent, io=io)

        self._session = None
        self._ec2 = None
        self._elb = None

    def pre(self, ctx: HandlerContext, resource: AWSResource) -> None:
        CRUDHandler.pre(self, ctx, resource)

        access_key = resource.provider["access_key"]
        if access_key is None:
            access_key = os.environ.get("AWS_ACCESS_KEY")
        if access_key is None:
            raise Exception(
                "AWS_ACCESS_KEY has to be provided as an environment variable."
            )

        secret_key = resource.provider["secret_key"]
        if secret_key is None:
            secret_key = os.environ.get("AWS_SECRET_KEY")
        if secret_key is None:
            raise Exception(
                "AWS_SECRET_KEY has to be provided as an environment variable."
            )

        self._session = boto3.Session(
            region_name=resource.provider["region"],
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._ec2 = self._session.resource("ec2")
        self._elb = self._session.client("elb")

    def post(self, ctx: HandlerContext, resource: AWSResource) -> None:
        CRUDHandler.post(self, ctx, resource)

        self._ec2 = None
        self._elb = None

    def tags_amazon_to_internal(self, tags):
        return {i["Key"]: i["Value"] for i in tags}

    def tags_internal_to_amazon(self, tags):
        return [{"Key": k, "Value": v} for k, v in tags.items()]

    def get_name_from_tag(self, tags):
        if tags is None:
            return None
        alltags = self.tags_amazon_to_internal(tags)
        if "Name" in alltags:
            return alltags["Name"]
        return None


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
        vms = {
            self._get_name(x): x
            for x in self._ec2.instances.all()
            if x.state["Name"] != "terminated"
        }
        vm_ids = {x.id: x for x in vms.values()}
        security_groups = {sg.id: sg for sg in self._ec2.security_groups.all()}

        ctx.set("vms", vms)
        ctx.set("security_groups", security_groups)

        try:
            loadbalancer = self._elb.describe_load_balancers(
                LoadBalancerNames=[resource.name]
            )["LoadBalancerDescriptions"][0]
        except botocore.exceptions.ClientError:
            raise ResourcePurged()

        resource.purged = False
        resource.instances = sorted(
            self._get_name(vm_ids[x["InstanceId"]]) for x in loadbalancer["Instances"]
        )

        if len(loadbalancer["ListenerDescriptions"]) > 0:
            if len(loadbalancer["ListenerDescriptions"]) > 1:
                ctx.warning(
                    "This handler does not support multiple listeners! Using the first one."
                )
            lb = loadbalancer["ListenerDescriptions"][0]["Listener"]
            resource.listen_port = lb["LoadBalancerPort"]
            resource.dst_port = lb["InstancePort"]
            resource.protocol = lb["Protocol"]

        if len(loadbalancer["SecurityGroups"]) > 0:
            if len(loadbalancer["SecurityGroups"]) > 1:
                ctx.warning(
                    "This handler does not support multiple security groups. Only using the first one"
                )

            sg = loadbalancer["SecurityGroups"][0]
            if sg in security_groups:
                resource.security_group = security_groups[sg].group_name
            else:
                raise Exception(
                    "Invalid amazon response, a security group is used by the loadbalancer but not defined?!?"
                )

    def create_resource(self, ctx: HandlerContext, resource: ELB) -> None:
        sg_id = self._get_security_group(
            ctx.get("security_groups"), resource.security_group
        )
        ctx.debug("Creating loadbalancer with security group %(sg)s", sg=sg_id)
        if sg_id is None:
            raise Exception(
                "Security group %s is not defined at AWS" % resource.security_group
            )

        self._elb.create_load_balancer(
            LoadBalancerName=resource.name,
            Listeners=[
                {
                    "Protocol": resource.protocol,
                    "LoadBalancerPort": resource.listen_port,
                    "InstanceProtocol": resource.protocol,
                    "InstancePort": resource.dest_port,
                }
            ],
            AvailabilityZones=[
                resource.provider["region"] + resource.provider["availability_zone"]
            ],
            SecurityGroups=[sg_id],
        )

        # register instances
        vms = ctx.get("vms")
        instance_list = []
        for inst in resource.instances:
            if inst not in vms:
                ctx.warning(
                    "Instance %(instance)s not added to aws::ELB %(elb)s, because it does not exist.",
                    instance=inst,
                    elb=resource.name,
                )
            else:
                instance_list.append({"InstanceId": vms[inst].id})

        if len(instance_list) > 0:
            self._elb.register_instances_with_load_balancer(
                LoadBalancerName=resource.name, Instances=instance_list
            )

        ctx.set_created()

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        self._elb.delete_load_balancer(LoadBalancerName=resource.name)
        ctx.set_purged()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: VirtualMachine
    ) -> None:
        vms = ctx.get("vms")

        if "instances" in changes:
            new_instances = set(changes["instances"]["desired"])
            old_instances = set(changes["instances"]["current"])
            add = [vms[vm].id for vm in new_instances - old_instances if vm in vms]
            remove = [vms[vm].id for vm in old_instances - new_instances if vm in vms]

            if len(add) > 0:
                self._elb.register_instances_with_load_balancer(
                    LoadBalancerName=resource.name,
                    Instances=[{"InstanceId": x} for x in add],
                )

            if len(remove) > 0:
                self._elb.deregister_instances_from_load_balancer(
                    LoadBalancerName=resource.name,
                    Instances=[{"InstanceId": x} for x in remove],
                )

        if "security_group" in changes:
            # set the security group
            sg_id = self._get_security_group(
                ctx.get("security_groups"), resource.security_group
            )
            ctx.debug("Change loadbalancer with security group %(sg)s", sg=sg_id)
            if sg_id is None:
                raise Exception(
                    "Security group %s is not defined at AWS" % resource.security_group
                )

            self._elb.apply_security_groups_to_load_balancer(
                LoadBalancerName=resource.name, SecurityGroups=[sg_id]
            )

        if "listener" in changes:
            self._elb.create_load_balancer_listeners(
                LoadBalancerName="string",
                Listeners=[
                    {
                        "Protocol": resource.protocol,
                        "LoadBalancerPort": resource.listen_port,
                        "InstanceProtocol": resource.protocol,
                        "InstancePort": resource.dest_port,
                    }
                ],
            )

            self._elb.delete_load_balancer_listeners(
                LoadBalancerName="string", LoadBalancerPorts=[resource.listen_port]
            )

    def facts(self, ctx, resource):
        try:
            loadbalancer = self._elb.describe_load_balancers(
                LoadBalancerNames=[resource.name]
            )["LoadBalancerDescriptions"][0]
            return {"dns_name": loadbalancer["DNSName"]}
        except botocore.exceptions.ClientError:
            return {}


@provider("aws::VirtualMachine", name="ec2")
class VirtualMachineHandler(AWSHandler):
    def _get_subnet(self, subnet_id):
        subnets = list(self._ec2.subnets.filter(SubnetIds=[subnet_id]))
        if len(subnets) == 0:
            return None
        return subnets[0]

    def _get_subnet_by_name(self, ctx, name):
        subnets = list(
            self._ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        )
        if len(subnets) == 0:
            ctx.info("No subnet found with tag Name %(name)s", name=name)
            raise SkipResource()

        elif len(subnets) > 1:
            ctx.info(
                "Found more than one subnet with tag Name %(name)s",
                name=name,
                subnets=subnets,
            )
            raise SkipResource()

        subnet = subnets[0]
        return subnet

    def read_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        key_pairs = list(
            self._ec2.key_pairs.filter(
                Filters=[{"Name": "key-name", "Values": [resource.key_name]}]
            )
        )
        if len(key_pairs) == 0:
            ctx.set("key", None)
        elif len(key_pairs) > 1:
            ctx.info(
                "Multiple keys with name %(name)s already deployed",
                name=resource.key_name,
            )
            raise SkipResource()
        else:
            ctx.set("key", True)

        instance = [
            x
            for x in self._ec2.instances.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource.name]}]
            )
            if x.state["Name"] != "terminated"
        ]
        if len(instance) == 0:
            raise ResourcePurged()

        elif len(instance) > 1:
            ctx.info(
                "Found more than one instance with tag Name %(name)s",
                name=resource.name,
                instances=instance,
            )
            raise SkipResource()

        instance = instance[0]
        ctx.set("instance", instance)
        resource.purged = False
        resource.flavor = instance.instance_type
        resource.image = instance.image_id
        resource.key_name = instance.key_name
        resource.ebs_optimized = instance.ebs_optimized

        root = instance.root_device_name

        resource.root_device_name = root

        def get_root_volume():
            """
            When a VM is created it doesn't have a root volume for a certain time window.
            This method waits until the root volume exists.
            """
            tries = 60
            while tries > 0:
                root_volumes = [
                    volume
                    for volume in instance.volumes.all()
                    if volume.attachments[0]["Device"] == root
                ]
                if len(root_volumes) == 0:
                    time.sleep(1)
                    tries -= 1
                else:
                    return root_volumes[0]
            raise Exception(f"No root volume found for VM {instance.id}")

        root_volume = get_root_volume()
        resource.root_volume_size = root_volume.size
        ctx.set("root_volume", root_volume)

        resource.volumes = [
            x
            for x in [
                self.get_name_from_tag(volume.tags)
                for volume in instance.volumes.all()
                if volume.attachments[0]["Device"] != root
            ]
            if x is not None
        ]
        resource.subnet_id = instance.subnet_id

        if instance.subnet_id is not None:
            subnet = self._get_subnet(instance.subnet_id)
            if subnet is not None and subnet.tags is not None:
                name_tag = [x for x in subnet.tags if x["Key"] == "Name"]
                if len(name_tag) > 0:
                    resource.subnet = name_tag[0]["Value"]
                else:
                    resource.subnet = None
            else:
                resource.subnet = None

        tags = self.tags_amazon_to_internal(instance.tags)
        del tags["Name"]
        resource.tags = tags

        if instance.state["Name"] == "terminated":
            resource.purged = True
            return

        # these do not work on terminated instances
        result = instance.describe_attribute(Attribute="sourceDestCheck")
        resource.source_dest_check = result["SourceDestCheck"]["Value"]

    def _ensure_key(self, ctx: HandlerContext, key_name, key_value):
        self._ec2.import_key_pair(
            KeyName=key_name, PublicKeyMaterial=key_value.encode()
        )

    def create_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        if not ctx.get("key"):
            self._ensure_key(ctx, resource.key_name, resource.key_value)

        itags = resource.tags
        itags["Name"] = resource.name
        tags = self.tags_internal_to_amazon(itags)

        if resource.subnet is not None:
            subnet = self._get_subnet_by_name(ctx, resource.subnet)
            subnet_id = subnet.id
            vpc_id = subnet.vpc.id
        else:
            subnet_id = resource.subnet_id
            subnets = list(self._ec2.subnets.filter(SubnetIds=[subnet_id]))
            if len(subnets) == 0:
                raise SkipResource("Subnet %s does not exist" % subnet_id)
            vpc_id = subnets[0].vpc.id

        callargs = {}
        if len(resource.security_groups) > 0:
            sgs = list(
                self._ec2.security_groups.filter(
                    Filters=[
                        {"Name": "group-name", "Values": resource.security_groups},
                        {"Name": "vpc-id", "Values": [vpc_id]},
                    ]
                )
            )
            if len(sgs) != len(resource.security_groups):
                ctx.warning(
                    "Unable to find the correct number of security groups. Found: %(groups)s",
                    groups=[x.group_name for x in sgs],
                )
            callargs["SecurityGroupIds"] = [x.id for x in sgs]

        image = list(self._ec2.images.filter(ImageIds=[resource.image]))[0]
        block_device_mapping = image.meta.data["BlockDeviceMappings"]
        block_device_mapping[0]["Ebs"]["VolumeSize"] = resource.root_volume_size
        block_device_mapping[0]["Ebs"]["VolumeType"] = resource.root_volume_type

        ctx.info("args %(args)s", args=callargs)

        instances = self._ec2.create_instances(
            ImageId=resource.image,
            KeyName=resource.key_name,
            UserData=resource.user_data,
            InstanceType=resource.flavor,
            SubnetId=subnet_id,
            MinCount=1,
            MaxCount=1,
            TagSpecifications=[{"ResourceType": "instance", "Tags": tags}],
            EbsOptimized=resource.ebs_optimized,
            BlockDeviceMappings=block_device_mapping,
            **callargs,
        )
        if len(instances) != 1:
            ctx.set_status(const.ResourceState.failed)
            ctx.error(
                "Requested one instance but do not receive it.", instances=instances
            )
            return

        instance = instances[0]

        for volumename in resource.volumes:
            self.attach_for_name(
                ctx, instance, volumename, resource.volume_attachment[volumename]
            )

        if not resource.source_dest_check:
            instance.modify_attribute(Attribute="sourceDestCheck", Value="False")

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: VirtualMachine
    ) -> None:
        todo = len(changes)

        instance = ctx.get("instance")

        if "volumes" in changes:
            current = changes["volumes"]["current"]
            desired = changes["volumes"]["desired"]
            toadd = set(desired) - set(current)
            toremove = set(current) - set(desired)
            if len(toremove) > 0 and not resource.ignore_extra_volumes:
                ctx.warning("Handler will not detach storage!")
            for volumename in toadd:
                self.attach_for_name(
                    ctx, instance, volumename, resource.volume_attachment[volumename]
                )
                todo -= 1

        if "tags" in changes:
            current = changes["tags"]["current"]
            desired = changes["tags"]["desired"]
            tochange = {
                k: v for k, v in desired.items() if k not in current or current[k] != v
            }
            ctx.info("changing tags %(tags)s", tags=tochange)
            instance.create_tags(Tags=self.tags_internal_to_amazon(tochange))
            todo -= 1

        if "image" in changes and resource.ignore_wrong_image:
            todo -= 1

        if "root_volume_size" in changes:
            current = changes["root_volume_size"]["current"]
            desired = changes["root_volume_size"]["desired"]

            if desired < current:
                ctx.warning(
                    "Can not reduce root volume size form %(current)d to %(desired)d",
                    current=current,
                    desired=desired,
                )
            else:
                rv = ctx.get("root_volume")
                self._session.client("ec2").modify_volume(
                    VolumeId=rv.volume_id, Size=desired
                )
                todo -= 1

        if todo > 0:
            ctx.warning(
                "attempting to modify running instance, diff %(diff)s", diff=changes
            )
            raise SkipResource("Modifying a running instance is not supported.")

    def attach_for_name(self, ctx: HandlerContext, instance, volumename, device):
        volume = [
            x
            for x in self._ec2.volumes.filter(
                Filters=[{"Name": "tag:Name", "Values": [volumename]}]
            )
        ]

        if len(volume) != 1:
            ctx.error(
                "Found more than one volume with tag Name %(name)s",
                name=volumename,
                instances=instance,
                volumes=volume,
            )
            raise SkipResource()

        volume = volume[0]

        instance.attach_volume(VolumeId=volume.id, Device=device)

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        instance = ctx.get("instance")
        instance.terminate()

        count = 0
        while instance.state["Name"] != "terminated" and count < 120:
            count += 1
            time.sleep(5)
            instance.reload()

        if instance.state["Name"] != "terminated":
            raise Exception(
                f"Timeout: Instance didn't get into terminated state (current_state={instance.state['Name']})"
            )

    def facts(self, ctx, resource):
        facts = {}

        instance = [
            x
            for x in self._ec2.instances.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource.name]}]
            )
            if x.state["Name"] != "terminated"
        ]
        if len(instance) == 0:
            return {}

        elif len(instance) > 1:
            ctx.info(
                "Found more than one instance with tag Name %(name)s",
                name=resource.name,
                instances=instance,
            )
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

        facts["root_device_name"] = instance.root_device_name

        data = instance.password_data()
        if "PasswordData" in data:
            facts["password_data"] = data["PasswordData"].strip()

        return facts


@provider("aws::Volume", name="volume")
class VolumeHandler(AWSHandler):
    def read_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        instance = [
            x
            for x in self._ec2.volumes.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource.name]}]
            )
        ]

        if len(instance) == 0:
            raise ResourcePurged()

        elif len(instance) > 1:
            ctx.info(
                "Found more than one instance with tag Name %(name)s",
                name=resource.name,
                instances=instance,
            )
            raise SkipResource()

        instance = instance[0]
        ctx.set("instance", instance)
        resource.purged = False
        resource.volume_type = instance.volume_type
        resource.size = instance.size
        resource.encrypted = instance.encrypted

        tags = self.tags_amazon_to_internal(instance.tags)
        del tags["Name"]
        resource.tags = tags

        if instance.state == "terminated":
            resource.purged = True
            return

    def create_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        itags = resource.tags
        itags["Name"] = resource.name
        tags = self.tags_internal_to_amazon(itags)

        instances = self._ec2.create_volume(
            AvailabilityZone=resource.provider["region"] + resource.availability_zone,
            Encrypted=resource.encrypted,
            Size=resource.size,
            VolumeType=resource.volume_type,
            DryRun=False,
            TagSpecifications=[{"ResourceType": "volume", "Tags": tags}],
        )

        if instances is None:
            ctx.set_status(const.ResourceState.failed)
            ctx.error(
                "Requested one Volume but do not receive it.", instances=instances
            )
            return

        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: VirtualMachine
    ) -> None:
        raise SkipResource("Modifying a volume is not supported yet.")

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        ctx.get("instance").delete()
        ctx.set_purged()


@provider("aws::analytics::ElasticSearch", name="elasticsearch")
class ElasticSearchHandler(AWSHandler):
    def pre(self, ctx: HandlerContext, resource: AWSResource) -> None:
        AWSHandler.pre(self, ctx, resource)
        self._es = self._session.client("es")

    def read_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        try:
            instance = self._es.describe_elasticsearch_domain(
                DomainName=resource.domain_name
            )["DomainStatus"]
        except self._es.exceptions.ResourceNotFoundException:
            raise ResourcePurged()

        ctx.warning(
            "Found instance %(mytype)s %(instance)s",
            mytype=str(type(instance)),
            instance=instance,
        )
        ctx.set("instance", instance)

        resource.elasticsearch_version = instance["ElasticsearchVersion"]
        resource.instance_type = instance["ElasticsearchClusterConfig"]["InstanceType"]
        resource.instance_count = instance["ElasticsearchClusterConfig"][
            "InstanceCount"
        ]
        resource.dedicated_master_enabled = instance["ElasticsearchClusterConfig"][
            "DedicatedMasterEnabled"
        ]
        resource.zone_awareness_enabled = instance["ElasticsearchClusterConfig"][
            "ZoneAwarenessEnabled"
        ]
        if "DedicatedMasterType" in instance["ElasticsearchClusterConfig"]:
            resource.dedicated_master_type = instance["ElasticsearchClusterConfig"][
                "DedicatedMasterType"
            ]
        else:
            resource.dedicated_master_type = ""

        if "DedicatedMasterCount" in instance["ElasticsearchClusterConfig"]:
            resource.dedicated_master_count = instance["ElasticsearchClusterConfig"][
                "DedicatedMasterCount"
            ]
        else:
            resource.dedicated_master_count = 0

        resource.ebs_enabled = instance["EBSOptions"]["EBSEnabled"]
        if resource.ebs_enabled:
            resource.volume_type = instance["EBSOptions"]["VolumeType"]
            resource.volume_size = instance["EBSOptions"]["VolumeSize"]

        resource.access_policies = json.dumps(
            json.loads(instance["AccessPolicies"]), sort_keys=True
        )
        resource.automated_snapshot_start_hour = instance["SnapshotOptions"][
            "AutomatedSnapshotStartHour"
        ]

    def convert_resource(self, resource, update=True):
        elasticsearch_cluster_config = {
            "InstanceType": resource.instance_type,
            "InstanceCount": resource.instance_count,
            "DedicatedMasterEnabled": resource.dedicated_master_enabled,
            "ZoneAwarenessEnabled": resource.zone_awareness_enabled,
        }

        if resource.dedicated_master_enabled:
            elasticsearch_cluster_config[
                "DedicatedMasterType"
            ] = resource.dedicated_master_type
            elasticsearch_cluster_config[
                "DedicatedMasterCount"
            ] = resource.dedicated_master_count

        out = {
            "DomainName": resource.domain_name,
            "ElasticsearchVersion": resource.elasticsearch_version,
            "ElasticsearchClusterConfig": elasticsearch_cluster_config,
            "EBSOptions": {
                "EBSEnabled": resource.ebs_enabled,
                "VolumeType": resource.volume_type,
                "VolumeSize": resource.volume_size,
            },
            "AccessPolicies": resource.access_policies,
            "SnapshotOptions": {
                "AutomatedSnapshotStartHour": resource.automated_snapshot_start_hour
            },
        }

        if update:
            del out["ElasticsearchVersion"]
        return out

    def create_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        elasticsearch_cluster_config = {
            "InstanceType": resource.instance_type,
            "InstanceCount": resource.instance_count,
            "DedicatedMasterEnabled": resource.dedicated_master_enabled,
            "ZoneAwarenessEnabled": resource.zone_awareness_enabled,
        }

        if resource.dedicated_master_enabled:
            elasticsearch_cluster_config[
                "DedicatedMasterType"
            ] = resource.dedicated_master_type
            elasticsearch_cluster_config[
                "DedicatedMasterCount"
            ] = resource.dedicated_master_count

        self._es.create_elasticsearch_domain(
            DomainName=resource.domain_name,
            ElasticsearchVersion=resource.elasticsearch_version,
            ElasticsearchClusterConfig=elasticsearch_cluster_config,
            EBSOptions={
                "EBSEnabled": resource.ebs_enabled,
                "VolumeType": resource.volume_type,
                "VolumeSize": resource.volume_size,
            },
            AccessPolicies=resource.access_policies,
            SnapshotOptions={
                "AutomatedSnapshotStartHour": resource.automated_snapshot_start_hour
            },
        )
        ctx.info("Create new Elastic Search")
        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: VirtualMachine
    ) -> None:
        ctx.info("pushing diff %(diff)s", diff=changes)
        self._es.update_elasticsearch_domain_config(**self.convert_resource(resource))
        ctx.set_updated()

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        pass

    def facts(self, ctx, resource):
        facts = {}
        try:
            instance = self._es.describe_elasticsearch_domain(
                DomainName=resource.domain_name
            )["DomainStatus"]
            facts["endpoint"] = instance["Endpoint"]
            facts["arn"] = instance["ARN"]
            facts["id"] = instance["DomainId"]
        except self._es.exceptions.ResourceNotFoundException:
            return facts
        return facts


@provider("aws::database::RDS", name="elasticsearch")
class RDSHandler(AWSHandler):
    def pre(self, ctx: HandlerContext, resource: AWSResource) -> None:
        AWSHandler.pre(self, ctx, resource)
        self._rds = self._session.client("rds")

    def read_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        try:
            instances = self._rds.describe_db_instances(
                DBInstanceIdentifier=resource.name
            )["DBInstances"]
        except Exception:
            raise ResourcePurged()

        if len(instances) == 0:
            raise ResourcePurged()

        elif len(instances) > 1:
            ctx.info(
                "Found more than one RDS instance with name %(name)s",
                name=resource.name,
                instances=instances,
            )
            raise SkipResource()

        instance = instances[0]

        ctx.warning(
            "Found instance %(mytype)s %(instance)s",
            mytype=str(type(instance)),
            instance=instance,
        )
        ctx.set("instance", instance)

        resource.flavor = instance["DBInstanceClass"]
        resource.allocated_storage = instance["AllocatedStorage"]
        resource.engine = instance["Engine"]
        resource.engine_version = instance["EngineVersion"]
        resource.master_user_name = instance["MasterUsername"]
        resource.subnet_group = instance["DBSubnetGroup"]["DBSubnetGroupName"]
        resource.port = instance["Endpoint"]["Port"]
        resource.public = instance["PubliclyAccessible"]

        arn = instance["DBInstanceArn"]

        tags = self._rds.list_tags_for_resource(ResourceName=arn)["TagList"]

        resource.tags = self.tags_amazon_to_internal(tags)

    def create_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        db = self._rds.create_db_instance(
            DBInstanceIdentifier=resource.name,
            AllocatedStorage=resource.allocated_storage,
            DBInstanceClass=resource.flavor,
            Engine=resource.engine,
            MasterUsername=resource.master_user_name,
            MasterUserPassword=resource.master_user_password,
            DBSubnetGroupName=resource.subnet_group,
            Port=resource.port,
            EngineVersion=resource.engine_version,
            PubliclyAccessible=resource.public,
            Tags=self.tags_internal_to_amazon(resource.tags),
        )
        ctx.info(
            "Create new db with id %(id)s", id=db["DBInstance"]["DBInstanceIdentifier"]
        )
        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: VirtualMachine
    ) -> None:
        raise SkipResource("Modifying a RDS is not supported yet.")

    def delete_resource(self, ctx: HandlerContext, resource: VirtualMachine) -> None:
        pass

    def facts(self, ctx, resource):
        facts = {}
        instances = self._rds.describe_db_instances(DBInstanceIdentifier=resource.name)[
            "DBInstances"
        ]

        if len(instances) != 1:
            return facts

        instance = instances[0]

        facts["endpoint"] = instance["Endpoint"]["Address"]
        facts["arn"] = instance["DBInstanceArn"]
        return facts


@provider("aws::VPC", name="ec2")
class VPCHandler(AWSHandler):
    def _get_vpc(self, name):
        return list(
            self._ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        )

    def read_resource(self, ctx: HandlerContext, resource: VPC) -> None:
        vpcs = self._get_vpc(resource.name)
        if len(vpcs) == 0:
            raise ResourcePurged()

        elif len(vpcs) > 1:
            ctx.info(
                "Found more than one vpcs with tag Name %(name)s",
                name=resource.name,
                instances=vpcs,
            )
            raise SkipResource()

        vpc = vpcs[0]
        ctx.set("vpc", vpc)

        resource.cidr_block = vpc.cidr_block
        resource.instance_tenancy = vpc.instance_tenancy
        resource.purged = False

    def create_resource(self, ctx: HandlerContext, resource: VPC) -> None:
        vpc = self._ec2.create_vpc(
            CidrBlock=resource.cidr_block, InstanceTenancy=resource.instance_tenancy
        )

        # This method tends to hit eventual consistency problem returning an error that the subnet does not exist
        tries = 5
        tag_creation_succeeded = False
        while not tag_creation_succeeded and tries > 0:
            try:
                vpc.create_tags(Tags=[{"Key": "Name", "Value": resource.name}])
                tag_creation_succeeded = True
            except botocore.exceptions.ClientError:
                time.sleep(1)
            tries -= 1

        if not tag_creation_succeeded:
            vpc.delete()
            raise Exception(f"Failed to associate tag with VPC {vpc.id}")

        ctx.info("Create new vpc with id %(id)s", id=vpc.id)
        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: VPC
    ) -> None:
        raise SkipResource("A VPC cannot be modified after creation.")

    def delete_resource(self, ctx: HandlerContext, resource: VPC) -> None:
        vpc = ctx.get("vpc")
        ctx.info("Purging vpc %(id)s", id=vpc.id)
        vpc.delete()
        ctx.set_purged()


@provider("aws::Route", name="ec2")
class RouteHandler(AWSHandler):
    def _get_vpc(self, name):
        return list(
            self._ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        )

    def read_resource(self, ctx: HandlerContext, resource: Route) -> None:
        vpcs = self._get_vpc(resource.vpc)
        if len(vpcs) == 0:
            ctx.info(
                "Unable to find vpcs with tag Name %(name)s",
                name=resource.vpc,
                instances=vpcs,
            )
            raise SkipResource()

        elif len(vpcs) > 1:
            ctx.info(
                "Found more than one vpcs with tag Name %(name)s",
                name=resource.vpc,
                instances=vpcs,
            )
            raise SkipResource()

        vpc = vpcs[0]
        ctx.set("vpc", vpc)

        # Find the ENI that is associated with the desired nexthop
        enis = list(
            vpc.network_interfaces.filter(
                Filters=[{"Name": "private-ip-address", "Values": [resource.nexthop]}]
            )
        )

        if len(enis) == 0:
            ctx.info(
                "No ENI found with private ip %(ip)s to route to in vpc tag Name %(name)s.",
                name=resource.vpc,
                ip=resource.nexthop,
            )
            raise SkipResource()

        elif len(enis) > 1:
            raise Exception(
                "Found more than one ENI with the same private ip, this should not happen"
            )

        eni = enis[0]
        ctx.set("eni", eni)

        # Find the route entry in the main routing table of the VPC
        route_tables = list(vpc.route_tables.all())
        if len(route_tables) > 1:
            ctx.info(
                "Found more than one route table in vpc with tag Name %(name)s. Only one is supported currently.",
                name=resource.vpc,
            )
            raise SkipResource()

        route_table = route_tables[0]
        ctx.set("route_table", route_table)

        route = None
        for rt in route_table.routes:
            if rt.destination_cidr_block == resource.destination:
                route = rt
                break

        if route is None:
            raise ResourcePurged()

        ctx.set("route", route)

        if route.network_interface_id != eni.id:
            resource.nexthop = ""

        resource.purged = False

    def create_resource(self, ctx: HandlerContext, resource: Route) -> None:
        route_table = ctx.get("route_table")
        eni = ctx.get("eni")
        route_table.create_route(
            DestinationCidrBlock=resource.destination, NetworkInterfaceId=eni.id
        )
        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: Route
    ) -> None:
        rt = ctx.get("route")
        rt.delete()
        route_table = ctx.get("route_table")
        eni = ctx.get("eni")
        route_table.create_route(
            DestinationCidrBlock=resource.destination, NetworkInterfaceId=eni.id
        )
        ctx.set_updated()

    def delete_resource(self, ctx: HandlerContext, resource: Route) -> None:
        rt = ctx.get("route")
        rt.delete()
        ctx.set_purged()


@provider("aws::Subnet", name="ec2")
class SubnetHandler(AWSHandler):
    def read_resource(self, ctx: HandlerContext, resource: Subnet) -> None:
        subnets = list(
            self._ec2.subnets.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource.name]}]
            )
        )
        if len(subnets) == 0:
            raise ResourcePurged()

        elif len(subnets) > 1:
            ctx.info(
                "Found more than one subnet with tag Name %(name)s",
                name=resource.name,
                instances=subnets,
            )
            raise SkipResource()

        subnet = subnets[0]
        ctx.set("subnet", subnet)
        resource.purged = False
        resource.cidr_block = subnet.cidr_block
        resource.availability_zone = subnet.availability_zone
        resource.map_public_ip_on_launch = subnet.map_public_ip_on_launch

        vpc_tag = [x for x in subnet.vpc.tags if x["Key"] == "Name"]
        resource.vpc = vpc_tag[0]["Value"]

    def create_resource(self, ctx: HandlerContext, resource: Subnet) -> None:
        vpcs = list(
            self._ec2.vpcs.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource.vpc]}]
            )
        )

        if len(vpcs) == 0:
            raise SkipResource("The vpc for this subnet is not available.")

        elif len(vpcs) > 1:
            raise SkipResource("Multiple VPCs with the same name tag found.")

        vpc = vpcs[0]
        args = {"VpcId": vpc.id, "CidrBlock": resource.cidr_block}
        if resource.availability_zone is not None:
            args["AvailabilityZone"] = resource.availability_zone

        tries = 5
        while tries > 0:
            try:
                subnet = self._ec2.create_subnet(**args)
            except botocore.exceptions.ClientError:
                tries -= 1
                if tries > 0:
                    ctx.info("An exception ocurred, retrying", exc_info=True)
                    time.sleep(5)
                else:
                    raise
            else:
                break

        # This method tends to hit eventual consistency problem returning an error that the subnet does not exist
        tries = 5
        tag_creation_succeeded = False
        while not tag_creation_succeeded and tries > 0:
            try:
                subnet.create_tags(Tags=[{"Key": "Name", "Value": resource.name}])
                tag_creation_succeeded = True
            except botocore.exceptions.ClientError:
                time.sleep(5)
            tries -= 1

        if not tag_creation_succeeded:
            subnet.delete()
            raise Exception(f"Failed to associate tag with subnet {subnet.id}")

        if subnet.map_public_ip_on_launch != resource.map_public_ip_on_launch:
            subnet.meta.client.modify_subnet_attribute(
                SubnetId=subnet.id,
                MapPublicIpOnLaunch={"Value": resource.map_public_ip_on_launch},
            )

        ctx.info("Created new subnet with id %(id)s", id=subnet.id)
        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: Subnet
    ) -> None:
        subnet = ctx.get("subnet")
        if "map_public_ip_on_launch" in changes:
            subnet.meta.client.modify_subnet_attribute(
                SubnetId=subnet.id,
                MapPublicIpOnLaunch={"Value": resource.map_public_ip_on_launch},
            )
            ctx.set_updated()

    def delete_resource(self, ctx: HandlerContext, resource: Subnet) -> None:
        subnet = ctx.get("subnet")
        ctx.info("Purging subnet %(id)s", id=subnet.id)
        subnet.delete()
        ctx.set_purged()


@provider("aws::InternetGateway", name="ec2")
class InternetGatewayHandler(AWSHandler):
    def read_resource(self, ctx: HandlerContext, resource: InternetGateway) -> None:
        igws = list(
            self._ec2.internet_gateways.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource.name]}]
            )
        )
        if len(igws) == 0:
            raise ResourcePurged()

        elif len(igws) > 1:
            ctx.info(
                "Found more than one internet gateway with tag Name %(name)s",
                name=resource.name,
                instances=igws,
            )
            raise SkipResource()

        igw = igws[0]
        ctx.set("igw", igw)
        resource.purged = False

        vpc = None
        if len(igw.attachments) > 0 and "VpcId" in igw.attachments[0]:
            data = igw.attachments[0]
            try:
                vpc = list(self._ec2.vpcs.filter(VpcIds=[data["VpcId"]]))[0]
                tags = [x for x in vpc.tags if x["Key"] == "Name"]
                if len(tags) > 0:
                    resource.vpc = tags[0]["Value"]
                else:
                    resource.vpc = None
            except botocore.exceptions.ClientError:
                resource.vpc = None
        else:
            resource.vpc = None
        ctx.set("vpc", vpc)

    def get_vpc(self, name):
        vpcs = list(
            self._ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        )

        if len(vpcs) == 0:
            raise SkipResource("The vpc for this internet gateway is not available.")

        elif len(vpcs) > 1:
            raise SkipResource("Multiple VPCs with the same name tag found.")

        return vpcs[0]

    def create_resource(self, ctx: HandlerContext, resource: InternetGateway) -> None:
        vpc = self.get_vpc(resource.name)
        igw = self._ec2.create_internet_gateway(
            TagSpecifications=[
                {
                    "ResourceType": "internet-gateway",
                    "Tags": [{"Key": "Name", "Value": resource.name}],
                },
            ]
        )
        self._wait_until_creation_is_done(resource.name)
        igw.attach_to_vpc(VpcId=vpc.id)
        ctx.info("Created new internet gateway with id %(id)s", id=igw.id)

        # Check that all VPC route tables have a default route to us
        for tbl in vpc.route_tables.all():
            has_default = False
            for rt in tbl.routes:
                if rt.destination_cidr_block == "0.0.0.0/0":
                    has_default = True

            if not has_default:
                tbl.create_route(DestinationCidrBlock="0.0.0.0/0", GatewayId=igw.id)

        ctx.set_created()

    def _wait_until_creation_is_done(
        self, resource_name: str, timeout: int = 120
    ) -> None:
        start_time = time.time()
        while time.time() - start_time < timeout:
            igws = list(
                self._ec2.internet_gateways.filter(
                    Filters=[{"Name": "tag:Name", "Values": [resource_name]}]
                )
            )
            if igws:
                return
            time.sleep(1)
        raise Exception(
            f"Timeout: waiting for creation internet gateway {resource_name} after {timeout}sec"
        )

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: InternetGateway
    ) -> None:
        igw = ctx.get("igw")
        vpc = self.get_vpc(resource.name)
        igw.attach_to_vpc(VpcId=vpc.id)
        ctx.set_updated()

    def delete_resource(self, ctx: HandlerContext, resource: InternetGateway) -> None:
        igw = ctx.get("igw")
        if len(igw.attachments) > 0:
            igw.detach_from_vpc(VpcId=igw.attachments[0]["VpcId"])
        igw.delete()
        ctx.set_purged()


@provider("aws::SecurityGroup", name="ec2")
class SecurityGroupHandler(AWSHandler):
    def _compare_rule(self, old, new):
        old_keys = old.keys()
        new_keys = new.keys()

        if old_keys != new_keys:
            return False

        for key in old_keys:
            if old[key] != new[key]:
                return False

        return True

    def _diff(self, current, desired):
        changes = AWSHandler._diff(self, current, desired)

        if "rules" in changes:
            old_rules = list(changes["rules"]["current"])
            new_rules = list(changes["rules"]["desired"])

            for new_rule in changes["rules"]["desired"]:
                for old_rule in changes["rules"]["current"]:
                    if self._compare_rule(old_rule, new_rule):
                        old_rules.remove(old_rule)
                        new_rules.remove(new_rule)
                        break

            if len(old_rules) == 0 and len(new_rules) == 0:
                del changes["rules"]

        return changes

    def _build_rule(self, ctx, rule, direction):
        current_rule = {}
        if rule["IpProtocol"] == "-1":
            current_rule["protocol"] = "all"
        else:
            current_rule["protocol"] = rule["IpProtocol"]

        current_rule["direction"] = direction
        current_rule["port_range_min"] = rule.get("FromPort", -1)
        current_rule["port_range_max"] = rule.get("ToPort", -1)

        rules = []
        if rule["IpRanges"] is not None:
            for ip_range in rule["IpRanges"]:
                r = current_rule.copy()
                r["remote_ip_prefix"] = ip_range["CidrIp"]
                rules.append(r)

        elif rule["UserIdGroupPairs"] is not None:
            if len(rule["UserIdGroupPairs"]) > 1:
                ctx.warning(
                    "More than one security group source per rule is not support, only using the first group",
                    groups=rule["UserIdGroupPairs"],
                )

            rgi = self._get_security_group(
                ctx, group_id=rule["UserIdGroupPairs"][0]["GroupId"]
            )
            current_rule["remote_group"] = rgi.name
            rules.append(rgi)
        else:
            ctx.error(
                "No idea what to do with this rule", rule=rule, direction=direction
            )

        return rules

    def _build_current_rules(self, ctx, security_group):
        rules = []
        for rule in security_group.ip_permissions:
            current_rule = self._build_rule(ctx, rule, "ingress")
            rules.extend(current_rule)

        for rule in security_group.ip_permissions_egress:
            current_rule = self._build_rule(ctx, rule, "egress")
            rules.extend(current_rule)

        return rules

    def read_resource(self, ctx: HandlerContext, resource: SecurityGroup) -> None:
        try:
            vpc = self.get_vpc(resource.vpc)
        except SkipResource:
            # If the SG needs to be purged, on subsequent runs the VPC will be also gone (e.g. decommission)
            if not resource.purged:
                raise
            else:
                raise ResourcePurged()

        ctx.set("vpc", vpc)

        sgs = list(
            vpc.security_groups.filter(
                Filters=[
                    {"Name": "group-name", "Values": [resource.name]},
                    {"Name": "vpc-id", "Values": [vpc.id]},
                ]
            )
        )
        if len(sgs) == 0:
            raise ResourcePurged()

        sg = sgs[0]
        ctx.set("sg", sg)
        resource.purged = False
        resource.description = sg.description
        resource.rules = self._build_current_rules(ctx, sg)

        # Verify if correct vpc
        vpc = list(self._ec2.vpcs.filter(VpcIds=[sg.vpc_id]))
        if len(vpc) == 0:
            raise Exception("Invalid response from Amazon API?!?")

        tags = [x for x in vpc[0].tags if x["Key"] == "Name"]
        if len(tags) > 0:
            resource.vpc = tags[0]["Value"]
        else:
            resource.vpc = "No name."

    def get_vpc(self, name):
        vpcs = list(
            self._ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        )

        if len(vpcs) == 0:
            raise SkipResource("The vpc for this security group is not available.")

        elif len(vpcs) > 1:
            raise SkipResource("Multiple VPCs with the same name tag found.")

        return vpcs[0]

    def _build_rule_arg(self, add_rule):
        proto = add_rule["protocol"]
        rule = {
            "FromPort": add_rule["port_range_min"],
            "ToPort": add_rule["port_range_max"],
            "IpProtocol": proto if proto != "all" else "-1",
        }
        if "remote_ip_prefix" in add_rule:
            rule["IpRanges"] = [{"CidrIp": add_rule["remote_ip_prefix"]}]

        elif "remote_group" in add_rule:
            raise Exception("Todo!!")

        return rule

    def _update_rules(self, ctx, group, resource, current_rules, desired_rules):
        """
        Update the rules to the desired state
        """
        remove_rules = list(current_rules)
        add_rules = list(desired_rules)

        for new_rule in desired_rules:
            for old_rule in current_rules:
                if self._compare_rule(old_rule, new_rule):
                    remove_rules.remove(old_rule)
                    add_rules.remove(new_rule)
                    break

        for add_rule in add_rules:
            rule = self._build_rule_arg(add_rule)
            if add_rule["direction"] == "ingress":
                group.authorize_ingress(IpPermissions=[rule])
            else:
                group.authorize_egress(IpPermissions=[rule])

        for remove_rule in remove_rules:
            rule = self._build_rule_arg(remove_rule)
            if remove_rule["direction"] == "ingress":
                group.revoke_ingress(IpPermissions=[rule])
            else:
                group.revoke_egress(IpPermissions=[rule])

    def create_resource(self, ctx: HandlerContext, resource: SecurityGroup) -> None:
        vpc = ctx.get("vpc")
        sg = vpc.create_security_group(
            GroupName=resource.name, Description=resource.description, VpcId=vpc.id
        )
        client = self._session.client("ec2")
        waiter = client.get_waiter("security_group_exists")
        waiter.wait(GroupIds=[sg.id])
        current_rules = self._build_current_rules(ctx, sg)
        self._update_rules(ctx, sg, resource, current_rules, resource.rules)
        ctx.set_created()

    def update_resource(
        self, ctx: HandlerContext, changes: dict, resource: SecurityGroup
    ) -> None:
        if "rules" in changes:
            self._update_rules(
                ctx,
                ctx.get("sg"),
                resource,
                changes["rules"]["current"],
                changes["rules"]["desired"],
            )
        ctx.set_updated()

    def delete_resource(self, ctx: HandlerContext, resource: SecurityGroup) -> None:
        ctx.get("sg").delete()
        ctx.set_purged()
