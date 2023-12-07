# Changelog

## v4.0.1 - ?


## v4.0.0 - 2023-12-07

- Remove aws::Host and dependencies on web and ip. aws::Host worked as a very opinionated drop in replacement
  for ip::Host. However, because it was so opinionated it was never used.
- The install_agent option has been removed. It depends on functionality that is no longer maintained.

## v3.2.13 - 2023-10-12


## v3.2.12 - 2023-06-30


## v3.2.11 - 2023-05-08

- Convert constraints in requirements.txt file

## v3.2.10 - 2023-04-04


## v3.2.9 - 2023-04-04


## v3.2.8 - 2023-02-07


## v3.1.12

- Remove pytest.ini and move its logic to pyproject.toml

## v3.1.11

- Add pytest.ini file and set asyncio_mode to auto

## v3.1.10

- Mark unstable tests with xfail

## v3.1.7

- Update requirements.dev.txt

## v3.1.6

- Fix exception type in test_vm_subnets

## v3.1.4

- Fix for incorrect retry in subnet creation

## v3.1.3

- Marked unstable test as xfail

## v3.0.10

- Update inmanta-dev-dependencies package
- Update boto3
- Improve test stability

## v3.0.9

- Fix a race condition when Creating a VM with security groups

## v3.0.8

- Fix broken VM cleanup in tests

## v3.0.7

- Fix unstable test test_internet_gateway (#209)

## v3.0.6

- Use inmanta-dev-dependencies package

## v3.0.5

- Fix race condition when attaching tags to an internet gateway (#133)

## v3.0.4

- Remove botocore dependency

## v3.0.3

- Upgrade boto3 dependency to v1.14

## v3.0.2

- Pin dependencies using ~=

## v3.0.1

- Pin transitive dependencies

## v3.0.0

- removed decrypt plugin because pycrypto dependency is no longer maintained
