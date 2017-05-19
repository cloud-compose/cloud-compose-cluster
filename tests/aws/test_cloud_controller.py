from builtins import object
from unittest import TestCase
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.config import CloudConfig
from os.path import abspath, join, dirname

TEST_ROOT = abspath(join(dirname(__file__)))

class MockEC2Client(object):
    pass

class MockASGClient(object):
    pass

class CloudInitTest(TestCase):

    def test_security_groups(self):
        controller = self._cloud_controller('single_security_group')
        self.assertEquals(['sg-abc123'], controller.security_groups())

        controller = self._cloud_controller('multi_security_group_comma')
        self.assertEquals(['sg-abc123', 'sg-def456'], controller.security_groups())

        controller = self._cloud_controller('multi_security_group_list')
        self.assertEquals(['sg-abc123', 'sg-def456', 'sg-hij789'], controller.security_groups())

    def _cloud_controller(self, config_dir):
        base_dir = join(TEST_ROOT, config_dir)
        cloud_config = CloudConfig(base_dir)
        return CloudController(cloud_config, ec2_client=MockEC2Client(), asg_client=MockASGClient())
