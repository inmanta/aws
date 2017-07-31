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

def test_vm(project, ec2):
    name = "inmanta-unit-test"
    key = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQCsiYV4Cr2lD56bkVabAs2i0WyGSjJbuNHP6IDf8Ru3Pg7DJkz0JaBmETHNjIs+yQ98DNkwH9gZX0"
           "gfrSgX0YfA/PwTatdPf44dwuwWy+cjS2FAqGKdLzNVwLfO5gf74nit4NwATyzakoojHn7YVGnd9ScWfwFNd5jQ6kcLZDq/1w== "
           "bart@wolf.inmanta.com")
    # TODO: find a subnet
    # TODO: find an ami
    project.compile("""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="%(name)s", public_key="%(key)s")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="ami-30876e5f", user_data="", public_key=key,
                    subnet_id="subnet-e91c4880", name="%(name)s")
        """ % {"name": name, "key": key})

    project.deploy_resource("aws::VirtualMachine")

    instances = [x for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
                 if x.state["Name"] != "terminated"]

    assert len(instances) == 1

    # run again -> idempotent
    project.compile("""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="%(name)s", public_key="%(key)s")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="ami-30876e5f", user_data="", public_key=key,
                    subnet_id="subnet-e91c4880", name="%(name)s")
        """ % {"name": name, "key": key})

    project.deploy_resource("aws::VirtualMachine")

    instances = [x for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
                 if x.state["Name"] != "terminated"]

    assert len(instances) == 1

    project.compile("""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region="eu-central-1",
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="%(name)s", public_key="%(key)s")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="ami-30876e5f", user_data="", public_key=key,
                    subnet_id="subnet-e91c4880", name="%(name)s", purged=true)
        """ % {"name": name, "key": key})

    project.deploy_resource("aws::VirtualMachine")

    instances = [x for x in ec2.instances.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])
                 if x.state["Name"] != "terminated"]

    assert len(instances) == 1


def test_vm_subnets(project):
    # set a subnet id
    project.compile("""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="test", public_key="test")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="ami-30876e5f", user_data="", public_key=key,
                    subnet_id="subnet-e91c4880", name="test")
        """)

    # set a subnet instance
    project.compile("""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="test", public_key="test")
aws::VirtualMachine(provider=provider, flavor="t2.small", image="ami-30876e5f", user_data="", public_key=key,
                    subnet=subnet, name="test")
        """)



def test_lb(project, ec2):
    name = "inmanta-demo"
    key = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQCsiYV4Cr2lD56bkVabAs2i0WyGSjJbuNHP6IDf8Ru3Pg7DJkz0JaBmETHNjIs+yQ98DNkwH9gZX0"
           "gfrSgX0YfA/PwTatdPf44dwuwWy+cjS2FAqGKdLzNVwLfO5gf74nit4NwATyzakoojHn7YVGnd9ScWfwFNd5jQ6kcLZDq/1w== "
           "bart@wolf.inmanta.com")

    project.compile("""
import unittest
import aws
import ssh

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")
key = ssh::Key(name="%(name)s", public_key="%(key)s")
aws::ELB(provider=provider, name="%(name)s")
        """ % {"name": name, "key": key})

    project.deploy_resource("aws::ELB")


def test_vpc(project, ec2):
    name = "inmanta-unit-test"
    project.compile("""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="%s", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
""" % name)

    project.deploy_resource("aws::VPC")
    vpcs = [x for x in ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])]

    assert len(vpcs) == 1

    # Deploy a second time
    project.deploy_resource("aws::VPC")
    vpcs = [x for x in ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])]

    assert len(vpcs) == 1

    # Purge it
    project.compile("""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="%s", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
""" % name)

    project.deploy_resource("aws::VPC")
    vpcs = [x for x in ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [name]}])]

    assert len(vpcs) == 0


def test_internet_gateway(project, ec2):
    name = "inmanta-unit-test"
    project.compile("""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default")
aws::InternetGateway(name="{0}", provider=provider, vpc=vpc)
""".format(name))

    project.deploy_resource("aws::VPC")
    project.deploy_resource("aws::InternetGateway")
    igw = list(ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}]))
    assert len(igw) == 1

    # Deploy a second time
    project.deploy_resource("aws::InternetGateway")
    igw = list(ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}]))
    assert len(igw) == 1

    # Remove vpc and test attaching it again
    igw[0].detach_from_vpc(VpcId=igw[0].attachments[0]["VpcId"])

    project.deploy_resource("aws::InternetGateway")
    igw = list(ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}]))
    assert len(igw) == 1

    assert len(igw[0].attachments) == 1

    # Purge it
    project.compile("""
import aws

provider = aws::Provider(name="test", access_key=std::get_env("AWS_ACCESS_KEY_ID"), region=std::get_env("AWS_REGION"),
                         secret_key=std::get_env("AWS_SECRET_ACCESS_KEY"), availability_zone="a")

vpc = aws::VPC(name="{0}", provider=provider, cidr_block="10.0.0.0/23", instance_tenancy="default", purged=true)
aws::InternetGateway(name="{0}", provider=provider, vpc=vpc, purged=true)
""".format(name))

    project.deploy_resource("aws::InternetGateway")
    igw = list(ec2.internet_gateways.filter(Filters=[{"Name": "tag:Name", "Values": [name]}]))
    assert len(igw) == 0

    project.deploy_resource("aws::VPC")
