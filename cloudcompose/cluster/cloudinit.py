from cloudcompose.cluster.template import Template
from cloudcompose.cluster.dockercompose import DockerCompose
from os.path import join, split
from pprint import pprint
from cloudcompose.cloudinit import CloudInit as BaseCloudInit

class CloudInit(BaseCloudInit):
    def __init__(self, base_dir='.'):
        BaseCloudInit.__init__(self, 'cluster', base_dir)

    def build_pre_hook(self, config_data, **kwargs):
        self._add_docker_compose(config_data)

    def _add_docker_compose(self, config_data):
        docker_compose = DockerCompose(self.search_path(config_data))
        docker_compose, docker_compose_override = docker_compose.yaml_files(config_data)
        config_data['docker_compose'] = {}
        config_data['docker_compose']['yaml'] = docker_compose
        config_data['docker_compose']['override_yaml'] = docker_compose_override
