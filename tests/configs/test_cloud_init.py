from unittest import TestCase
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.config import CloudConfig
from os.path import abspath, join, dirname

TEST_ROOT = abspath(join(dirname(__file__)))

class CloudInitTest(TestCase):

    def test_simple_config(self):
        self._cloud_init_comparator('simple')

    def test_subtree_config(self):
        self._cloud_init_comparator('subtree')

    def _cloud_init_comparator(self, config_dir):
        base_dir = join(TEST_ROOT, config_dir)
        cloud_config = CloudConfig(base_dir)
        cloud_init = CloudInit(cloud_config, base_dir)
        actual_cloud_init = cloud_init.build()
        expected_cloud_init = self._read_cloud_init(base_dir)
        self.assertEquals(actual_cloud_init.strip(), expected_cloud_init.strip())

    def _read_cloud_init(self, base_dir):
        with open(join(base_dir, 'cloud_init.sh'), 'r') as f:
            contents = f.read()
        return contents
