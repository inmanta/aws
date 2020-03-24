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
import pytest

# States that indicate that an instance is terminated or is getting terminated
INSTANCE_TERMINATING_STATES = ["terminated", "shutting-down"]


# def _wait_for_vm_to_be_is_running_state(ec2, instance_name: str) -> None:
#     instances = [
#         x
#         for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [instance_name]}])
#         if x.state["Name"] not in INSTANCE_TERMINATING_STATES
#     ]
#     if not instances:
#         raise Exception(f"No not-terminated instance found with name {instance_name}")
#
#     counter = 60
#     while not all([x.state["Name"] == "running" for x in instances]) and counter > 0:
#         print([x.state["Name"] for x in instances])
#         time.sleep(2)
#         for x in instances:
#             x.reload()
#     if not all([x.state["Name"] == "running" for x in instances]):
#         raise Exception("Timeout: Instance didn't get into the running state")


def test_vm(project, ec2, subnet_id, latest_amzn_image):
    """
        Test VM creation.
    """
    name = "inmanta-unit-test"
    key = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQCsiYV4Cr2lD56bkVabAs2i0WyGSjJbuNHP6IDf8Ru3Pg7DJkz0JaBmETHNjIs+yQ98DNkwH9gZX0"
        "gfrSgX0YfA/PwTatdPf44dwuwWy+cjS2FAqGKdLzNVwLfO5gf74nit4NwATyzakoojHn7YVGnd9ScWfwFNd5jQ6kcLZDq/1w== "
        "bart@wolf.inmanta.com"
    )
    model = f"""
import unittest
import aws
import ssh
provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="{name}", public_key="{key}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet_id="{subnet_id}", name="{name}")
        """

    project.compile(model)
    project.deploy_resource("aws::VirtualMachine")

    instances = [
        x
        for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        if x.state["Name"] not in INSTANCE_TERMINATING_STATES
    ]

    assert len(instances) == 1

    # run again -> idempotent
    project.compile(model)

    project.deploy_resource("aws::VirtualMachine")

    instances = [
        x
        for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        if x.state["Name"] not in INSTANCE_TERMINATING_STATES
    ]

    assert len(instances) == 1

    project.compile(
        f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="{name}", public_key="{key}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet_id="{subnet_id}", name="{name}", purged=true)
        """
    )
    project.deploy_resource("aws::VirtualMachine")

    instances = [
        x
        for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
        if x.state["Name"] not in INSTANCE_TERMINATING_STATES
    ]

    assert len(instances) == 0


def test_vm_subnets(project, latest_amzn_image):
    """
        A subnet can be attached to a virtualmachine via the subnet or the subnet_id attribute.
        One of both attributes should be set, but not both at the same time.
    """
    # set a subnet id
    project.compile(
        f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="test", public_key="test")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet_id="subnet-e91c4880", name="test")
        """
    )

    # set a subnet instance
    project.compile(
        f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="test", public_key="test")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet=subnet, name="test")
vpc = aws::VPC(name="test", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="test", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc)
        """
    )

    # set none
    with pytest.raises(ValueError):
        project.compile(
            f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="test", public_key="test")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    name="test")
        """
        )

    # set both
    with pytest.raises(ValueError):
        project.compile(
            f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="test", public_key="test")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet=subnet, subnet_id="1214", name="test")
vpc = aws::VPC(name="test", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="test", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc)
        """
        )


def test_deploy_vm_vpc(project, ec2, latest_amzn_image):
    """
        Test deploying a virtual machine in a dedicated VPC
    """
    name = "inmanta-unit-test"
    key = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQCsiYV4Cr2lD56bkVabAs2i0WyGSjJbuNHP6IDf8Ru3Pg7DJkz0JaBmETHNjIs+yQ98DNkwH9gZX0"
        "gfrSgX0YfA/PwTatdPf44dwuwWy+cjS2FAqGKdLzNVwLfO5gf74nit4NwATyzakoojHn7YVGnd9ScWfwFNd5jQ6kcLZDq/1w== "
        "bart@wolf.inmanta.com"
    )
    project.compile(
        f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="{0}", public_key="{1}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet=subnet, name="test")
vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, map_public_ip_on_launch=true)
aws::InternetGateway(name="{0}", provider=provider, vpc=vpc)
        """.format(
            name, key
        )
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::Subnet")
    project.deploy_resource("aws::InternetGateway")
    project.deploy_resource("aws::VirtualMachine")

    # delete it all
    project.compile(
        f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="{0}", public_key="{1}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet=subnet, name="test", purged=true)
vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc,
                     map_public_ip_on_launch=true, purged=true)
