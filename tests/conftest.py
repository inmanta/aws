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
import os
import time

import boto3
import botocore
import pytest

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def resource_name_prefix():
    """
    All resources with this name or prefixed with this name
    will be cleaned up automatically at the end the test run
    by the cleanup fixture.
    """
    return "inmanta-unit-test"


@pytest.fixture(scope="session")
def session():
    yield boto3.Session(
        region_name=os.environ["AWS_REGION"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


@pytest.fixture(scope="session")
def ec2(session):
    yield session.resource("ec2")


@pytest.fixture(scope="session")
def elb(session):
    yield session.client("elb")


@pytest.fixture(scope="session")
def latest_amzn_image(ec2):
    result = ec2.images.filter(
        Owners=["amazon"],
        Filters=[{"Name": "name", "Values": ["amzn-ami-hvm-*-x86_64-gp2"]}],
    )
    name_to_image_dct = {r.meta.data["Name"]: r for r in result}
    name_latest_image = sorted(name_to_image_dct.keys())[-1]
    yield name_to_image_dct[name_latest_image]


@pytest.fixture
def vpc(ec2, resource_name_prefix, cleanup):
    vpc = ec2.create_vpc(CidrBlock="10.10.0.0/23", InstanceTenancy="default")
    # This method tends to hit eventual consistency problem returning an error that the subnet does not exist
    tries = 5
    tag_creation_succeeded = False
    while not tag_creation_succeeded and tries > 0:
        try:
            vpc.create_tags(
                Tags=[{"Key": "Name", "Value": f"{resource_name_prefix}-subnet"}]
            )
            tag_creation_succeeded = True
        except botocore.exceptions.ClientError:
            time.sleep(5)
        tries -= 1

    if not tag_creation_succeeded:
        vpc.delete()
        raise Exception(f"Failed to associate tag with VPC {vpc.id}")

    yield vpc


@pytest.fixture
def subnet_id(ec2, vpc, cleanup):
    subnet = ec2.create_subnet(
        VpcId=vpc.id,
        CidrBlock="10.10.0.0/24",
        AvailabilityZone=f"{os.environ['AWS_REGION']}a",
    )
    yield subnet.id


@pytest.fixture(autouse=True)
def cleanup(ec2, elb, resource_name_prefix: str):
    _cleanup(ec2, elb, resource_name_prefix)
    yield
    _cleanup(ec2, elb, resource_name_prefix)


WAIT_ITERATIONS = 120
WAIT_SLEEP = 5


def cleanup_instances(ec2, resource_name_prefix: str):
    # Delete instances
    instances = ec2.instances.filter(
        Filters=[{"Name": "tag:Name", "Values": [f"{resource_name_prefix}*"]}]
    )
    for i in instances:
        LOGGER.debug("Cleanup: terminating vm %s", i)
        i.terminate()

    # Wait for instance termination
    count = 0
    while (
        not all([i.state["Name"] == "terminated" for i in instances])
        and count < WAIT_ITERATIONS
    ):
        count += 1
        time.sleep(WAIT_SLEEP)
        for i in instances:
            i.reload()

    if not all([i.state["Name"] == "terminated" for i in instances]):
        raise Exception("Instances not in terminated state")


def cleanup_igw(ec2, resource_name_prefix: str):
    # Delete InternetGateways
    internet_gateways = ec2.internet_gateways.filter(
        Filters=[{"Name": "tag:Name", "Values": [f"{resource_name_prefix}*"]}]
    )
    for igw in internet_gateways:
        for attached_vpc in igw.meta.data["Attachments"]:
            igw.detach_from_vpc(DryRun=False, VpcId=attached_vpc["VpcId"])
        LOGGER.debug("Cleanup: deleting internet gateway %s", igw)
        igw.delete()


def cleanup_vpc(ec2, resource_name_prefix: str):
    # Delete vpcs
    vpcs = ec2.vpcs.filter(
        Filters=[{"Name": "tag:Name", "Values": [f"{resource_name_prefix}*"]}]
    )
    for vpc in vpcs:
        # Delete dependent security groups
        sgs = vpc.security_groups.filter(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc.id]},
                {"Name": "group-name", "Values": [f"{resource_name_prefix}*"]},
            ]
        )
        for sg in sgs:
            LOGGER.debug("Cleanup: deleting security group %s", sg)
            sg.delete()

        # Delete dependent subnets
        subnets = ec2.subnets.filter(Filters=[{"Name": "vpc-id", "Values": [vpc.id]}])
        for subnet in subnets:
            LOGGER.debug("Cleanup: deleting subnet %s", subnet)
            subnet.delete()

        # Delete vpc
        vpc.delete()
        LOGGER.debug("Cleanup: deleting vpc %s", vpc)


def cleanup_volumes(ec2, resource_name_prefix: str):
    # Delete volumes
    volumes = ec2.volumes.filter(
        Filters=[{"Name": "tag:Name", "Values": [f"{resource_name_prefix}*"]}]
    )
    for volume in volumes:
        LOGGER.debug("Cleanup: deleting volume %s", volume)
        volume.delete()


def cleanup_ssh(ec2, resource_name_prefix: str):
    # Delete SSH keys
    keys = ec2.key_pairs.filter(
        Filters=[{"Name": "key-name", "Values": [f"{resource_name_prefix}"]}]
    )
    for key in keys:
        LOGGER.debug("Cleanup: deleting key %s", key)
        key.delete()


def cleanup_elb(elb, resource_name_prefix: str):
    # Delete loadbalancer
    lb_descriptions = elb.describe_load_balancers()
    lbs_to_delete = [
        lb_description["LoadBalancerName"]
        for lb_description in lb_descriptions["LoadBalancerDescriptions"]
        if lb_description["LoadBalancerName"].startswith(resource_name_prefix)
    ]

    for lb_name in lbs_to_delete:
        LOGGER.debug("Cleanup: deleting elb %s", lb_name)
        elb.delete_load_balancer(LoadBalancerName=lb_name)


def _cleanup(ec2, elb, resource_name_prefix: str):
    functions = [
        (cleanup_instances, (ec2, resource_name_prefix)),
        (cleanup_volumes, (ec2, resource_name_prefix)),
        (cleanup_igw, (ec2, resource_name_prefix)),
        (cleanup_vpc, (ec2, resource_name_prefix)),
        (cleanup_ssh, (ec2, resource_name_prefix)),
        (cleanup_elb, (elb, resource_name_prefix)),
    ]
    # ignore cleanup failures
    for function, arguments in functions:
        try:
            function(*arguments)
        except Exception:
            LOGGER.exception("Failed to execute cleanup method %s", function.__name__)


def retry_limited(fun, timeout, *args, **kwargs):
    start = time.time()
    while time.time() - start < timeout:
        if fun(*args, **kwargs):
            return
        time.sleep(1)
    raise AssertionError("Bounded wait failed")
