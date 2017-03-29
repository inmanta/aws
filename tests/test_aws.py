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
    assert False
