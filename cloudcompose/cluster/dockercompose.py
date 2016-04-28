from cloudcompose.template import Template
from os.path import join, isfile, isdir

class DockerCompose:
    def __init__(self):
        self.config_dirs = ['cloud-compose', '.']
        self.docker_compose_files = ['docker-compose.yml', 'docker-compose.yaml']
        self.docker_compose_override_files = ['docker-compose.override.template.yml', 'docker-compose.override.template.yaml']

    def yaml_files(self, config_data):
        docker_compose = self._read_docker_compose()
        docker_compose_override = self._render_docker_compose_override(config_data)
        return docker_compose, docker_compose_override

    def _read_docker_compose(self):
        for docker_compose_dir in ['.', '..']:
            for docker_compose_file in self.docker_compose_files:
                docker_compose_path = join(docker_compose_dir, docker_compose_file)
                if isfile(docker_compose_path):
                    return self._read_file(docker_compose_path)

    def _read_file(self, file_path):
        with open(file_path, 'r') as f:
            contents = f.read()
        return contents

    def _render_docker_compose_override(self, config_data):
        for config_dir in self.config_dirs:
            template_dir = join(config_dir, 'templates')
            if isdir(template_dir):
                for docker_compose_override_file in self.docker_compose_override_files:
                    template_file = join(template_dir, docker_compose_override_file)
                    if isfile(template_file):
                        return self._render_template(template_file, config_data)

    def _render_template(self, template_file, template_data):
        template = Template()
        return template.render(template_file, template_data)
