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
import logging

import pytest
from conftest import retry_limited
from inmanta.ast import ExternalException

# States that indicate that an instance is terminated or is getting terminated
INSTANCE_TERMINATING_STATES = ["terminated", "shutting-down"]

LOGGER = logging.getLogger(__name__)


def test_vm(project, ec2, subnet_id, latest_amzn_image, resource_name_prefix: str):
    """
    Test VM creation.
    """
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
key = ssh::Key(name="{resource_name_prefix}", public_key="{key}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet_id="{subnet_id}", name="{resource_name_prefix}")
        """

    project.compile(model)
    project.deploy_resource("aws::VirtualMachine")

    instances = [
        x
        for x in ec2.instances.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
        if x.state["Name"] not in INSTANCE_TERMINATING_STATES
    ]

    assert len(instances) == 1

    # run again -> idempotent
    project.compile(model)

    project.deploy_resource("aws::VirtualMachine")

    instances = [
        x
        for x in ec2.instances.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
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
key = ssh::Key(name="{resource_name_prefix}", public_key="{key}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet_id="{subnet_id}", name="{resource_name_prefix}", purged=true)
        """
    )
    project.deploy_resource("aws::VirtualMachine")

    instances = [
        x
        for x in ec2.instances.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
        if x.state["Name"] != "terminated"
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
    with pytest.raises(
        (ExternalException, ValueError)
    ):  # need ValueError here so that the test doesn't fail for stable products
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
    with pytest.raises(
        (ExternalException, ValueError)
    ):  # need ValueError here so that the test doesn't fail for stable products
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


@pytest.mark.xfail(strict=False)
def test_deploy_vm_vpc(project, ec2, latest_amzn_image, resource_name_prefix: str):
    """
    Test deploying a virtual machine in a dedicated VPC
    """
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
key = ssh::Key(name="{resource_name_prefix}", public_key="{key}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet=subnet, name="{resource_name_prefix}")
vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc,
                     map_public_ip_on_launch=true)
aws::InternetGateway(name="{resource_name_prefix}", provider=provider, vpc=vpc)
        """
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
key = ssh::Key(name="{resource_name_prefix}", public_key="{key}")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="{latest_amzn_image.id}", user_data="", public_key=key,
                    subnet=subnet, name="{resource_name_prefix}", purged=true)
vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default",
               purged=true)
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc,
                     map_public_ip_on_launch=true, purged=true)
aws::InternetGateway(name="{resource_name_prefix}", provider=provider, vpc=vpc, purged=true)
        """
    )

    project.deploy_resource("aws::VirtualMachine")
    project.deploy_resource("aws::InternetGateway")
    project.deploy_resource("aws::Subnet")
    project.deploy_resource("aws::VPC")


def test_lb(project, ec2, resource_name_prefix: str):
    key = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQCsiYV4Cr2lD56bkVabAs2i0WyGSjJbuNHP6IDf8Ru3Pg7DJkz0JaBmETHNjIs+yQ98DNkwH9gZX0"
        "gfrSgX0YfA/PwTatdPf44dwuwWy+cjS2FAqGKdLzNVwLfO5gf74nit4NwATyzakoojHn7YVGnd9ScWfwFNd5jQ6kcLZDq/1w== "
        "bart@wolf.inmanta.com"
    )

    # Create loadbalancer
    project.compile(
        f"""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="{resource_name_prefix}", public_key="{key}")
aws::ELB(provider=provider, name="{resource_name_prefix}")
        """
    )

    project.deploy_resource("aws::ELB")

    # Purge loadbalancer
    project.compile(
        f"""
    import unittest
    import aws
    import ssh

    provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                             secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
    key = ssh::Key(name="{resource_name_prefix}", public_key="{key}")
    aws::ELB(provider=provider, name="{resource_name_prefix}", purged=true)
            """
    )

    project.deploy_resource("aws::ELB")


def test_vpc(project, ec2, resource_name_prefix: str):
    """
    Test VPC creation/deletion
    """
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
"""
    )

    project.deploy_resource("aws::VPC")
    vpcs = [
        x
        for x in ec2.vpcs.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]

    assert len(vpcs) == 1

    # Deploy a second time
    project.deploy_resource("aws::VPC")
    vpcs = [
        x
        for x in ec2.vpcs.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]

    assert len(vpcs) == 1

    # Purge it
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default",
               purged=true)
"""
    )

    project.deploy_resource("aws::VPC")
    vpcs = [
        x
        for x in ec2.vpcs.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]

    assert len(vpcs) == 0


def test_subnet(project, ec2, resource_name_prefix: str):
    """
    Test subnet creation/deletion
    """
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc)
"""
    )

    project.deploy_resource("aws::VPC")

    project.deploy_resource("aws::Subnet")
    subnets = [
        x
        for x in ec2.subnets.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]
    assert len(subnets) == 1

    # Deploy a second time
    project.deploy_resource("aws::Subnet")
    subnets = [
        x
        for x in ec2.subnets.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]
    assert len(subnets) == 1

    # Purge it
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default",
               purged=true)
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, purged=true)
"""
    )

    project.deploy_resource("aws::Subnet")
    subnets = [
        x
        for x in ec2.subnets.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]
    assert len(subnets) == 0

    project.deploy_resource("aws::VPC")