aws::InternetGateway(name="{0}", provider=provider, vpc=vpc, purged=true)
        """.format(
            name, key
        )
    )

    project.deploy_resource("aws::VirtualMachine")
    project.deploy_resource("aws::InternetGateway")
    project.deploy_resource("aws::Subnet")
    project.deploy_resource("aws::VPC")


def test_lb(project, ec2):
    name = "inmanta-demo"
    key = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQCsiYV4Cr2lD56bkVabAs2i0WyGSjJbuNHP6IDf8Ru3Pg7DJkz0JaBmETHNjIs+yQ98DNkwH9gZX0"
        "gfrSgX0YfA/PwTatdPf44dwuwWy+cjS2FAqGKdLzNVwLfO5gf74nit4NwATyzakoojHn7YVGnd9ScWfwFNd5jQ6kcLZDq/1w== "
        "bart@wolf.inmanta.com"
    )

    project.compile(
        """
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="%(name)s", public_key="%(key)s")
aws::ELB(provider=provider, name="%(name)s")
        """
        % {"name": name, "key": key}
    )

    project.deploy_resource("aws::ELB")


def test_vpc(project, ec2):
    name = "inmanta-unit-test"
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="%s", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
"""
        % name
    )

    project.deploy_resource("aws::VPC")
    vpcs = [
        x for x in ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]

    assert len(vpcs) == 1

    # Deploy a second time
    project.deploy_resource("aws::VPC")
    vpcs = [
        x for x in ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]

    assert len(vpcs) == 1

    # Purge it
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="%s", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
"""
        % name
    )

    project.deploy_resource("aws::VPC")
    vpcs = [
        x for x in ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]

    assert len(vpcs) == 0


def test_subnet(project, ec2):
    name = "inmanta-unit-test"
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc)
""".format(
            name
        )
    )

    project.deploy_resource("aws::VPC")

    project.deploy_resource("aws::Subnet")
    subnets = [
        x for x in ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]
    assert len(subnets) == 1

    # Deploy a second time
    project.deploy_resource("aws::Subnet")
    subnets = [
        x for x in ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]
    assert len(subnets) == 1

    # Purge it
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, purged=true)
""".format(
            name
        )
    )

    project.deploy_resource("aws::Subnet")
    subnets = [
        x for x in ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]
    assert len(subnets) == 0

    project.deploy_resource("aws::VPC")


def test_subnet_map_public(project, ec2):
    name = "inmanta-unit-test"
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, map_public_ip_on_launch=true)
""".format(
            name
        )
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::Subnet")
    subnets = [
        x for x in ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]
    assert len(subnets) == 1

    assert subnets[0].map_public_ip_on_launch

    # Turn map public off
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, map_public_ip_on_launch=false)
""".format(
            name
        )
    )

    project.deploy_resource("aws::Subnet")
    subnets = [
        x for x in ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]
    assert len(subnets) == 1
    assert not subnets[0].map_public_ip_on_launch

    # Purge it
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
subnet = aws::Subnet(name="{0}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, purged=true)
""".format(
            name
        )
    )

    project.deploy_resource("aws::Subnet")
    subnets = [
        x for x in ec2.subnets.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    ]
    assert len(subnets) == 0

    project.deploy_resource("aws::VPC")


def test_internet_gateway(project, ec2):
    name = "inmanta-unit-test"
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
aws::InternetGateway(name="{0}", provider=provider, vpc=vpc)
""".format(
            name
        )
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::InternetGateway")
    igw = list(
        ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    )
    assert len(igw) == 1

    # Deploy a second time
    project.deploy_resource("aws::InternetGateway")
    igw = list(
        ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    )
    assert len(igw) == 1

    # Remove vpc and test attaching it again
    igw[0].detach_from_vpc(VpcId=igw[0].attachments[0]["VpcId"])

    project.deploy_resource("aws::InternetGateway")
    igw = list(
        ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    )
    assert len(igw) == 1

    assert len(igw[0].attachments) == 1

    # Purge it
    project.compile(
        """
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
aws::InternetGateway(name="{0}", provider=provider, vpc=vpc, purged=true)
""".format(
            name
        )
    )

    project.deploy_resource("aws::InternetGateway")
    igw = list(
        ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
    )
    assert len(igw) == 0

    project.deploy_resource("aws::VPC")


def test_security_group(project, ec2):
    name = "inmanta_unit_test"

    project.compile(
        """
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="%(name)s", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")

sg_base = aws::SecurityGroup(name="%(name)s", description="Clearwater base", vpc=vpc, provider=provider)
aws::IPrule(group=sg_base, direction="egress", ip_protocol="all", remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="udp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="tcp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
        """
        % {"name": name}
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::SecurityGroup")
    project.deploy_resource("aws::SecurityGroup")

    project.compile(
        """
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="%(name)s", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)

sg_base = aws::SecurityGroup(name="%(name)s", description="Clearwater base", vpc=vpc, provider=provider, purged=true)
aws::IPrule(group=sg_base, direction="egress", ip_protocol="all", remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="udp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="tcp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
        """
        % {"name": name}
    )

    project.deploy_resource("aws::SecurityGroup")
    project.deploy_resource("aws::VPC")


def test_volume(project):
    project.compile(
        """
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
volume = aws::Volume(name="test", provider=provider, availability_zone="a")
"""
    )

    project.deploy_resource("aws::Volume")
