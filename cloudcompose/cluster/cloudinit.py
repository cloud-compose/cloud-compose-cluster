from cloudcompose.template import Template
from cloudcompose.cluster.dockercompose import DockerCompose
from os.path import join
from pprint import pprint

class CloudInit():
    def build(self, cloud_config):
        config_data, config_dir = cloud_config.config_data('cluster')
        template_dir = join(config_dir, 'templates')
        self._add_docker_compose(template_dir, config_data)
        #pprint(config_data)
        return self._render_template(template_dir, config_data['template'], config_data)

    def _add_docker_compose(self, template_dir, config_data):
        docker_compose = DockerCompose()
        docker_compose, docker_compose_override = docker_compose.yaml_files(config_data)
        config_data['docker_compose'] = {}
        config_data['docker_compose']['yaml'] = docker_compose
        config_data['docker_compose']['override_yaml'] = docker_compose_override

    def _render_template(self, template_dir, template_file, template_data):
        template = Template()
        return template.render(join(template_dir, template_file), template_data)