def test_subnet_map_public(project, ec2, resource_name_prefix: str):
    """
    Test the map_public_ip_on_launch feature of a aws::Subnet resource
    """
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc,
                     map_public_ip_on_launch=true)
"""
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::Subnet")
    subnets = [
        x
        for x in ec2.subnets.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]
    assert len(subnets) == 1

    assert subnets[0].map_public_ip_on_launch

    # Turn map public off
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc,
                     map_public_ip_on_launch=false)
"""
    )

    project.deploy_resource("aws::Subnet")
    subnets = [
        x
        for x in ec2.subnets.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]
    assert len(subnets) == 1
    assert not subnets[0].map_public_ip_on_launch

    # Purge it
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default",
               purged=true)
subnet = aws::Subnet(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/24", vpc=vpc, purged=true)
"""
    )

    project.deploy_resource("aws::Subnet")
    subnets = [
        x
        for x in ec2.subnets.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    ]
    assert len(subnets) == 0

    project.deploy_resource("aws::VPC")


def assert_attachments_internet_gateway(
    ec2, resource_name: str, nr_attachments: int
) -> None:
    def func():
        igws = list(
            ec2.internet_gateways.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource_name]}]
            )
        )
        if not igws:
            LOGGER.info(f"Internet gateway '{resource_name}' doesn't exist.")
            return False
        LOGGER.info(
            "Internet gateway '%s' has attachments %s (expected amount=%d)",
            resource_name,
            igws[0].attachments,
            nr_attachments,
        )
        return len(igws[0].attachments) == nr_attachments

    retry_limited(func, timeout=900)


def test_internet_gateway(project, ec2, resource_name_prefix: str):
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
aws::InternetGateway(name="{resource_name_prefix}", provider=provider, vpc=vpc)
"""
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::InternetGateway")
    igw = list(
        ec2.internet_gateways.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    )
    assert len(igw) == 1

    LOGGER.info("Deploy a second time")
    project.deploy_resource("aws::InternetGateway")
    igw = list(
        ec2.internet_gateways.filter(
            Filters=[{"Name": "tag:Name", "Values": [resource_name_prefix]}]
        )
    )
    assert len(igw) == 1

    assert_attachments_internet_gateway(ec2, resource_name_prefix, 1)

    LOGGER.info("Remove vpc and test attaching it again")
    igw[0].detach_from_vpc(VpcId=igw[0].attachments[0]["VpcId"])
    assert_attachments_internet_gateway(ec2, resource_name_prefix, 0)

    project.deploy_resource("aws::InternetGateway")
    assert_attachments_internet_gateway(ec2, resource_name_prefix, 1)

    LOGGER.info("Purge it")
    project.compile(
        f"""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default",
               purged=true)
aws::InternetGateway(name="{resource_name_prefix}", provider=provider, vpc=vpc, purged=true)
"""
    )

    project.deploy_resource("aws::InternetGateway")

    def is_igw_deleted(resource_name: str) -> bool:
        igws = list(
            ec2.internet_gateways.filter(
                Filters=[{"Name": "tag:Name", "Values": [resource_name]}]
            )
        )
        LOGGER.info("Found internet gateways: %s (expected [])", igws)
        return len(igws) == 0

    retry_limited(is_igw_deleted, timeout=120, resource_name=resource_name_prefix)

    project.deploy_resource("aws::VPC")


def test_security_group(project, ec2, resource_name_prefix: str):
    project.compile(
        f"""
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")

sg_base = aws::SecurityGroup(name="{resource_name_prefix}", description="Clearwater base", vpc=vpc, provider=provider)
aws::IPrule(group=sg_base, direction="egress", ip_protocol="all", remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="udp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="tcp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
        """
    )

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::SecurityGroup")
    project.deploy_resource("aws::SecurityGroup")

    project.compile(
        f"""
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{resource_name_prefix}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default",
               purged=true)

sg_base = aws::SecurityGroup(name="{resource_name_prefix}", description="Clearwater base", vpc=vpc, provider=provider,
                             purged=true)
aws::IPrule(group=sg_base, direction="egress", ip_protocol="all", remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="udp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
aws::IPrule(group=sg_base, direction="ingress", ip_protocol="tcp", port_min=161, port_max=162, remote_prefix="0.0.0.0/0")
        """
    )

    project.deploy_resource("aws::SecurityGroup")
    project.deploy_resource("aws::VPC")


def test_volume(project, resource_name_prefix: str):
    # Create volume
    project.compile(
        f"""
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
volume = aws::Volume(name="{resource_name_prefix}", provider=provider, availability_zone="a")
"""
    )

    project.deploy_resource("aws::Volume")

    # Purge volume
    project.compile(
        f"""
import unittest
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
volume = aws::Volume(name="{resource_name_prefix}", provider=provider, availability_zone="a", purged=true)
"""
    )

    project.deploy_resource("aws::Volume")
