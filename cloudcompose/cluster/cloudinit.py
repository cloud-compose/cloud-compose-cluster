from cloudcompose.template import Template
from cloudcompose.cluster.dockercompose import DockerCompose
from os.path import join
from pprint import pprint

class CloudInit():
    def __init__(self, cloud_config):
        self.cloud_config = cloud_config

    def build(self, **kwargs):
        config_data, config_dir = self.cloud_config.config_data('cluster')

        for key, value in kwargs.iteritems():
            config_data['_' + key] = value

        template_dir = join(config_dir, 'templates')
        self._add_docker_compose(template_dir, config_data)
        return self._render_template(template_dir, config_data['template'], config_data)

    def _add_docker_compose(self, template_dir, config_data):
        docker_compose = DockerCompose()
        docker_compose, docker_compose_override = docker_compose.yaml_files(config_data)
        config_data['docker_compose'] = {}
        config_data['docker_compose']['yaml'] = docker_compose
        config_data['docker_compose']['override_yaml'] = docker_compose_override

    def _render_template(self, template_dir, template_file, template_data):
        template = Template(template_dir)
        return template.render(template_file, template_data)
