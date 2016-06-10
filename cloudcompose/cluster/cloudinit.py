from cloudcompose.cluster.template import Template
from cloudcompose.cluster.dockercompose import DockerCompose
from os.path import join, split
from os import environ
from pprint import pprint
from cloudcompose.cloudinit import CloudInit as BaseCloudInit

class CloudInit(BaseCloudInit):
    def __init__(self, base_dir='.'):
        BaseCloudInit.__init__(self, 'cluster', base_dir)

    def build_pre_hook(self, config_data, **kwargs):
        self._add_custom_environment(config_data)
        self._add_docker_compose(config_data)

    def _add_custom_environment(self, config_data):
        for key, val in config_data.get('environment', {}).iteritems():
            if key not in environ:
                environ[key] = Template.render_string(str(val), environ)

    def _add_docker_compose(self, config_data):
        docker_compose = DockerCompose(self.search_path(config_data))
        docker_compose, docker_compose_override = docker_compose.yaml_files(config_data)
        config_data['docker_compose'] = {}
        if docker_compose:
            config_data['docker_compose']['yaml'] = docker_compose
        if docker_compose_override:
            config_data['docker_compose']['override_yaml'] = docker_compose_override
