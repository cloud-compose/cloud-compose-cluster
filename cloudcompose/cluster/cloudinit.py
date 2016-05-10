from cloudcompose.cluster.template import Template
from cloudcompose.cluster.dockercompose import DockerCompose
from os.path import join, split
from pprint import pprint

class CloudInit():
    def __init__(self, base_dir='.'):
        self.base_dir = base_dir
        self.template_file = 'cluster.sh'

    def build(self, config_data, **kwargs):
        raw_search_path = config_data['search_path']
        raw_search_path.insert(0, '.')
        search_path = [join(self.base_dir, path) for path in raw_search_path]
        for key, value in kwargs.iteritems():
            config_data['_' + key] = value

        self._add_docker_compose(config_data, search_path)
        return self._render_template(config_data, search_path)

    def _add_docker_compose(self, config_data, search_path):
        docker_compose = DockerCompose(search_path)
        docker_compose, docker_compose_override = docker_compose.yaml_files(config_data)
        config_data['docker_compose'] = {}
        config_data['docker_compose']['yaml'] = docker_compose
        config_data['docker_compose']['override_yaml'] = docker_compose_override

    def _render_template(self, template_data, search_path):
        template = Template(search_path)
        return template.render(self.template_file, template_data)
